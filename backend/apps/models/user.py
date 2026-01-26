from sqlalchemy import Column, String, Boolean, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime
import uuid
from passlib.context import CryptContext
from apps.database import Base

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255))
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    reset_password_token = Column(String, nullable=True, index=True)
    reset_password_expires = Column(DateTime, nullable=True)
    delete_account_token = Column(String, nullable=True)
    delete_account_expires = Column(DateTime, nullable=True)
    last_verification_sent_at = Column(DateTime, nullable=True)
    verification_attempts = Column(Integer, default=0)



    def set_password(self, password: str):
        """Hashea y guarda la contraseña"""
        self.password_hash = pwd_context.hash(password)
    
    def verify_password(self, password: str) -> bool:
        """Verifica si la contraseña es correcta"""
        return pwd_context.verify(password, self.password_hash)
    
    @classmethod
    def create_user(cls, email: str, password: str, name: str = None):
        """Factory method para crear usuario con password hasheado"""
        user = cls(email=email, name=name)
        user.set_password(password)
        return user