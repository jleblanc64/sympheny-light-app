import base64
import json
from jproperties import Properties
import requests as r

def load_password(path: str) -> tuple[str, str, str]:
    configs = load_config(path)
    p = configs.get("password").data
    return p

def load_config(path: str) -> Properties:
    configs = Properties()
    with open(path, "rb") as f:
        configs.load(f)

    return configs

def get_jwt(u, p , base_url) -> str:
    url = f"{base_url}backoffice/auth/ext/token"
    data = {"email": u, "password": p}
    headers = {"content-type": "application/json"}

    resp = r.post(url, headers=headers, json=data)
    return resp.json()["access_token"]

def decode_token(jwt):
    payload = jwt.split('.')[1]
    payload += '=' * (4 - len(payload) % 4)
    return json.loads(base64.b64decode(payload))

def get_creds_from_token(jwt):
    h = {"authorization": f"Bearer {jwt}", "content-type": "application/json"}

    aud = decode_token(jwt)["aud"]
    base_dev = "https://eu-north-1-api.dev.sympheny.com"
    base_prod = "https://eu-north-1-api.sympheny.com"
    base_url = base_dev if base_dev in aud else base_prod
    base_url = f"{base_url}/"

    be = f"{base_url}sympheny-app/"
    return {"base_url": base_url, "be": be, "h": h}
