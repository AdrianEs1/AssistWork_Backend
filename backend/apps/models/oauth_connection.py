from sqlalchemy import Column, String, Boolean, DateTime, Text, ARRAY, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import validates
from datetime import datetime
import uuid
from apps.database import Base
from apps.core.encryption import encryption

class OAuthConnection(Base):
    __tablename__ = "oauth_connections"
   
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    service = Column(String(50), nullable=False)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text, nullable=False)
    token_expires_at = Column(DateTime, nullable=False)
    scopes = Column(ARRAY(Text))
    service_user_id = Column(String(255))
    meta_data = Column(JSONB)
    is_active = Column(Boolean, default=True)
    connected_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
   
    @validates('access_token')
    def encrypt_access_token(self, key, value):
        """Auto-encripta el access_token si no está encriptado"""
        if value and not self._is_encrypted(value):
            return encryption.encrypt(value)
        return value
    
    @validates('refresh_token')
    def encrypt_refresh_token(self, key, value):
        """Auto-encripta el refresh_token si no está encriptado"""
        if value and not self._is_encrypted(value):
            return encryption.encrypt(value)
        return value
    
    """def _is_encrypted(self, value: str) -> bool:
        Verifica si un token ya está encriptado (Fernet empieza con 'gAAAAA')
        return value.startswith('gAAAAA')"""
    
    def _is_encrypted(self, value: str) -> bool:
        try:
            encryption.decrypt(value)
            return True
        except Exception:
            return False


    
    def get_access_token(self) -> str:
        """Desencripta y retorna el access token"""
        return encryption.decrypt(self.access_token)
   
    def get_refresh_token(self) -> str:
        """Desencripta y retorna el refresh token"""
        return encryption.decrypt(self.refresh_token)
    
    def set_tokens(self, access_token: str, refresh_token: str | None = None):
        """Actualiza los tokens de acceso y refresco."""
        if access_token:
            self.access_token = access_token  # Se encripta automáticamente al asignar
        if refresh_token:
            self.refresh_token = refresh_token

    def is_token_expired(self) -> bool:
        return datetime.utcnow() >= self.token_expires_at

