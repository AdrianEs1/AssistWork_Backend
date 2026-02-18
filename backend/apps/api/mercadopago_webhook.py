"""
mercadopago_webhook.py
Endpoints para recibir webhooks de Mercado Pago
"""

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy.orm import Session
from apps.database import SessionLocal
from apps.services.payments.mercadopago_service import process_webhook_notification
from apps.services.payments.subscription_service import (
    upgrade_to_pro,
    get_user_subscription
)
from datetime import datetime, timedelta
import uuid

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/mercadopago")
async def mercadopago_webhook(request: Request):
    """
    Recibe y procesa webhooks de Mercado Pago
    """
    try:
        # Leer payload
        data = await request.json()
        
        print(f"📨 Webhook Mercado Pago recibido: {data}")
        
        # Mercado Pago envía diferentes tipos de notificaciones
        notification_type = data.get("type")
        
        print(f"📨 Tipo de notificación: {notification_type}")
        
        # Solo procesar pagos
        if notification_type != "payment":
            print(f"⚠️ Tipo de notificación no manejado: {notification_type}")
            return {"status": "ignored"}
        
        # Procesar notificación de pago
        result = process_webhook_notification(data)
        
        if not result["success"]:
            print(f"❌ Error procesando webhook: {result.get('error')}")
            return {"status": "error", "message": result.get("error")}
        
        payment_info = result["payment_info"]
        
        print(f"💳 Estado del pago: {payment_info['status']}")
        print(f"💳 Método de pago: {payment_info.get('payment_method_id')}")
        print(f"💳 Monto: {payment_info.get('transaction_amount')} {payment_info.get('currency_id')}")
        
        # Solo actualizar si el pago fue aprobado
        if payment_info["status"] == "approved":
            user_id = payment_info.get("external_reference") or payment_info["metadata"].get("user_id")
            
            if not user_id:
                print("⚠️ No user_id en external_reference ni metadata")
                return {"status": "error", "message": "No user_id found"}
            
            print(f"✅ Pago aprobado para usuario: {user_id}")
            
            # Upgrade a Pro
            db = SessionLocal()
            try:
                # Crear periodo de 30 días (Mercado Pago no tiene suscripciones automáticas por defecto)
                now = datetime.utcnow()
                next_month = now + timedelta(days=30)
                
                upgrade_to_pro(
                    user_id=uuid.UUID(user_id),
                    stripe_customer_id=payment_info["payer_email"],  # Email del pagador
                    stripe_subscription_id=str(payment_info["id"]),  # ID del pago
                    current_period_start=now,
                    current_period_end=next_month,
                    db=db
                )
                
                print(f"✅ Usuario {user_id} actualizado a Pro (Mercado Pago)")
                
                db.commit()
                
            except Exception as e:
                print(f"❌ Error actualizando usuario a Pro: {e}")
                import traceback
                traceback.print_exc()
                db.rollback()
                return {"status": "error", "message": str(e)}
            
            finally:
                db.close()
        
        elif payment_info["status"] == "pending":
            print(f"⏳ Pago pendiente (puede ser PSE esperando confirmación)")
        
        elif payment_info["status"] in ["rejected", "cancelled"]:
            print(f"❌ Pago {payment_info['status']}: {payment_info.get('status_detail')}")
        
        return {"status": "success"}
    
    except Exception as e:
        print(f"❌ Error procesando webhook de Mercado Pago: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}
