from utils_login import load_password
import os
import subprocess
import ipystream
from ipystream.voila.utils import OS_JWT_OVERRIDE
import requests as r

port = 8878

username = "charles.dabadie@sympheny.com"
# password = load_password(f"/home/sagemaker-user/creds.txt")
password = load_password(f"/home/charles/Desktop/SEP_PROD.properties")
base_url = "https://eu-north-1-api.sympheny.com/"

os.environ[OS_JWT_OVERRIDE] = r.post(f"{base_url}backoffice/auth/ext/token",
                                     json={"email": username, "password": password}).json()["access_token"]

SCRIPT = r'''
for pid in $(pgrep -f light-app-from-editor); do
  ppid=$(ps -o ppid= -p "$pid" | tr -d ' ')
  echo "killing kernel $pid (parent $ppid)"
  [ "$ppid" -gt 1 ] && kill -9 "$ppid" 2>/dev/null
  kill -9 "$pid" 2>/dev/null
done
exit 0
'''

result = subprocess.run(["bash", "-c", SCRIPT], capture_output=True, text=True)
print(result.stdout, result.stderr)

ipystream.run(tag="light-app-from-editor", use_xpython=False, show_logo=False, port=port, disable_extensions=True)
