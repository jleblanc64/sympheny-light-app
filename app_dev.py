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
set -f
pids=$(pgrep -f "$PATTERN")

declare -A parents
victims=()

for pid in $pids; do
  [ "$pid" = "$$" ] && continue
  [ "$pid" = "$PPID" ] && continue
  ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
  [ -z "$ppid" ] && continue
  [ "$ppid" = "$$" ] && continue
  [ "$ppid" = "$PPID" ] && continue
  victims+=("$pid")
  parents["$ppid"]=1
done

# kill children first
for pid in "${victims[@]}"; do
  echo "killing kernel $pid"
  kill -9 "$pid" 2>/dev/null
done

# then kill each unique parent exactly once, and only if it still exists
for ppid in "${!parents[@]}"; do
  if [ "$ppid" -gt 1 ] && kill -0 "$ppid" 2>/dev/null; then
    echo "killing parent $ppid"
    kill -9 "$ppid" 2>/dev/null
  fi
done
exit 0
'''

tag = "light-app-"
result = subprocess.run(["bash", "-c", SCRIPT], capture_output=True, text=True,
                        env={**os.environ, "PATTERN": tag})
print(result.stdout, result.stderr)

ipystream.run(tag=tag, use_xpython=False, show_logo=False, port=port, disable_extensions=True)
