
home/knr-admin/proxy/proxy.sh: 

``` bash
#!/bin/bash
sleep 1
cd /home/knr-admin//proxy
while:
do:
	/home/knr-admin/proxy/.venv/bin/python3 can_proxy.py >> /home/knr-admin/proxy/logs.txt 2>&1
sleep 5
done
```

```bash
crontab -e: @reboot /home/knr-admin/proxy/proxy.sh
```
