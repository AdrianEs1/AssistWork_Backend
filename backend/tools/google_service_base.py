from datetime import datetime
from typing import Optional, Dict, Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

from sqlalchemy.orm import Session
from apps.database import SessionLocal
from apps.models.oauth_connection import OAuthConnection
from abc import ABC, abstractmethod


class GoogleServiceBase(ABC):
    """
    Clase base genérica para manejar la conexión con cualquier servicio de Google
    (Gmail, Drive, Calendar, etc.) usando OAuth2.
    
    Características:
    - Manejo automático de refresh de tokens
    - Validación de credenciales OAuth
    - Manejo robusto de errores
    - Thread-safe con locks en DB
    """

    DEFAULT_API_VERSION = "v1"

    def __init__(self, service_name: str, api_version: Optional[str] = None):
        self.service_name = service_name.lower()
        self.api_version = api_version or self.DEFAULT_API_VERSION

    # -------------------------------------------------------------------------
    # MÉTODOS PRINCIPALES
    # -------------------------------------------------------------------------
    def get_service(self, user_id: str):
        """
        Obtiene un cliente autenticado para el servicio de Google.
        Se encarga de recuperar credenciales, refrescar tokens y construir el cliente.
        
        Args:
            user_id: ID del usuario o service_user_id
            
        Returns:
            Resource: Cliente del servicio de Google autenticado
            
        Raises:
            ValueError: Si no existe conexión o las credenciales son inválidas
            RefreshError: Si falla el refresh del token  
        """
        db = SessionLocal()
        try:
            oauth_conn = self._get_active_connection(db, user_id)
            creds = self._build_credentials(oauth_conn)

            # Refrescar token si expiró
            if self._is_token_expired(oauth_conn):
                creds = self._refresh_credentials(db, oauth_conn, creds)

            # Actualizar última vez usado
            oauth_conn.last_used_at = datetime.utcnow()
            db.commit()

            # Construir y devolver el cliente del servicio
            return build(self.service_name, self.api_version, credentials=creds)

        finally:
            db.close()

    def test_connection(self, user_id: str) -> Dict[str, Any]:
        """
        Verifica la conexión con el servicio de Google.
        Intenta refrescar el token automáticamente si es necesario.
        
        Args:
            user_id: ID del usuario
            
        Returns:
            dict con:
                - success (bool): Si la conexión fue exitosa
                - service (str): Nombre del servicio
                - ping_data (dict): Datos del usuario/servicio
                - message (str): Mensaje descriptivo
                - error (str, opcional): Tipo de error si falló
        """
        try:
            print(f"🚀 Probando conexión con servicio: {self.service_name}")
            service = self.get_service(user_id)
            print(f"🔗 Cliente {self.service_name} construido correctamente: {service}")

            # Realizar ping al servicio y obtener datos
            ping_data = self._ping_service(service)
            print(f"✅ _ping_service ejecutado sin errores para {self.service_name}")

            return {
                "success": True,
                "service": self.service_name,
                "ping_data": ping_data,
                "message": f"✅ Conexión exitosa con {self.service_name.title()} API"
            }

        except ValueError as e:
            # Errores de validación (no existe conexión, falta configuración, etc.)
            error_msg = str(e)
            print(f"❌ Error de validación en {self.service_name}: {error_msg}")
            
            if "No se encontró conexión activa" in error_msg:
                return {
                    "success": False,
                    "error": "no_connection",
                    "message": f"No se encontró conexión activa para {self.service_name}. El usuario debe autorizar el acceso primero."
                }
            elif "Faltan credenciales OAuth" in error_msg:
                return {
                    "success": False,
                    "error": "missing_credentials",
                    "message": f"Configuración OAuth incompleta para {self.service_name}. Contacta a soporte."
                }
            elif "Token de" in error_msg and "inválido o revocado" in error_msg:
                return {
                    "success": False,
                    "error": "token_revoked",
                    "message": f"Token de {self.service_name.title()} revocado. Reconecta tu cuenta desde el menú de Apps."
                }
            else:
                return {
                    "success": False,
                    "error": "validation_error",
                    "message": f"❌ Error de validación: {error_msg}"
                }
        
        except RefreshError as e:
            # Error al refrescar el token
            print(f"❌ Error refrescando token para {self.service_name}: {e}")
            return {
                "success": False,
                "error": "refresh_failed",
                "message": f"No se pudo refrescar el token de {self.service_name.title()}. Reconecta tu cuenta desde el menú de Apps."
            }
        
        except Exception as e:
            # Errores inesperados
            print(f"❌ Error inesperado en test_connection({self.service_name}): {e}")
            import traceback
            traceback.print_exc()
            
            return {
                "success": False,
                "error": "unexpected_error",
                "message": f"❌ Error inesperado con {self.service_name.title()}: {str(e)}"
            }

    # -------------------------------------------------------------------------
    # MÉTODOS AUXILIARES PRIVADOS
    # -------------------------------------------------------------------------
    def _get_active_connection(self, db: Session, user_id: str) -> OAuthConnection:
        """
        Recupera la conexión activa de OAuth para el usuario y servicio.
        Usa lock pesimista (FOR UPDATE) para evitar race conditions.
        
        Args:
            db: Sesión de SQLAlchemy
            user_id: ID del usuario o service_user_id
            
        Returns:
            OAuthConnection: Conexión activa encontrada
            
        Raises:
            ValueError: Si no existe conexión activa
        """
        oauth_conn = (
            db.query(OAuthConnection)
            .filter_by(user_id=user_id, service=self.service_name, is_active=True)
            .with_for_update()  # 🔒 Lock pesimista para evitar race conditions
            .first()
        )

        if not oauth_conn:
            # Intentar por service_user_id (sub de Google)
            oauth_conn = (
                db.query(OAuthConnection)
                .filter_by(service_user_id=user_id, service=self.service_name, is_active=True)
                .with_for_update()
                .first()
            )

        if not oauth_conn:
            raise ValueError(
                f"No se encontró conexión activa para {self.service_name}. "
                f"El usuario debe autorizar el acceso primero."
            )

        return oauth_conn

    def _build_credentials(self, oauth_conn: OAuthConnection) -> Credentials:
        """
        Crea el objeto Credentials a partir de los tokens guardados en BD.
        Lee client_id y client_secret de variables de entorno por seguridad.
        
        Args:
            oauth_conn: Conexión OAuth de la BD
            
        Returns:
            Credentials: Objeto de credenciales de Google
            
        Raises:
            ValueError: Si faltan las variables de entorno GOOGLE_CLIENT_ID o GOOGLE_CLIENT_SECRET
        """
        from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
        
        # Validar que existan las variables de entorno
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            raise ValueError(
                f"Faltan credenciales OAuth para {self.service_name}. "
                f"Verifica que GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET estén configurados en las variables de entorno (.env)"
            )
        
        # Validar que exista refresh_token
        refresh_token = oauth_conn.get_refresh_token()
        if not refresh_token:
            raise ValueError(
                f"No hay refresh_token disponible para {self.service_name}. "
                f"El usuario debe reconectar su cuenta."
            )
        
        print(f"🔑 Construyendo credenciales para {self.service_name} usando variables de entorno")
        
        return Credentials(
            token=oauth_conn.get_access_token(),
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            scopes=oauth_conn.scopes,
        )

    def _is_token_expired(self, oauth_conn: OAuthConnection) -> bool:
        """
        Verifica si el token de acceso ha expirado.
        Si no hay fecha de expiración, asume que está expirado por seguridad.
        
        Args:
            oauth_conn: Conexión OAuth de la BD
            
        Returns:
            bool: True si el token expiró o no tiene fecha de expiración
        """
        if not oauth_conn.token_expires_at:
            print(f"⚠️ Token sin fecha de expiración para {self.service_name}, asumiendo expirado")
            return True  # Si no hay fecha, asumir expirado por seguridad
        
        is_expired = oauth_conn.token_expires_at < datetime.utcnow()
        if is_expired:
            print(f"⏰ Token expirado para {self.service_name} (expiró: {oauth_conn.token_expires_at})")
        
        return is_expired

    def _refresh_credentials(
        self, db: Session, oauth_conn: OAuthConnection, creds: Credentials
    ) -> Credentials:
        """
        Refresca las credenciales de acceso cuando el token expira.
        Actualiza los nuevos tokens en la base de datos.
        
        Args:
            db: Sesión de SQLAlchemy
            oauth_conn: Conexión OAuth de la BD
            creds: Credenciales actuales
            
        Returns:
            Credentials: Credenciales refrescadas
            
        Raises:
            ValueError: Si el token es inválido o fue revocado
        """
        try:
            print(f"🔄 Refrescando token para servicio {self.service_name}...")
            creds.refresh(Request())

            # Actualizar tokens en BD
            oauth_conn.set_tokens(creds.token, creds.refresh_token)
            oauth_conn.token_expires_at = creds.expiry
            oauth_conn.last_used_at = datetime.utcnow()
            db.commit()
            
            print(f"✅ Token refrescado exitosamente para {self.service_name}")
            print(f"   📅 Nueva expiración: {creds.expiry}")
            
            return creds

        except RefreshError as e:
            # Token revocado o inválido - marcar conexión como inactiva
            print(f"❌ RefreshError para {self.service_name}: {e}")
            oauth_conn.is_active = False
            db.commit()
            
            raise ValueError(
                f"Token de {self.service_name.title()} inválido o revocado. "
                f"Reconecta tu cuenta. Detalle: {str(e)}"
            )
        except Exception as e:
            # Cualquier otro error durante el refresh
            print(f"❌ Error inesperado refrescando token para {self.service_name}: {e}")
            import traceback
            traceback.print_exc()
            
            raise ValueError(
                f"Error refrescando token de {self.service_name.title()}: {str(e)}"
            )

    @abstractmethod
    def _ping_service(self, service) -> Dict[str, Any]:
        """
        Método abstracto que debe implementar cada servicio de Google.
        Realiza una llamada mínima a la API para verificar autenticación.
        
        Args:
            service: Cliente del servicio de Google
            
        Returns:
            dict: Datos del usuario/servicio (email, nombre, etc.)
            
        Ejemplos:
            - Gmail: obtener perfil del usuario
            - Drive: obtener información 'about' del usuario
            - Calendar: listar calendarios
        """
        pass