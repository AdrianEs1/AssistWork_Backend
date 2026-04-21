import requests
from datetime import datetime
from apps.database import SessionLocal
from apps.models.oauth_connection import OAuthConnection
from apps.services.oauth.oauth_service import oauth_service

class HubSpotServiceBase:
    BASE_URL = "https://api.hubapi.com"
    INTEGRATION = "hubspot:crm"

    def get_access_token(self, user_id: str) -> str:
        db = SessionLocal()
        try:
            oauth_conn = (
                db.query(OAuthConnection)
                .filter_by(user_id=user_id, integration=self.INTEGRATION, is_active=True)
                .first()
            )
            if not oauth_conn:
                raise ValueError("No hay conexión activa para HubSpot")
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

    def _get_headers(self, access_token: str) -> dict:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

    def _request(self, method: str, endpoint: str, access_token: str, retry=True, **kwargs):
        url = f"{self.BASE_URL}{endpoint}"
        user_id = kwargs.pop("user_id", None)
        response = requests.request(
            method,
            url,
            headers=self._get_headers(access_token),
            **kwargs
        )
        if response.status_code == 401 and retry and user_id:
            print(f"🔄 Token de HubSpot expirado (401), reintentando refresh...")
            new_token = self.get_access_token(user_id)
            return self._request(method, endpoint, new_token, retry=False, user_id=user_id, **kwargs)
        if response.status_code == 403:
            raise ValueError("Permisos insuficientes para HubSpot API")
        if response.status_code == 404:
            raise ValueError("Recurso no encontrado en HubSpot")
        if response.status_code >= 400:
            raise Exception(f"HubSpot API error: {response.text}")
        if response.status_code == 204:
            return {}
        return response.json()

    def test_connection(self, user_id: str) -> dict:
        try:
            token = self.get_access_token(user_id)
            data = self._request("GET", "/crm/v3/objects/contacts?limit=1", token, user_id=user_id)
            return {"success": True, "message": "✅ Conexión exitosa con HubSpot", "data": data}
        except Exception as e:
            return {"success": False, "error": str(e)}