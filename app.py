import ipystream
from ipystream.voila.utils import is_sagemaker, PARAM_KEY_TOKEN
from utils_login import get_jwt, load_password
from utils_token import token_to_user

port = 8866

if not is_sagemaker():
    username = "charles.dabadie@sympheny.com"
    password = load_password(f"/home/charles/Desktop/SEP_PROD.properties")
    base_url = "https://eu-north-1-api.sympheny.com/"

    jwt = get_jwt(username, password, base_url)
    print(f"APP: http://localhost:{port}?{PARAM_KEY_TOKEN}={jwt}")

ipystream.run(enforce_PARAM_KEY_TOKEN=True, token_to_user_fun=token_to_user, show_logo=False, show_app_url=False, port=port)
