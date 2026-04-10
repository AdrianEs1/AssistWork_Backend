import requests
from datetime import datetime
from sqlalchemy.orm import Session
from apps.database import SessionLocal
from apps.models.oauth_connection import OAuthConnection
from apps.models.user import User  # 🔥 Importante para cargar metadatos de la tabla 'users'
from apps.services.oauth.oauth_service import oauth_service


class MicrosoftServiceBase:

    BASE_URL = "https://graph.microsoft.com/v1.0"
    PROVIDER = "microsoft"

    def __init__(self, service_name: str):
        self.service_name = service_name.lower()
        

    def _get_integration_name(self):
        return f"{self.PROVIDER}:{self.service_name}"

    

    # -------------------- CORE --------------------

    def get_access_token(self, user_id: str) -> str:
        db = SessionLocal()
        integration= self._get_integration_name()
        try:
            oauth_conn = (
                db.query(OAuthConnection)
                .filter_by(user_id=user_id, integration=integration, is_active=True)
                .first()
            )

            if not oauth_conn:
                raise ValueError(f"No hay conexión activa para {integration}")

            token = oauth_service.get_valid_access_token(oauth_conn, db)

            oauth_conn.last_used_at = datetime.utcnow()
            try:
                db.commit()
            except Exception:
                db.rollback()
                raise

            return token

        finally:
            db.close()

    def _get_headers(self, access_token: str):
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

    # -------------------- REQUEST BASE --------------------

    def _request(self, method: str, endpoint: str, access_token: str, retry=True, **kwargs):
        url = f"{self.BASE_URL}{endpoint}"
        
        # 🔥 Extraer user_id para no pasarlo a requests.request
        user_id = kwargs.pop("user_id", None)

        response = requests.request(
            method,
            url,
            headers=self._get_headers(access_token),
            **kwargs
        )

        if response.status_code == 401 and retry:
            # 🔄 intentar refrescar token automáticamente
            if user_id:
                print(f"🔄 Token de {self.service_name} expirado (401), reintentando refresh...")
                new_token = self.get_access_token(user_id)
                # Volvemos a meter user_id para la recursión si es necesario (aunque retry=False)
                return self._request(method, endpoint, new_token, retry=False, user_id=user_id, **kwargs)

        if response.status_code == 403:
            raise ValueError("Permisos insuficientes para Microsoft API")

        if response.status_code >= 400:
            raise Exception(f"Microsoft API error: {response.text}")

        return response.json()

    # -------------------- TEST --------------------

    def test_connection(self, user_id: str):
        try:
            token = self.get_access_token(user_id)

            # Pasamos user_id en kwargs para que _request pueda reintentar si falla
            data = self._request("GET", "/me", token, user_id=user_id)

            return {
                "success": True,
                "message": "Conexión exitosa con Microsoft",
                "data": data
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }