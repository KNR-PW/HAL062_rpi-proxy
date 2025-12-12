import asyncio
import serial_asyncio
import sys

USB_CAN_INT1_PORT = "/dev/ttyUSB0"
USB_CAN_INT2_PORT = "/dev/ttyUSB1"
USB_CAN_EXT_PORT = ""
SERIAL_BAUDRATE = 2000000

MESSAGE_WIDTH = 19
LISTEN_PORTS = [8888, 8889, 8890, 8891]

# Store connected clients
client_writers = {}

TX_queue = asyncio.Queue()
RX_queue = asyncio.Queue() 


USB_CAN_INT_SETUP = [
    0xaa,     #  0  Packet header
    0x55,     #  1  Packet header
    0x02,     #  3  Type 
    0x09,     #  3  CAN Baud Rate (50k) 
    0x01,     #  4  Frame Type: Extended Frame  ##   0x01 standard frame,   0x02 extended frame ##
    0x00,     #  5  Filter ID1
    0x00,     #  6  Filter ID2
    0x00,     #  7  Filter ID3
    0x00,     #  8  Filter ID4
    0x00,     #  9  Mask ID1
    0x00,     #  10 Mask ID2
    0x00,     #  11 Mask ID3
    0x00,     #  12 Mask ID4
    0x00,     #  13 CAN mode
    0x01,     #  14 automatic resend
    0x00,     #  15 Spare
    0x00,     #  16 Spare
    0x00,     #  17 Spare
    0x00,     #  18 Spare
]

USB_CAN_EXT_SETUP = [
    0xaa,     #  0  Packet header
    0x55,     #  1  Packet header
    0x02,     #  3  Type 
    0x03,     #  3  CAN Baud Rate (500k)
    0x01,     #  4  Frame Type: Extended Frame  ##   0x01 standard frame,   0x02 extended frame ##
    0x00,     #  5  Filter ID1
    0x00,     #  6  Filter ID2
    0x00,     #  7  Filter ID3
    0x00,     #  8  Filter ID4
    0x00,     #  9  Mask ID1
    0x00,     #  10 Mask ID2
    0x00,     #  11 Mask ID3
    0x00,     #  12 Mask ID4
    0x00,     #  13 CAN mode
    0x01,     #  14 automatic resend
    0x00,     #  15 Spare
    0x00,     #  16 Spare
    0x00,     #  17 Spare
    0x00,     #  18 Spare
]

def create_can_frame(can_id, can_data):
    # constucting the can converter frame
    # 0-4   header
    # 5-8   CAN frame ID 
    # 9     CAN frame data lenght
    # 10-17 CAN frame data
    # 18    reserve
    # 19    CRC 
    frame = [0xAA, 0x55, 0x01, 0x01, 0x01, can_id & 0x00FF, can_id & 0xFF00, 0x00, 0x00, 0x08] + can_data + [0x00]
    frame.append(calculate_checksum(frame))
    return frame

def calculate_checksum(data):
    checksum = sum(data[2:])
    return checksum & 0xFF


async def can_writer_task(can_reader, can_writer, TX_queue):
    while True:
        await can_int1_writer.drain()

        data = await TX_queue.get()

        # fuck comms format and ones who came up with it
        try:
            data = data.replace("X", "0")
            can_id = int(data[1:3], 16)
            can_data = [int(data[i:i+2], 16) for i in range(3, 19, 2)]
        except Exception:
            continue

        frame = create_can_frame(can_id, can_data)

        can_int1_writer.write(bytes(frame))

        try:
           await asyncio.wait_for() 


async def can_reader_task(can_reader):
    while True:
        data = await can_reader.readexactly(20)
        if not (data[0] == 0xAA) and (data[1] == 0x55):  # frame header
            await can_reader.read()
            continue

        await RX_queue.put(data[5:6] + data[10:18])


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    client_address = writer.get_extra_info("peername")
    port = writer.get_extra_info("sockname")

    print(f"Client {client_address} connected on port {port}")

    client_writers[client_address] = writer

    try:
        while True:
            data = await reader.read(MESSAGE_WIDTH)
            if not data: break

            await TX_queue.put(data.decode("utf-8"))

    finally:
        writer.close()
        await writer.wait_closed()

        print(f"Client {client_address} disconnected")
        del client_writers[client_address]


async def feedback_transmit_task():
    while True:
        message = await RX_queue.get()
        print(message)

        writers = list(client_writers.values())
        for writer in writers:
            writer.write(message)
        await asyncio.gather(*[writer.drain() for writer in writers])


async def start_servers():
    # 1. Uruchom serwery TCP (raz, dzialaja niezaleznie od USB)
    for port in LISTEN_PORTS:
        server = await asyncio.start_server(handle_client, '0.0.0.0', port)
        print(f"Listening on 0.0.0.0:{port}")
        asyncio.create_task(server.serve_forever())

    asyncio.create_task(feedback_transmit_task())

    USB_CAN_INT_SETUP.append(calculate_checksum(setup_frame))
    USB_CAN_EXT_SETUP.append(calculate_checksum(setup_frame))

    # 2. Petla nieskonczona obslugujaca restartowanie USB
    while True:
        writers_to_close = []
        try:
            print("Connecting to CAN adapters...")
            
            # Otwarcie polaczen
            r1, w1 = await serial_asyncio.open_serial_connection(url=USB_CAN_INT1_PORT, baudrate=SERIAL_BAUDRATE)
            writers_to_close.append(w1)
            
            r2, w2 = await serial_asyncio.open_serial_connection(url=USB_CAN_INT2_PORT, baudrate=SERIAL_BAUDRATE)
            writers_to_close.append(w2)

            r_ext, w_ext = await serial_asyncio.open_serial_connection(url=USB_CAN_INT2_PORT, baudrate=SERIAL_BAUDRATE)
            writers_to_close.append(w_ext)

            # Konfiguracja (tworzymy kopie listy zeby nie dodawac checksum w nieskonczonosc)
            w1.write(bytes(USB_CAN_INT_SETUP))
            w2.write(bytes(USB_CAN_INT_SETUP))
            w_ext.write(bytes(USB_CAN_EXT_SETUP))
            await w1.drain()
            await w2.drain()
            await w_ext.drain()

            print("CAN connected. Starting tasks...")

            # Uruchomienie taskow komunikacji
            can1_read = asyncio.create_task(can_reader_task(r1))
            can2_read = asyncio.create_task(can_reader_task(r2))
            can_ext_read = asyncio.create_task(can_reader_task(r_ext))
            can_write = asyncio.create_task(can_writer_task(w1, w2, w_ext))

            # Czekamy az ktorykolwiek task padnie (np. przez odpiecie kabla)
            done, pending = await asyncio.wait(
                        [can1_read, can2_read, can_ext_read, can_write], 
                        return_when=asyncio.FIRST_COMPLETED
                    )

            print("Connection lost! Restarting...")
            for task in pending: task.cancel()

        except Exception as e:
            print(f"Connection error: {e}. Retrying in 5s...")
        
        finally:
            # Sprzatanie starych writerow
            for w in writers_to_close:
                try:
                    w.close()
                    await w.wait_closed()
                except: pass

    await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(start_servers())
    except KeyboardInterrupt:
        print("\nProxy stopped.")


