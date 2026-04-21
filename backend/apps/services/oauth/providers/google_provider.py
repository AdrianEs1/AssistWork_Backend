import requests
import jwt  # PyJWT - para extraer sub del id_token sin userinfo
from .base_provider import BaseOAuthProvider
from config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    REDIRECT_URI
)

USERINFO_SCOPES = {"openid", "email", "profile"}

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

    def get_user_info(self, access_token: str, scopes: list = None, id_token: str = None) -> dict:
        """
        Obtiene info del usuario según los scopes disponibles:
        - Con openid/email/profile → llama a userinfo endpoint
        - Sin ellos (ej: sheets) → extrae 'sub' del id_token o retorna info mínima
        """
        granted_scopes = set(scopes or [])
        has_userinfo = bool(USERINFO_SCOPES & granted_scopes)

        if has_userinfo:
            response = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            if response.status_code != 200:
                raise Exception(f"Error obteniendo usuario: {response.text}")
            return response.json()

        # Sin scopes de userinfo: extraer 'sub' del id_token si está disponible
        user_id = None
        if id_token:
            try:
                payload = jwt.decode(id_token, options={"verify_signature": False})
                user_id = payload.get("sub")
            except Exception:
                pass

        return {
            "id": user_id,
            "email": None,
            "name": None,
            "picture": None
        }

    def revoke_token(self, token: str) -> bool:
        try:
            response = requests.post(
                'https://oauth2.googleapis.com/revoke',
                params={'token': token},
                headers={'content-type': 'application/x-www-form-urlencoded'}
            )
            return response.status_code in [200, 400]
        except Exception:
            return False