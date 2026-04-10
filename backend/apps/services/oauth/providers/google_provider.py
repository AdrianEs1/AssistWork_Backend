import requests
from .base_provider import BaseOAuthProvider
from config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    REDIRECT_URI
)


class GoogleOAuthProvider(BaseOAuthProvider):

    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    def generate_auth_url(self, user_id, scopes, state):
        return (
            f"{self.AUTH_URL}"
            f"?client_id={GOOGLE_CLIENT_ID}"
            f"&redirect_uri={REDIRECT_URI}"
            f"&response_type=code"
            f"&scope={' '.join(scopes)}"
            f"&state={state}"
            f"&access_type=offline"
            f"&prompt=consent"
        )

    def exchange_code(self, code, scopes: list = None):
        response = requests.post(self.TOKEN_URL, data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI
        })

        if response.status_code != 200:
            raise Exception(f"Error intercambiando code: {response.text}")

        return response.json()

    def refresh_token(self, refresh_token):
        response = requests.post(self.TOKEN_URL, data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        })

        if response.status_code != 200:
            raise Exception(f"Error refrescando token: {response.text}")

        return response.json()

    def get_user_info(self, access_token):
        response = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )

        if response.status_code != 200:
            raise Exception(f"Error obteniendo usuario: {response.text}")

        return response.json()

    def revoke_token(self, token: str) -> bool:
        """Revoca el token en Google"""
        try:
            response = requests.post(
                'https://oauth2.googleapis.com/revoke',
                params={'token': token},
                headers={'content-type': 'application/x-www-form-urlencoded'}
            )
            return response.status_code in [200, 400]
        except Exception:
            return False