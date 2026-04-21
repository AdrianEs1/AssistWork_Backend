# Debo crear cuenta en HubSpot para developers
#  Crear app
#  Obtener credentials para app (client, secret)
#  configurar scopes
#  codear modulos para logica del provider HubSpot

import requests
from .base_provider import BaseOAuthProvider
from config import HUBSPOT_CLIENT_ID, HUBSPOT_CLIENT_SECRET, REDIRECT_URI

class HubSpotOAuthProvider(BaseOAuthProvider):
    AUTH_URL = "https://app.hubspot.com/oauth/authorize"
    TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"

    def generate_auth_url(self, user_id, scopes, state):
        return (
            f"{self.AUTH_URL}"
            f"?client_id={HUBSPOT_CLIENT_ID}"
            f"&redirect_uri={REDIRECT_URI}"
            f"&scope={' '.join(scopes)}"
            f"&state={state}"
        )

    def exchange_code(self, code, scopes: list = None):
        response = requests.post(self.TOKEN_URL, data={
            "grant_type": "authorization_code",
            "client_id": HUBSPOT_CLIENT_ID,
            "client_secret": HUBSPOT_CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "code": code,
        })
        if response.status_code != 200:
            raise Exception(f"Error intercambiando code: {response.text}")
        return response.json()

    def refresh_token(self, refresh_token):
        response = requests.post(self.TOKEN_URL, data={
            "grant_type": "refresh_token",
            "client_id": HUBSPOT_CLIENT_ID,
            "client_secret": HUBSPOT_CLIENT_SECRET,
            "refresh_token": refresh_token,
        })
        if response.status_code != 200:
            raise Exception(f"Error refrescando token: {response.text}")
        return response.json()

    def get_user_info(self, access_token: str, scopes: list = None, id_token: str = None) -> dict:
        response = requests.get(
            "https://api.hubapi.com/oauth/v1/access-tokens/" + access_token
        )
        if response.status_code != 200:
            return {"email": None}
        data = response.json()
        return {
            "email": data.get("user"),
            "hub_id": data.get("hub_id"),
            "hub_domain": data.get("hub_domain"),
        }

    def revoke_token(self, token: str) -> bool:
        try:
            # HubSpot revoca por refresh_token, no por access_token
            response = requests.delete(
                f"https://api.hubapi.com/oauth/v1/refresh-tokens/{token}"
            )
            return response.status_code in [200, 204]
        except Exception:
            return False