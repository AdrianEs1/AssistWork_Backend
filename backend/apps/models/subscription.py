"""
subscription.py
Modelo para gestionar suscripciones de usuarios
"""

from sqlalchemy import Column, String, Integer, Boolean, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime, timedelta
from apps.database import Base
import enum


class PlanType(str, enum.Enum):
    """Tipos de planes disponibles"""
    FREE = "free"
    PRO = "pro"


class SubscriptionStatus(str, enum.Enum):
    """Estados posibles de una suscripción"""
    TRIALING = "trialing"      # En periodo de prueba
    ACTIVE = "active"          # Activa y pagando
    PAST_DUE = "past_due"      # Pago atrasado
    CANCELED = "canceled"       # Cancelada
    INCOMPLETE = "incomplete"   # Pago inicial incompleto


class Subscription(Base):
    __tablename__ = "subscriptions"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("users.id", ondelete="CASCADE"), 
        unique=True,  # Un usuario = una suscripción
        nullable=False
    )
    
    #MercadoPago
    payment_customer_reference = Column(String, nullable=True)
    payment_transaction_id= Column(String, nullable=True)

    
    # Plan y estado
    plan = Column(SQLEnum(PlanType), default=PlanType.FREE, nullable=False)
    status = Column(SQLEnum(SubscriptionStatus), default=SubscriptionStatus.TRIALING, nullable=False)
    
    # Fechas del trial
    trial_start = Column(DateTime, nullable=True)
    trial_end = Column(DateTime, nullable=True)
    
    # Fechas de facturación
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    
    # Cancelación
    cancel_at_period_end = Column(Boolean, default=False)
    canceled_at = Column(DateTime, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    #user = relationship("User", back_populates="subscription")


class UsageLimits(Base):
    __tablename__ = "usage_limits"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), 
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False
    )
    
    # Contadores de uso
    conversations_count = Column(Integer, default=0, nullable=False)
    conversations_limit = Column(Integer, nullable=True)  # NULL = ilimitado (Pro)
    
    files_count = Column(Integer, default=0, nullable=False)
    files_limit = Column(Integer, default=5, nullable=False)  # 5 (Free) o 100 (Pro)
    
    # Fecha de último reseteo
    reset_at = Column(DateTime, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    #user = relationship("User", back_populates="usage_limits")