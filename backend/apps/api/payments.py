"""
payments.py
Endpoints para gestionar pagos y suscripciones con Mercado Pago
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from apps.core.dependencies import get_db, get_current_user
from apps.models.user import User
from apps.services.payments.mercadopago_service import create_subscription_preference
from apps.services.payments.subscription_service import (
    get_user_subscription,
    get_user_usage
)
from datetime import datetime

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("/create-checkout-session")
def create_checkout(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Crea una sesión de checkout de Mercado Pago para suscribirse a Pro
    """
    # Obtener suscripción actual
    subscription = get_user_subscription(current_user.id, db)
    
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription no encontrada")
    
    # Verificar que no esté ya en Pro
    if subscription.plan == "pro" and subscription.status == "active":
        raise HTTPException(
            status_code=400,
            detail="Ya tienes una suscripción Pro activa"
        )
    
    # Crear preferencia de Mercado Pago
    result = create_subscription_preference(
        user_id=str(current_user.id),
        email=current_user.email,
        plan="pro"
    )
    
    if not result["success"]:
        raise HTTPException(
            status_code=500,
            detail=f"Error creando checkout: {result.get('error')}"
        )
    
    return {
        "checkout_url": result["init_point"],
        "preference_id": result["preference_id"]
    }


@router.get("/subscription")
def get_subscription_info(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtiene información de la suscripción del usuario
    """
    subscription = get_user_subscription(current_user.id, db)
    usage = get_user_usage(current_user.id, db)
    
    if not subscription:
        raise HTTPException(status_code=404, detail="Subscription no encontrada")
    
    # Calcular días restantes de trial
    days_left = None
    if subscription.status == "trialing" and subscription.trial_end:
        delta = subscription.trial_end - datetime.utcnow()
        days_left = max(0, delta.days)
    
    return {
        "plan": subscription.plan,
        "status": subscription.status,
        "trial_end": subscription.trial_end.isoformat() if subscription.trial_end else None,
        "days_left": days_left,
        "current_period_end": subscription.current_period_end.isoformat() if subscription.current_period_end else None,
        "cancel_at_period_end": subscription.cancel_at_period_end,
        "usage": {
            "conversations_count": usage.conversations_count if usage else 0,
            "conversations_limit": usage.conversations_limit if usage else None,
            "files_count": usage.files_count if usage else 0,
            "files_limit": usage.files_limit if usage else 5,
        }
    }


@router.get("/subscription/summary")
def get_subscription_summary_endpoint(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Obtiene resumen completo de suscripción y uso
    """
    from apps.middleware.subscription_middleware import get_subscription_summary
    
    return get_subscription_summary(current_user.id, db)