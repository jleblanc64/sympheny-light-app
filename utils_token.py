from ipystream.voila.login import token_to_user_generic


def token_to_user(token):
    token_issuers = ["https://login.sympheny.com/", "https://sympheny.eu.auth0.com/", "https://login.dev.sympheny.com/",
                     "https://dev-zaxc2-zd.eu.auth0.com/"]
    token_decoded_to_user_fun = lambda d: d["https://sympheny.com/email"]
    return token_to_user_generic(token, token_issuers, token_decoded_to_user_fun)