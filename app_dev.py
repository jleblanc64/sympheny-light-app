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

subprocess.run(f"ps -eo pid,args | grep -E '[p]ython3? app.py' | awk '$1 != {os.getpid()} {{print $1}}' | xargs -r kill -9", shell=True)
subprocess.run(f"ps -eo pid,args | grep -E '[p]ython3? app_dev.py' | awk '$1 != {os.getpid()} {{print $1}}' | xargs -r kill -9", shell=True)
subprocess.run(f"ps -eo pid,args | grep -E '[p]ython3? -u app.py' | awk '$1 != {os.getpid()} {{print $1}}' | xargs -r kill -9", shell=True)
subprocess.run(f"ps -eo pid,args | grep -E '[p]ython3? -u app_dev.py' | awk '$1 != {os.getpid()} {{print $1}}' | xargs -r kill -9", shell=True)
ipystream.run(use_xpython=False, show_logo=False, port=port, disable_extensions=True)
