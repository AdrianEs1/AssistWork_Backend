from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from sqlalchemy.orm import Session
from datetime import datetime
from apps.models.oauth_connection import OAuthConnection
from apps.core.encryption import encryption
import os
import secrets
import requests



# 🔧 Configuración base de Google OAuth
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")


# 🎯 Servicios soportados
SUPPORTED_SERVICES = {
    "gmail": {
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            
        ],
        "profile_api": (
            "gmail",
            "v1",
            lambda service: service.users().getProfile(userId="me").execute(),
        ),
        "extract_email": lambda profile: profile.get("emailAddress"),
    },

    
}


class OAuthService:
    """
    Servicio centralizado para manejar OAuth de Google con scopes incrementales.
    """

    SUPPORTED_SERVICES = SUPPORTED_SERVICES

    # -------------------- Helpers --------------------

    def get_accumulated_scopes(self, user_id: str, db: Session, new_service: str) -> list:
        """
        Obtiene scopes acumulados de TODOS los servicios (activos e inactivos).
        """
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
        return list(dict.fromkeys(accumulated_scopes))

    def create_google_flow_with_scopes(self, service: str, scopes: list, redirect_uri: str = None) -> Flow:
        """Crea el flujo OAuth con scopes personalizados (acumulados). Usará siempre el redirect único por defecto."""
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
        return flow

    def _revoke_google_token(self, access_token: str, refresh_token: str = None) -> bool:
        """
        Revoca el token en Google.
        """
        success = self._revoke_token_request(access_token)

        if not success and refresh_token:
            # Fallback a refresh_token si access_token falla
            success = self._revoke_token_request(refresh_token)

        return success

    def _revoke_token_request(self, token: str) -> bool:
        """
        Hace la petición HTTP de revocación a Google.
        """
        if not token:
            # Nada que revocar
            return True

        try:
            response = requests.post(
                'https://oauth2.googleapis.com/revoke',
                params={'token': token},
                headers={'content-type': 'application/x-www-form-urlencoded'}
            )

            # 200 = revocado; 400 = inválido o ya revocado (lo tratamos como éxito)
            if response.status_code in [200, 400]:
                return True
            else:
                # Log para diagnosticar
                print(f"❌ Error revocando token: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            print(f"❌ Excepción revocando token: {e}")
            return False

    # -------------------- Autorización --------------------

    def generate_authorization_url(self, user_id: str, service: str, db: Session) -> tuple:
        """Genera la URL de autorización de Google OAuth con scopes acumulados."""
        
        # Obtener scopes acumulados
        scopes = self.get_accumulated_scopes(user_id, db, service)
        
        # Crear flow con TODOS los scopes acumulados
        flow = self.create_google_flow_with_scopes(service, scopes)
        
        # ✅ Generar state personalizado
        custom_state = f"{user_id}:{service}:{secrets.token_urlsafe(32)}"
        
        # ✅ Google retorna el mismo state que le pasamos
        authorization_url, returned_state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
            state=custom_state,  # ← Google lo retornará tal cual en el callback
        )
        
        # ✅ Retornar el state original (no el de Google, que es el mismo)
        return authorization_url, custom_state

    # -------------------- Callback --------------------

    def handle_callback(
        self, code: str, state: str, user_id: str, service: str, db: Session
    ) -> OAuthConnection:
        """
        Maneja el callback de OAuth y actualiza TODAS las conexiones existentes.
        Se espera que el `state` tenga el formato: "user_id:service:nonce"

        Notas:
        - Se IGNORA el `service` pasado por la ruta y se toma el del state (fuente de verdad).
        - Para mitigación básica de replay se guarda/consulta `last_oauth_nonce` en meta_data
        del registro de la conexión del servicio actual (si existe).
        """
        # 1) Parseo y validación estricta del state
        try:
            parts = state.split(":", 2)
            if len(parts) != 3:
                raise ValueError("State inválido: formato esperado 'user_id:service:nonce'")
            state_user_id, state_service, nonce = parts
            if state_user_id != user_id:
                raise ValueError("State inválido: user_id no coincide")
            # Usamos el service del state como fuente de verdad
            service_from_state = state_service
        except Exception as e:
            raise ValueError(f"State inválido - posible ataque CSRF ({e})")

        # 2) Validar que el servicio sea soportado
        if service_from_state not in SUPPORTED_SERVICES:
            raise ValueError(f"Servicio '{service_from_state}' no soportado")

        # 3) Evitar replay: comprobar nonce en DB (guardado previo en meta_data["last_oauth_nonce"])
        #    Nota: esto es una mitigación simple; para alta concurrencia/distribuido usar store central (Redis).
        try:
            existing_conns = db.query(OAuthConnection).filter_by(user_id=user_id).all()
            for c in existing_conns:
                meta = c.meta_data or {}
                if meta.get("last_oauth_nonce") == nonce:
                    raise ValueError("State ya utilizado (posible replay)")
        except ValueError:
            # reenviar la excepción hacia arriba
            raise
        except Exception:
            # si falla la comprobación por alguna razón, seguimos (no queremos bloquear por un fallo no crítico)
            pass

        # 4) Obtener scopes acumulados (no modifica DB)
        scopes = self.get_accumulated_scopes(user_id, db, service_from_state)

        # 5) Intercambiar code por tokens (usar redirect fijo dentro de create_google_flow_with_scopes)
        try:
            flow = self.create_google_flow_with_scopes(service_from_state, scopes)
            flow.fetch_token(code=code)
            credentials = flow.credentials
        except Exception as e:
            raise ValueError(f"Error intercambiando code por tokens: {e}")

        if not credentials or not getattr(credentials, "token", None):
            raise ValueError("No se obtuvieron credenciales válidas desde Google")

        # 6) Extraer perfil (proteger contra errores de API)
        try:
            api_name, api_version, get_profile_fn = SUPPORTED_SERVICES[service_from_state]["profile_api"]
            google_service = build(api_name, api_version, credentials=credentials)
            profile = get_profile_fn(google_service)
            email = SUPPORTED_SERVICES[service_from_state]["extract_email"](profile)
        except Exception as e:
            # No actualizamos tokens si no podemos verificar perfil; retornamos error claro.
            raise ValueError(f"Error obteniendo perfil desde la API de Google: {e}")

        # 7) Si no se pudo extraer un email, lo permitimos pero advertimos (no bloquear estrictamente)
        if not email:
            # Dependiendo de tu lógica podrías querer bloquear aquí; por ahora lo dejamos como advertencia.
            # raise ValueError("No se pudo obtener email del perfil de Google")
            print("⚠️ Advertencia: no se obtuvo email al extraer perfil de Google")

        # 8) Preparar tokens a guardar: si refresh_token es None, intentar reutilizar uno existente
        try:
            # Buscar cualquier token existente (activo o no) para recuperar refresh si Google no lo envía
            any_token_record = db.query(OAuthConnection).filter_by(user_id=user_id).filter(
                OAuthConnection.refresh_token.isnot(None)
            ).first()
        except Exception:
            any_token_record = None

        access_token_plain = getattr(credentials, "token", None)
        refresh_token_plain = getattr(credentials, "refresh_token", None)

        if not refresh_token_plain and any_token_record and any_token_record.refresh_token:
            try:
                refresh_token_plain = encryption.decrypt(any_token_record.refresh_token)
            except Exception:
                # si falla desencriptar, dejamos refresh_token_plain como None
                refresh_token_plain = None

        # Encriptar tokens solo si existen
        encrypted_access_token = encryption.encrypt(access_token_plain) if access_token_plain else None
        encrypted_refresh_token = encryption.encrypt(refresh_token_plain) if refresh_token_plain else None

        # 9) Antes de escribir, actualizamos meta_data con nonce para mitigar replays futuros
        #    (si existe current_conn se actualizará; si no existe, lo incluiremos al crear)
        try:
            # Actualizar todas las conexiones existentes *solo después* de validar todo lo anterior
            existing_connections = db.query(OAuthConnection).filter_by(user_id=user_id).all()

            for conn in existing_connections:
                # No sobrescribimos refresh_token con None
                if encrypted_access_token:
                    conn.access_token = encrypted_access_token
                if encrypted_refresh_token:
                    conn.refresh_token = encrypted_refresh_token
                conn.token_expires_at = credentials.expiry
                conn.scopes = scopes
                conn.connected_at = datetime.utcnow()
                # no tocar last_used_at aquí (es para cuando se usan las credenciales)
                meta = conn.meta_data or {}
                # Guardar último nonce usado para mitigar replay (por usuario/servicio)
                meta["last_oauth_nonce"] = nonce
                # Guardar email en meta (opcional)
                if email:
                    meta["email"] = email
                conn.meta_data = meta

            # 10) Crear o actualizar registro del servicio actual
            current_conn = db.query(OAuthConnection).filter_by(
                user_id=user_id,
                service=service_from_state
            ).first()

            meta_for_conn = {"email": email}
            # opcional: guardar client_id (no guardar client_secret)
            if GOOGLE_CLIENT_ID:
                meta_for_conn["client_id"] = GOOGLE_CLIENT_ID
            meta_for_conn["last_oauth_nonce"] = nonce

            if current_conn:
                if encrypted_access_token:
                    current_conn.access_token = encrypted_access_token
                if encrypted_refresh_token:
                    current_conn.refresh_token = encrypted_refresh_token
                current_conn.token_expires_at = credentials.expiry
                current_conn.scopes = scopes
                current_conn.service_user_id = email
                current_conn.is_active = True
                # Fusionar meta_data existente (no borrar campos previos)
                existing_meta = current_conn.meta_data or {}
                existing_meta.update(meta_for_conn)
                current_conn.meta_data = existing_meta
                current_conn.connected_at = datetime.utcnow()
            else:
                current_conn = OAuthConnection(
                    user_id=user_id,
                    service=service_from_state,
                    access_token=encrypted_access_token,
                    refresh_token=encrypted_refresh_token,
                    token_expires_at=credentials.expiry,
                    scopes=scopes,
                    service_user_id=email,
                    is_active=True,
                    meta_data=meta_for_conn,
                )
                db.add(current_conn)

            db.commit()
            db.refresh(current_conn)
            return current_conn

        except Exception as e:
            # Si algo falla al escribir en BD, revertir y reportar
            try:
                db.rollback()
            except Exception:
                pass
            raise ValueError(f"Error guardando la conexión OAuth en la BD: {e}")


    # -------------------- Consultas --------------------

    def get_user_connection(
        self, user_id: str, service: str, db: Session
    ) -> OAuthConnection:
        """Obtiene la conexión OAuth activa del usuario para un servicio"""
        return (
            db.query(OAuthConnection)
            .filter_by(user_id=user_id, service=service, is_active=True)
            .first()
        )

    def disconnect_service(self, user_id: str, service: str, db: Session) -> dict:
        """
        Desconecta un servicio OAuth.
        """
        oauth_conn = self.get_user_connection(user_id, service, db)
        if not oauth_conn:
            return {"success": False, "revoked": False, "cleaned": False}

        # Cuántos servicios activos hay ahora (antes de cambiar)
        remaining_active = db.query(OAuthConnection).filter_by(
            user_id=user_id,
            is_active=True
        ).count()

        revoked = False
        cleaned = False

        if remaining_active == 1:
            try:
                token_record = db.query(OAuthConnection).filter_by(
                    user_id=user_id
                ).filter(
                    OAuthConnection.access_token.isnot(None)
                ).first()

                if token_record and token_record.access_token:
                    access_token = encryption.decrypt(token_record.access_token)
                    refresh_token = encryption.decrypt(token_record.refresh_token) if token_record.refresh_token else None

                    revoked = self._revoke_google_token(access_token, refresh_token)

                    if revoked:
                        print(f"✅ Token revocado en Google para user {user_id}")
                    else:
                        print(f"⚠️ No se pudo revocar token (puede ya estar revocado)")
                else:
                    revoked = True
                    print(f"ℹ️ No se encontró token para revocar (user {user_id})")

                db.query(OAuthConnection).filter_by(
                    user_id=user_id
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
                    print(f"⚠️ Fallback: servicio {service} marcado como inactivo")
                except Exception as fallback_error:
                    print(f"❌ Error en fallback: {fallback_error}")
        else:
            oauth_conn.is_active = False
            db.commit()
            print(f"✅ Servicio {service} desconectado (quedan {remaining_active - 1} activos)")

        return {
            "success": True,
            "revoked": revoked,
            "cleaned": cleaned,
            "remaining_services": max(0, remaining_active - 1)
        }

    # -------------------- Credenciales --------------------

    def get_service_credentials(
        self, user_id: str, service: str, db: Session
    ) -> Credentials:
        """
        Obtiene credenciales de un servicio Google (refresca si expiran).
        """
        oauth_conn = self.get_user_connection(user_id, service, db)
        if not oauth_conn:
            raise ValueError(f"{service.capitalize()} no conectado. Conecta tu cuenta primero.")

        access_token = encryption.decrypt(oauth_conn.access_token) if oauth_conn.access_token else None
        refresh_token = encryption.decrypt(oauth_conn.refresh_token) if oauth_conn.refresh_token else None

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=oauth_conn.meta_data.get("client_id") if oauth_conn.meta_data else GOOGLE_CLIENT_ID,
            client_secret=oauth_conn.meta_data.get("client_secret") if oauth_conn.meta_data else GOOGLE_CLIENT_SECRET,
            scopes=oauth_conn.scopes,
        )

        # Comprobar expiración de forma segura (token_expires_at puede ser None)
        if oauth_conn.token_expires_at and oauth_conn.token_expires_at < datetime.utcnow():
            try:
                creds.refresh(Request())

                encrypted_access = encryption.encrypt(creds.token) if creds.token else None
                encrypted_refresh = encryption.encrypt(creds.refresh_token) if creds.refresh_token else None

                all_connections = db.query(OAuthConnection).filter_by(
                    user_id=user_id,
                    is_active=True
                ).all()

                for conn in all_connections:
                    conn.access_token = encrypted_access
                    conn.refresh_token = encrypted_refresh
                    conn.token_expires_at = creds.expiry
                    conn.last_used_at = datetime.utcnow()

                db.commit()
            except RefreshError as e:
                print("🔥 RefreshError:", str(e))
                all_connections = db.query(OAuthConnection).filter_by(
                    user_id=user_id,
                    is_active=True
                ).all()

                for conn in all_connections:
                    conn.is_active = False

                db.commit()

                raise ValueError(f"Token de Google inválido. Reconecta tus servicios.")
        else:
            oauth_conn.last_used_at = datetime.utcnow()
            db.commit()

        return creds

    # -------------------- Reconectar Servicios --------------------

    def reconnect_service(self, user_id: str, service: str, db: Session) -> dict:
        """
        Intenta reactivar un servicio si al menos un token válido sigue activo.
        """
        oauth_conn = db.query(OAuthConnection).filter_by(
            user_id=user_id,
            service=service,
            is_active=False
        ).first()

        if not oauth_conn:
            return {"reconnected": False, "needs_oauth": True}

        another_active = db.query(OAuthConnection).filter(
            OAuthConnection.user_id == user_id,
            OAuthConnection.is_active == True,
            OAuthConnection.service != service
        ).first()

        if not another_active:
            return {"reconnected": False, "needs_oauth": True}

        oauth_conn.is_active = True
        db.commit()

        return {
            "reconnected": True,
            "message": f"{service.capitalize()} reactivado automáticamente (token compartido válido)"
        }


# Singleton
oauth_service = OAuthService()