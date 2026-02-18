"""
subscription_middleware.py
Middleware para verificar límites de suscripción antes de procesar acciones
"""

from sqlalchemy.orm import Session
from apps.services.payments.subscription_service import (
    get_user_subscription,
    get_user_usage,
    check_trial_expired,
    increment_conversation_count,
    increment_file_count
)
from apps.models.subscription import SubscriptionStatus
from datetime import datetime
import uuid


class SubscriptionLimitError(Exception):
    """Excepción cuando se alcanza un límite de suscripción"""
    def __init__(self, message: str, upgrade_required: bool = False):
        self.message = message
        self.upgrade_required = upgrade_required
        super().__init__(self.message)


def check_conversation_limit(user_id: uuid.UUID, db: Session) -> dict:
    """
    Verifica si el usuario puede iniciar una nueva conversación
    
    Args:
        user_id: ID del usuario
        db: Sesión de base de datos
    
    Returns:
        {
            "allowed": bool,
            "message": str,
            "upgrade_required": bool,
            "usage": dict
        }
    
    Raises:
        SubscriptionLimitError si alcanzó el límite
    """
    subscription = get_user_subscription(user_id, db)
    usage = get_user_usage(user_id, db)
    
    if not subscription or not usage:
        raise SubscriptionLimitError("Subscription no encontrada")
    
    # Verificar si el trial expiró
    if check_trial_expired(subscription):
        raise SubscriptionLimitError(
            "❌ Tu periodo de prueba de 7 días ha terminado. Upgrade a Pro para continuar.",
            upgrade_required=True
        )
    
    # Verificar estado de suscripción
    if subscription.status == SubscriptionStatus.PAST_DUE:
        raise SubscriptionLimitError(
            "⚠️ Tu pago está pendiente. Actualiza tu método de pago para continuar.",
            upgrade_required=False
        )
    
    # Si es Pro activo, siempre permitir (ilimitado)
    if subscription.plan == "pro" and subscription.status == SubscriptionStatus.ACTIVE:
        return {
            "allowed": True,
            "message": "✅ Conversaciones ilimitadas (Pro)",
            "upgrade_required": False,
            "usage": {
                "conversations_count": usage.conversations_count,
                "conversations_limit": None,
                "files_count": usage.files_count,
                "files_limit": usage.files_limit
            }
        }
    
    # Verificar límite de conversaciones (Free/Trial)
    if usage.conversations_limit is not None:
        if usage.conversations_count >= usage.conversations_limit:
            raise SubscriptionLimitError(
                f"❌ Alcanzaste el límite de {usage.conversations_limit} conversaciones. "
                f"Upgrade a Pro para conversaciones ilimitadas.",
                upgrade_required=True
            )
    
    # Calcular conversaciones restantes
    remaining = None
    if usage.conversations_limit is not None:
        remaining = usage.conversations_limit - usage.conversations_count
    
    return {
        "allowed": True,
        "message": f"✅ Te quedan {remaining} conversaciones" if remaining else "✅ Permitido",
        "upgrade_required": False,
        "usage": {
            "conversations_count": usage.conversations_count,
            "conversations_limit": usage.conversations_limit,
            "conversations_remaining": remaining,
            "files_count": usage.files_count,
            "files_limit": usage.files_limit
        }
    }


def check_file_upload_limit(user_id: uuid.UUID, files_to_upload: int, db: Session) -> dict:
    """
    Verifica si el usuario puede subir archivos
    
    Args:
        user_id: ID del usuario
        files_to_upload: Cantidad de archivos que quiere subir
        db: Sesión de base de datos
    
    Returns:
        {
            "allowed": bool,
            "message": str,
            "upgrade_required": bool
        }
    
    Raises:
        SubscriptionLimitError si alcanzó el límite
    """
    subscription = get_user_subscription(user_id, db)
    usage = get_user_usage(user_id, db)
    
    if not subscription or not usage:
        raise SubscriptionLimitError("Subscription no encontrada")
    
    # Verificar si el trial expiró
    if check_trial_expired(subscription):
        raise SubscriptionLimitError(
            "❌ Tu periodo de prueba ha terminado. Upgrade a Pro para continuar.",
            upgrade_required=True
        )
    
    # Verificar límite de archivos
    new_total = usage.files_count + files_to_upload
    
    if new_total > usage.files_limit:
        remaining = usage.files_limit - usage.files_count
        raise SubscriptionLimitError(
            f"❌ Límite de archivos alcanzado. "
            f"Puedes subir {remaining} archivo(s) más. "
            f"Upgrade a Pro para 100 archivos.",
            upgrade_required=True
        )
    
    return {
        "allowed": True,
        "message": f"✅ Puedes subir {files_to_upload} archivo(s)",
        "upgrade_required": False,
        "files_remaining": usage.files_limit - new_total
    }


def record_conversation_usage(user_id: uuid.UUID, db: Session) -> bool:
    """
    Registra el uso de una conversación (incrementa contador)
    
    Args:
        user_id: ID del usuario
        db: Sesión de base de datos
    
    Returns:
        True si se registró exitosamente
    """
    success = increment_conversation_count(user_id, db)
    
    if success:
        usage = get_user_usage(user_id, db)
        if usage and usage.conversations_limit:
            remaining = usage.conversations_limit - usage.conversations_count
            print(f"📊 Conversación registrada. Restantes: {remaining}/{usage.conversations_limit}")
        else:
            print(f"📊 Conversación registrada (ilimitado)")
    
    return success


def record_file_usage(user_id: uuid.UUID, files_count: int, db: Session) -> bool:
    """
    Registra el uso de archivos (incrementa contador)
    
    Args:
        user_id: ID del usuario
        files_count: Cantidad de archivos subidos
        db: Sesión de base de datos
    
    Returns:
        True si se registró exitosamente
    """
    for _ in range(files_count):
        success = increment_file_count(user_id, db)
        if not success:
            return False
    
    usage = get_user_usage(user_id, db)
    if usage:
        remaining = usage.files_limit - usage.files_count
        print(f"📊 {files_count} archivo(s) registrado(s). Restantes: {remaining}/{usage.files_limit}")
    
    return True


def get_subscription_summary(user_id: uuid.UUID, db: Session) -> dict:
    """
    Obtiene un resumen del estado de la suscripción
    
    Args:
        user_id: ID del usuario
        db: Sesión de base de datos
    
    Returns:
        Diccionario con información de la suscripción
    """
    subscription = get_user_subscription(user_id, db)
    usage = get_user_usage(user_id, db)
    
    if not subscription or not usage:
        return {
            "plan": "unknown",
            "status": "unknown",
            "usage": {}
        }
    
    # Calcular días restantes de trial
    days_left = None
    trial_active = False
    if subscription.status == SubscriptionStatus.TRIALING and subscription.trial_end:
        delta = subscription.trial_end - datetime.utcnow()
        days_left = max(0, delta.days)
        trial_active = days_left > 0
    
    # Verificar si trial expiró
    trial_expired = check_trial_expired(subscription)
    
    return {
        "plan": subscription.plan.value,
        "status": subscription.status.value,
        "trial_active": trial_active,
        "trial_expired": trial_expired,
        "days_left": days_left,
        "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
        "cancel_at_period_end": subscription.cancel_at_period_end,
        "usage": {
            "conversations_count": usage.conversations_count,
            "conversations_limit": usage.conversations_limit,
            "conversations_remaining": (usage.conversations_limit - usage.conversations_count) if usage.conversations_limit else None,
            "files_count": usage.files_count,
            "files_limit": usage.files_limit,
            "files_remaining": usage.files_limit - usage.files_count
        }
    }