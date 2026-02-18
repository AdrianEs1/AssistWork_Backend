"""
subscription_service.py
Lógica de negocio para gestionar suscripciones
"""

from sqlalchemy.orm import Session
from apps.models.subscription import Subscription, UsageLimits, PlanType, SubscriptionStatus
from apps.models.user import User
from datetime import datetime, timedelta
from typing import Optional
import uuid


def create_trial_subscription(user_id: uuid.UUID, db: Session) -> Subscription:
    """
    Crea una suscripción trial de 7 días para un nuevo usuario
    
    Args:
        user_id: ID del usuario
        db: Sesión de base de datos
    
    Returns:
        Subscription creada
    """
    now = datetime.utcnow()
    trial_end = now + timedelta(days=7)
    
    # Crear suscripción
    subscription = Subscription(
        user_id=user_id,
        plan=PlanType.FREE,
        status=SubscriptionStatus.TRIALING,
        trial_start=now,
        trial_end=trial_end
    )
    db.add(subscription)
    
    # Crear límites de uso para trial
    usage_limits = UsageLimits(
        user_id=user_id,
        conversations_count=0,
        conversations_limit=20,  # 20 conversaciones en trial
        files_count=0,
        files_limit=5  # 5 archivos en trial
    )
    db.add(usage_limits)
    
    db.commit()
    db.refresh(subscription)
    
    print(f"✅ Trial creado para user {user_id}: {trial_end}")
    
    return subscription


def get_user_subscription(user_id: uuid.UUID, db: Session) -> Optional[Subscription]:
    """
    Obtiene la suscripción de un usuario
    
    Args:
        user_id: ID del usuario
        db: Sesión de base de datos
    
    Returns:
        Subscription o None
    """
    return db.query(Subscription).filter(Subscription.user_id == user_id).first()


def get_user_usage(user_id: uuid.UUID, db: Session) -> Optional[UsageLimits]:
    """
    Obtiene los límites de uso de un usuario
    
    Args:
        user_id: ID del usuario
        db: Sesión de base de datos
    
    Returns:
        UsageLimits o None
    """
    return db.query(UsageLimits).filter(UsageLimits.user_id == user_id).first()


def upgrade_to_pro(
    user_id: uuid.UUID,
    payment_customer_reference: str,
    payment_transaction_id: str,
    current_period_start: datetime,
    current_period_end: datetime,
    db: Session
) -> Subscription:
    """
    Actualiza una suscripción a Pro
    
    Args:
        user_id: ID del usuario
        stripe_customer_id: ID del cliente (email en Mercado Pago)
        stripe_subscription_id: ID de la suscripción/pago
        current_period_start: Inicio del periodo actual
        current_period_end: Fin del periodo actual
        db: Sesión de base de datos
    
    Returns:
        Subscription actualizada
    """
    subscription = get_user_subscription(user_id, db)
    
    if not subscription:
        raise ValueError(f"Subscription no encontrada para user {user_id}")
    
    # Actualizar suscripción
    subscription.plan = PlanType.PRO
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.payment_customer_reference = payment_customer_reference
    subscription.payment_transaction_id = payment_transaction_id
    subscription.current_period_start = current_period_start
    subscription.current_period_end = current_period_end
    subscription.trial_end = None  # Ya no está en trial
    
    # Actualizar límites de uso para Pro
    usage_limits = get_user_usage(user_id, db)
    if usage_limits:
        usage_limits.conversations_limit = None  # Ilimitado
        usage_limits.files_limit = 100
    
    db.commit()
    db.refresh(subscription)
    
    print(f"✅ Usuario {user_id} actualizado a Pro")
    
    return subscription


def downgrade_to_free(user_id: uuid.UUID, db: Session) -> Subscription:
    """
    Degrada una suscripción a Free
    
    Args:
        user_id: ID del usuario
        db: Sesión de base de datos
    
    Returns:
        Subscription actualizada
    """
    subscription = get_user_subscription(user_id, db)
    
    if not subscription:
        raise ValueError(f"Subscription no encontrada para user {user_id}")
    
    # Actualizar suscripción
    subscription.plan = PlanType.FREE
    subscription.status = SubscriptionStatus.CANCELED
    subscription.canceled_at = datetime.utcnow()
    
    # Actualizar límites de uso a Free
    usage_limits = get_user_usage(user_id, db)
    if usage_limits:
        usage_limits.conversations_limit = 20
        usage_limits.files_limit = 5
    
    db.commit()
    db.refresh(subscription)
    
    print(f"✅ Usuario {user_id} degradado a Free")
    
    return subscription


def check_trial_expired(subscription: Subscription) -> bool:
    """
    Verifica si el trial ha expirado
    
    Args:
        subscription: Subscription a verificar
    
    Returns:
        True si expiró, False si no
    """
    if subscription.status != SubscriptionStatus.TRIALING:
        return False
    
    if not subscription.trial_end:
        return False
    
    return datetime.utcnow() > subscription.trial_end


def increment_conversation_count(user_id: uuid.UUID, db: Session) -> bool:
    """
    Incrementa el contador de conversaciones
    
    Args:
        user_id: ID del usuario
        db: Sesión de base de datos
    
    Returns:
        True si se incrementó, False si alcanzó el límite
    """
    usage = get_user_usage(user_id, db)
    
    if not usage:
        return False
    
    # Si es ilimitado (Pro), siempre permitir
    if usage.conversations_limit is None:
        usage.conversations_count += 1
        db.commit()
        return True
    
    # Si no alcanzó el límite, incrementar
    if usage.conversations_count < usage.conversations_limit:
        usage.conversations_count += 1
        db.commit()
        return True
    
    # Alcanzó el límite
    return False


def increment_file_count(user_id: uuid.UUID, db: Session) -> bool:
    """
    Incrementa el contador de archivos
    
    Args:
        user_id: ID del usuario
        db: Sesión de base de datos
    
    Returns:
        True si se incrementó, False si alcanzó el límite
    """
    usage = get_user_usage(user_id, db)
    
    if not usage:
        return False
    
    # Verificar límite
    if usage.files_count < usage.files_limit:
        usage.files_count += 1
        db.commit()
        return True
    
    # Alcanzó el límite
    return False