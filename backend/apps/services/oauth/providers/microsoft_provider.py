import requests
from urllib.parse import urlencode # 🔥 Para codificar parámetros correctamente
from .base_provider import BaseOAuthProvider
from config import MICROSOFT_CLIENT_SECRET, MICROSOFT_ID_CLIENT, REDIRECT_URI

class MicrosoftOAuthProvider(BaseOAuthProvider):

    AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

    def generate_auth_url(self, user_id, scopes, state):
        params = {
            "client_id": MICROSOFT_ID_CLIENT,
            "response_type": "code",
            "response_mode": "query", 
            "redirect_uri": REDIRECT_URI,
            "scope": " ".join(scopes),
            "state": state,
            "prompt": "consent" # 🔥 Forzar pantalla de consentimiento para actualizar scopes
        }

        url=f"{self.AUTH_URL}?{urlencode(params)}"
        print(f"Esta es la URL generada para Scopes de Microsoft: {url}")
        return url

    def exchange_code(self, code, scopes: list = None):
        data = {
            "client_id": MICROSOFT_ID_CLIENT,
            "client_secret": MICROSOFT_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        }
        if scopes:
            data["scope"] = " ".join(scopes)   # ✅ Agregar scopes al exchange

        response = requests.post(self.TOKEN_URL, data=data)
        return response.json()

    def refresh_token(self, refresh_token):
        response = requests.post(self.TOKEN_URL, data={
            "client_id": MICROSOFT_ID_CLIENT,
            "client_secret": MICROSOFT_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token"
        })
        return response.json()

    def revoke_token(self, token: str) -> bool:
        """
        Revoca el token en Microsoft.
        Nota: Microsoft requiere client_secret para revocar.
        """
        try:
            # Endpoint de revocación v2.0
            # https://learn.microsoft.com/en-us/graph/api/token-revoke
            # OJO: A veces Microsoft usa un endpoint diferente según el tenant.
            # Este es el estándar para apps multi-tenant.
            revoke_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token/revoke"
            
            response = requests.post(revoke_url, data={
                "client_id": MICROSOFT_ID_CLIENT,
                "client_secret": MICROSOFT_CLIENT_SECRET,
                "token": token
            })
            
            return response.status_code == 200
        except Exception as e:
            print(f"⚠️ Error revocando token de Microsoft: {e}")
            return False

    def get_user_info(self, access_token):
        r = requests.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        return r.json()