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
import hmac
import hashlib
import os

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/mercadopago")
async def mercadopago_webhook(request: Request):
    """
    Recibe y procesa webhooks de Mercado Pago con validación de firma
    """
    try:
        # Leer payload
        body = await request.body()
        data = await request.json()
        
        # Obtener headers para validación
        x_signature = request.headers.get("x-signature")
        x_request_id = request.headers.get("x-request-id")
        
        print(f"📨 Webhook Mercado Pago recibido")
        print(f"🔒 X-Signature: {x_signature}")
        print(f"🆔 X-Request-ID: {x_request_id}")
        
        # Validar firma del webhook
        if not verify_webhook_signature(body, x_signature, x_request_id):
            print("❌ Firma de webhook inválida")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        
        print("✅ Firma de webhook verificada")
        
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
                # Crear periodo de 30 días
                now = datetime.utcnow()
                next_month = now + timedelta(days=30)
                
                upgrade_to_pro(
                    user_id=uuid.UUID(user_id),
                    payment_customer_reference=payment_info.get("payer_email"),
                    payment_transaction_id=str(payment_info["id"]),
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
    
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error procesando webhook de Mercado Pago: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


def verify_webhook_signature(payload: bytes, x_signature: str, x_request_id: str) -> bool:
    """
    Verifica la firma del webhook de Mercado Pago
    
    Args:
        payload: Cuerpo del webhook (bytes)
        x_signature: Header X-Signature
        x_request_id: Header X-Request-ID
    
    Returns:
        True si la firma es válida, False si no
    """
    from config import MERCADOPAGO_WEBHOOK_KEY_PROD
    webhook_secret = MERCADOPAGO_WEBHOOK_KEY_PROD
    
    if not webhook_secret:
        print("⚠️ MERCADOPAGO_WEBHOOK_SECRET no configurado")
        # En desarrollo puedes permitir webhooks sin validación
        # En producción SIEMPRE debe estar configurado
        return True  # ← Cambiar a False en producción
    
    if not x_signature or not x_request_id:
        print("⚠️ Headers X-Signature o X-Request-ID faltantes")
        return False
    
    try:
        # Extraer ts y v1 del header X-Signature
        # Formato: "ts=1234567890,v1=hash_value"
        parts = {}
        for part in x_signature.split(","):
            key, value = part.split("=")
            parts[key] = value
        
        ts = parts.get("ts")
        v1_hash = parts.get("v1")
        
        if not ts or not v1_hash:
            print("⚠️ X-Signature mal formado")
            return False
        
        # Construir string para validar
        # Formato: id:{request_id};request-id:{request_id};ts:{timestamp};
        manifest = f"id:{x_request_id};request-id:{x_request_id};ts:{ts};"
        
        # Calcular HMAC SHA256
        hmac_obj = hmac.new(
            webhook_secret.encode('utf-8'),
            manifest.encode('utf-8'),
            hashlib.sha256
        )
        
        computed_hash = hmac_obj.hexdigest()
        
        # Comparar hashes
        is_valid = hmac.compare_digest(computed_hash, v1_hash)
        
        if is_valid:
            print(f"✅ Firma válida")
        else:
            print(f"❌ Firma inválida")
            print(f"   Esperado: {v1_hash}")
            print(f"   Calculado: {computed_hash}")
        
        return is_valid
    
    except Exception as e:
        print(f"❌ Error validando firma: {e}")
        return False