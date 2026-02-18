"""
mercadopago_service.py
Servicio para gestionar pagos con Mercado Pago
"""

import mercadopago
import os
from typing import Dict, Optional
from datetime import datetime

# Configuración
ACCESS_TOKEN = os.getenv("MERCADOPAGO_ACCESS_TOKEN")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")

# Inicializar SDK
sdk = mercadopago.SDK(ACCESS_TOKEN)


def create_subscription_preference(user_id: str, email: str, plan: str = "pro") -> Dict:
    """
    Crea una preferencia de pago para suscripción Pro
    
    Args:
        user_id: ID del usuario
        email: Email del usuario
        plan: Plan a suscribir (default: pro)
    
    Returns:
        {
            "preference_id": "xxxxx",
            "init_point": "https://www.mercadopago.com.co/checkout/v1/redirect?pref_id=xxxxx"
        }
    """
    try:
        # Precio en COP (equivalente a $20 USD)
        price_cop = 80000  # Ajusta según tasa de cambio
        
        preference_data = {
            "items": [
                {
                    "title": "AssistWork Pro - Suscripción Mensual",
                    "description": "Conversaciones ilimitadas, 100 archivos PDF, Gmail completo",
                    "quantity": 1,
                    "currency_id": "COP",
                    "unit_price": float(price_cop)
                }
            ],
            "payer": {
                "email": email
            },
            "back_urls": {
                "success": f"{FRONTEND_URL}/pricing?success=true",
                "failure": f"{FRONTEND_URL}/pricing?failure=true",
                "pending": f"{FRONTEND_URL}/pricing?pending=true"
            },
            "auto_return": "approved",
            "notification_url": f"{BACKEND_URL}/api/webhooks/mercadopago",
            "external_reference": user_id,  # Para identificar al usuario
            "metadata": {
                "user_id": user_id,
                "plan": plan
            }
        }
        
        preference_response = sdk.preference().create(preference_data)
        preference = preference_response["response"]
        
        print(f"✅ Preferencia creada: {preference['id']}")
        
        return {
            "success": True,
            "preference_id": preference["id"],
            "init_point": preference["init_point"],  # URL de checkout
            "sandbox_init_point": preference.get("sandbox_init_point")  # Para testing
        }
    
    except Exception as e:
        print(f"❌ Error creando preferencia: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def get_payment_info(payment_id: str) -> Optional[Dict]:
    """
    Obtiene información de un pago
    
    Args:
        payment_id: ID del pago de Mercado Pago
    
    Returns:
        Información del pago o None si hay error
    """
    try:
        payment_info = sdk.payment().get(payment_id)
        
        if payment_info["status"] == 200:
            payment = payment_info["response"]
            
            return {
                "id": payment["id"],
                "status": payment["status"],  # approved, pending, rejected, etc.
                "status_detail": payment["status_detail"],
                "transaction_amount": payment["transaction_amount"],
                "currency_id": payment["currency_id"],
                "payer_email": payment["payer"]["email"],
                "external_reference": payment.get("external_reference"),
                "metadata": payment.get("metadata", {}),
                "date_approved": payment.get("date_approved"),
                "payment_method_id": payment["payment_method_id"],  # visa, pse, etc.
            }
        
        return None
    
    except Exception as e:
        print(f"❌ Error obteniendo pago: {e}")
        return None


def process_webhook_notification(data: Dict) -> Dict:
    """
    Procesa notificación de webhook de Mercado Pago
    
    Args:
        data: Datos del webhook
    
    Returns:
        Información procesada del pago
    """
    try:
        # Mercado Pago envía el payment_id en el webhook
        payment_id = data.get("data", {}).get("id")
        
        if not payment_id:
            return {"success": False, "error": "No payment_id in webhook"}
        
        # Obtener información completa del pago
        payment_info = get_payment_info(payment_id)
        
        if not payment_info:
            return {"success": False, "error": "Could not fetch payment info"}
        
        return {
            "success": True,
            "payment_info": payment_info
        }
    
    except Exception as e:
        print(f"❌ Error procesando webhook: {e}")
        return {
            "success": False,
            "error": str(e)
        }