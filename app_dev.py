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

_KILL_TREE = r"""
kill_tree() {
    for child in $(pgrep -P "$1" 2>/dev/null); do
        kill_tree "$child"
    done
    kill -9 "$1" 2>/dev/null
}

PIDS=$(ps -eo pid,args \
    | grep -E '[p]ython3?( -[^ ]+)* .*(^| )(app|app_dev)\.py( |$)' \
    | awk -v self="$SELF" -v parent="$PARENT" '$1 != self && $1 != parent {print $1}')

if [ -n "$PIDS" ]; then
    echo "Found existing process(es): $PIDS. Killing processes and kernels..."
    for PID in $PIDS; do
        kill_tree "$PID"
    done
fi
"""

subprocess.run(
    _KILL_TREE,
    shell=True,
    executable="/bin/bash",
    env={**os.environ, "SELF": str(os.getpid()), "PARENT": str(os.getppid())},
)
ipystream.run(use_xpython=False, show_logo=False, port=port, disable_extensions=True)
