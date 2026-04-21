#from google_auth_oauthlib.flow import Flow
#from google.oauth2.credentials import Credentials
#from google.auth.transport.requests import Request
#from google.auth.exceptions import RefreshError
#from googleapiclient.discovery import build
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from apps.models.oauth_connection import OAuthConnection
from apps.models.user import User  # 🔥 Importante para cargar metadatos de la tabla 'users'
from apps.core.encryption import encryption
from .utils import parse_integration, get_integration_config
from .providers.factory_selector import get_oauth_provider
import os
#import secrets
import requests



class OAuthService:
    """
    Servicio centralizado para manejar OAuth de Google con scopes incrementales.
    """

    #SUPPORTED_SERVICES = SUPPORTED_SERVICES

    # -------------------- Helpers --------------------

    """def get_accumulated_scopes(self, user_id: str, db: Session, new_service: str) -> list:
        ""
        Obtiene scopes acumulados de TODOS los servicios (activos e inactivos).
        ""
        all_connections = db.query(OAuthConnection).filter_by(
            user_id=user_id
        ).all()

        accumulated_scopes = []
        for conn in all_connections:
            if conn.service in SUPPORTED_SERVICES:
                accumulated_scopes.extend(SUPPORTED_SERVICES[conn.service]["scopes"])

        # Agregar scopes del nuevo servicio
        if new_service in SUPPORTED_SERVICES:
            accumulated_scopes.extend(SUPPORTED_SERVICES[new_service]["scopes"])
        else:
            raise ValueError(f"Servicio '{new_service}' no soportado al acumular scopes")

        # Eliminar duplicados manteniendo orden
        return list(dict.fromkeys(accumulated_scopes))"""

    """def create_google_flow_with_scopes(self, service: str, scopes: list, redirect_uri: str = None) -> Flow:
        ""Crea el flujo OAuth con scopes personalizados (acumulados). Usará siempre el redirect único por defecto.""
        if service not in SUPPORTED_SERVICES:
            raise ValueError(f"Servicio '{service}' no soportado")

        # Usar siempre el redirect URI fijo (el que registraste en Google Console)
        effective_redirect = redirect_uri or f"{GOOGLE_REDIRECT_URI}/api/oauth/callback"

        client_config = {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                # Incluir el redirect URI fijo (lista) para que la librería tenga el mismo valor
                "redirect_uris": [effective_redirect],
            }
        }

        flow = Flow.from_client_config(
            client_config,
            scopes=scopes,
            redirect_uri=effective_redirect,
        )
        return flow"""

    # -------------------- Autorización --------------------

    def generate_authorization_url(self,user_id: str, integration: str, db):

        config = get_integration_config(integration)
        provider_name = config["provider"]

        provider = get_oauth_provider(provider_name)

        scopes = config["scopes"]
        state = f"{user_id}:{integration}"

        url = provider.generate_auth_url(user_id, scopes, state)

        return url, state

    # -------------------- Callback --------------------

    def handle_callback(self, code: str, state: str, user_id: str, db: Session):

        # 🔹 1. Parse state
        parts = state.split(":", 1)
        if len(parts) != 2:
            raise ValueError("State inválido")

        state_user_id, integration = parts

        if state_user_id != user_id:
            raise ValueError("State inválido")

        # 🔹 2. Config + provider
        config = get_integration_config(integration)
        provider_name = config["provider"]

        provider = get_oauth_provider(provider_name)

        # 🔹 3. Intercambiar code
        # En handle_callback:
        token_data = provider.exchange_code(code, scopes=config.get("scopes", []))

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in")

        if not access_token:
            raise ValueError("No se obtuvo access_token")

        # 🔹 4. Obtener usuario
        user_info = provider.get_user_info(access_token)
        email = user_info.get("email") or user_info.get("mail") or user_info.get("userPrincipalName")

        # 🔹 5. Guardar en DB
        oauth_conn = db.query(OAuthConnection).filter_by(
            user_id=user_id,
            integration=integration
        ).first()

        expires_at = datetime.utcnow() + timedelta(seconds=expires_in or 3600)

        if oauth_conn:
            oauth_conn.set_tokens(access_token, refresh_token)
            oauth_conn.token_expires_at = expires_at
            oauth_conn.meta_data = {"email": email}
            oauth_conn.scopes = config.get("scopes", []) # 🔥 Guardar scopes
            oauth_conn.is_active = True
        else:
            oauth_conn = OAuthConnection(
                user_id=user_id,
                integration=integration,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=expires_at,
                meta_data={"email": email},
                scopes=config.get("scopes", []), # 🔥 Guardar scopes
                is_active=True
            )
            db.add(oauth_conn)

        db.commit()
        db.refresh(oauth_conn)

        return oauth_conn


    # -------------------- Consultas --------------------

    def get_user_connection(
        self, user_id: str, integration: str, db: Session
    ) -> OAuthConnection:
        """Obtiene la conexión OAuth activa del usuario para un servicio"""
        return (
            db.query(OAuthConnection)
            .filter_by(user_id=user_id, integration=integration, is_active=True)
            .first()
        )

    def disconnect_service(self, user_id: str, integration: str, db: Session) -> dict:
        """
        Desconecta un servicio OAuth.
        """
        oauth_conn = self.get_user_connection(user_id, integration, db)
        if not oauth_conn:
            return {"success": False, "revoked": False, "cleaned": False}

        # Cuántos servicios activos hay para este PROVEEDOR (ej: google, microsoft)
        provider_name, _ = parse_integration(integration)
        remaining_active = db.query(OAuthConnection).filter(
            OAuthConnection.user_id == user_id,
            OAuthConnection.is_active == True,
            OAuthConnection.integration.like(f"{provider_name}:%")
        ).count()

        revoked = False
        cleaned = False

        if remaining_active <= 1: # Es la última del proveedor
            try:
                # ✅ Filtra por proveedor
                token_record = db.query(OAuthConnection).filter(
                    OAuthConnection.user_id == user_id,
                    OAuthConnection.integration.like(f"{provider_name}:%"),
                    OAuthConnection.access_token.isnot(None)
                ).first()

                if token_record and token_record.access_token:
                    access_token = encryption.decrypt(token_record.access_token)
                    refresh_token = encryption.decrypt(token_record.refresh_token) if token_record.refresh_token else None

                    provider_name, _ = parse_integration(integration)
                    provider = get_oauth_provider(provider_name)
                    
                    # 🔥 Usar el método de revocación del provider
                    revoked = provider.revoke_token(access_token)
                    if not revoked and refresh_token:
                        revoked = provider.revoke_token(refresh_token)

                else:
                    revoked = True
                    print(f"ℹ️ No se encontró token para revocar (user {user_id})")

                # ✅ Solo borra las del proveedor desconectado
                db.query(OAuthConnection).filter(
                    OAuthConnection.user_id == user_id,
                    OAuthConnection.integration.like(f"{provider_name}:%")
                ).delete()
                cleaned = True
                db.commit()
                print(f"✅ Registros eliminados para user {user_id} (revocado: {revoked})")

            except Exception as e:
                print(f"❌ Error al revocar/limpiar: {e}")
                db.rollback()

                try:
                    db.refresh(oauth_conn)
                    oauth_conn.is_active = False
                    db.commit()
                    print(f"⚠️ Fallback: servicio {integration} marcado como inactivo")
                except Exception as fallback_error:
                    print(f"❌ Error en fallback: {fallback_error}")
        else:
            oauth_conn.is_active = False
            db.commit()
            print(f"✅ Servicio {integration} desconectado (quedan {remaining_active - 1} activos)")

        return {
            "success": True,
            "revoked": revoked,
            "cleaned": cleaned,
            "remaining_services": max(0, remaining_active - 1)
        }

    # -------------------- Credenciales --------------------

    def get_valid_access_token(self, oauth_conn: OAuthConnection, db: Session):

        if not oauth_conn.is_token_expired():
            return oauth_conn.get_access_token()

        provider_name, _ = parse_integration(oauth_conn.integration)
        provider = get_oauth_provider(provider_name)

        try:
            token_data = provider.refresh_token(oauth_conn.get_refresh_token())
            
            if not token_data or "access_token" not in token_data:
                error_msg = token_data.get("error_description") or token_data.get("error") or "Respuesta de refresh inválida"
                raise ValueError(f"Error al refrescar token de {oauth_conn.integration}: {error_msg}")

            oauth_conn.set_tokens(
                access_token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token")  # 🔥 Microsoft rota aquí
            )

            oauth_conn.token_expires_at = datetime.utcnow() + timedelta(
                seconds=token_data.get("expires_in", 3600)
            )

            oauth_conn.last_used_at = datetime.utcnow()

            try:
                db.commit()
            except Exception:
                db.rollback()
                raise

            return oauth_conn.get_access_token()
            
        except Exception as e:
            print(f"❌ Error crítico refrescando token para {oauth_conn.integration}: {e}")
            # Si el refresh falla catastróficamente (ej: refresh_token revocado), marcamos como inactivo
            oauth_conn.is_active = False
            try:
                db.commit()
            except Exception:
                db.rollback()
            raise ValueError(f"Tu conexión con {oauth_conn.integration} ha expirado y no se pudo renovar. Por favor, vuelve a conectarla. Detalle: {str(e)}")

    # -------------------- Reconectar Servicios --------------------

    def reconnect_service(self, user_id: str, integration: str, db: Session):

        oauth_conn = db.query(OAuthConnection).filter_by(
            user_id=user_id,
            integration=integration,
            is_active=False
        ).first()

        if not oauth_conn:
            return {"reconnected": False, "needs_oauth": True}

        # 🔹 1. Verificar si hay cambios en los scopes requeridos
        config = get_integration_config(integration)
        required_scopes = set(config.get("scopes", []))
        current_scopes = set(oauth_conn.scopes or [])

        if not current_scopes or not required_scopes.issubset(current_scopes):
            print(f"🔄 Scopes cambiados o no almacenados para {integration}. Forzando OAuth.")
            return {"reconnected": False, "needs_oauth": True}

        # 🔹 2. Verificar si hay otra conexión activa del MISMO PROVEEDOR
        provider_name, _ = parse_integration(integration)
        another_active = db.query(OAuthConnection).filter(
            OAuthConnection.user_id == user_id,
            OAuthConnection.is_active == True,
            OAuthConnection.integration.like(f"{provider_name}:%"),
            OAuthConnection.integration != integration
        ).first()

        if not another_active:
            # Si no hay nada activo del mismo proveedor, mejor forzar OAuth para refrescar estado
            return {"reconnected": False, "needs_oauth": True}

        oauth_conn.is_active = True
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

        return {
            "reconnected": True,
            "message": f"{integration} reactivado automáticamente"
        }


# Singleton
oauth_service = OAuthService()