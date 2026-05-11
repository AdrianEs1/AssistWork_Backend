"""
sse_chat.py
SSE endpoint para chat en tiempo real con streaming de eventos.
Reemplaza ws_chat.py — misma lógica, protocolo HTTP/SSE en lugar de WebSocket.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.dependencies import get_user_from_token
from apps.database import SessionLocal
from apps.middleware.subscription_middleware import (
    SubscriptionLimitError,
    check_conversation_limit,
    record_conversation_usage,
)
from apps.models.message import Message
from apps.models.user import User
from apps.services.conversation.conversation_service import conversation_service
from apps.services.memory.qdrant_service import search_context, store_message
from apps.services.orchestrator.orchestrator_service import orchestrator
from apps.services.orchestrator.time_spent_specific import timer
from apps.redis_client import redis

router  = APIRouter()
bearer  = HTTPBearer()

# ── Almacén temporal de requests pendientes ───────────────────────────────────
# Vida útil: desde POST /send hasta GET /stream/{id} (segundos).
# El payload se elimina con pop() al abrir el stream → sin acumulación.
# Con un solo worker esto es suficiente; para multi-worker usar Redis.

# Tiempo máximo (segundos) que un request_id permanece en el dict sin que
# el cliente abra el stream. Pasado este tiempo se descarta automáticamente.



# ── Schemas ───────────────────────────────────────────────────────────────────

class SendMessageRequest(BaseModel):
    message:         str
    session_id:      str
    conversation_id: Optional[str] = None


def get_past_messages_safe(conversation_id, before_dt):
    db = SessionLocal()
    try:
        messages = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation_id,
                Message.created_at < before_dt,
            )
            .order_by(Message.created_at.asc())
            .limit(10)
            .all()
        )
        return [{"role": m.role, "content": m.content} for m in messages]
    finally:
        db.close()

def check_limit_safe(user_id):
    db = SessionLocal()
    try:
        return check_conversation_limit(user_id, db)
    finally:
        db.close()

def init_conversation_safe(user_id, conversation_id, message_content):
    db = SessionLocal()
    try:
        conversation = conversation_service.get_or_create_active_conversation(
            user_id=user_id,
            conversation_id=conversation_id,
            db=db,
        )
        saved_msg = conversation_service.save_user_message(
            conversation_id=conversation.id,
            content=message_content,
            db=db,
        )
        return {
            "id": conversation.id,
            "title": conversation.title,
            "msg_created_at": saved_msg.created_at if hasattr(saved_msg, "created_at") else datetime.now(timezone.utc)
        }
    finally:
        db.close()

def save_assistant_message_safe(conversation_id, content, metadata):
    db = SessionLocal()
    try:
        conversation_service.save_assistant_message(
            conversation_id=conversation_id,
            content=content,
            metadata=metadata,
            db=db,
        )
    finally:
        db.close()

def record_usage_safe(user_id):
    db = SessionLocal()
    try:
        record_conversation_usage(user_id, db)
    finally:
        db.close()

# ── Helpers SSE ───────────────────────────────────────────────────────────────

def _sse_event(event_type: str, data: dict) -> str:
    """Formatea un evento SSE estándar con serialización segura."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


def _sse_comment(text: str = "") -> str:
    """Heartbeat / keep-alive — mantiene la conexión viva en Cloud Run."""
    return f": {text}\n\n"


# ── Background tasks ──────────────────────────────────────────────────────────

async def _update_title_background(conversation_id, first_message: str, user_id):
    """
    Genera y guarda el título de la conversación en segundo plano.
    Usa su propia sesión de DB para no interferir con el flujo principal.
    """
    db = SessionLocal()
    try:
        await conversation_service.update_conversation_title(
            conversation_id=conversation_id,
            first_message=first_message,
            user_id=user_id,
            db=db,
        )
    except Exception as e:
        print(f"⚠️ Error actualizando título (background): {e}")
    finally:
        db.close()


async def _index_messages_background(
    user_message: str,
    result_text: str,
    conversation_id: str,
    user_id: str,
):
    """
    Indexa los mensajes del turno en Qdrant en segundo plano.
    El evento 'completed' llega al frontend sin esperar las escrituras vectoriales.
    """
    try:
        store_message(user_message, metadata={
            "role": "user",
            "conversation_id": conversation_id,
            "user_id": user_id,
        })
        store_message(result_text, metadata={
            "role": "assistant",
            "conversation_id": conversation_id,
            "user_id": user_id,
        })
    except Exception as e:
        print(f"⚠️ Error indexando mensajes en Qdrant (background): {e}")


# ── Helpers de autenticación ──────────────────────────────────────────────────

async def _authenticate(credentials: HTTPAuthorizationCredentials) -> User:
    """
    Autentica al usuario a partir del Bearer token del header Authorization.
    Abre y cierra su propia sesión de DB (el scope no se comparte con el
    generador SSE).
    """
    db = SessionLocal()
    try:
        return await get_user_from_token(credentials.credentials, db)
    finally:
        db.close()


# ── Endpoint 1: POST /agent/send ──────────────────────────────────────────────

@router.post("/agent/send", status_code=status.HTTP_202_ACCEPTED)
async def send_message(
    body:        SendMessageRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
):
    """
    Recibe el mensaje del usuario de forma segura (body + header Auth) y
    devuelve un request_id para abrir el stream SSE.

    El token viaja en el header Authorization: Bearer <token>
    El mensaje viaja en el body JSON — nunca en la URL.

    Response: { "request_id": "<uuid>" }
    """
   

    # Autenticar
    try:
        current_user = await _authenticate(credentials)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Autenticación fallida: {str(e)}",
        )

    # Generar ID único para este request
    request_id = str(uuid.uuid4())

    payload = {
        "message": body.message,
        "session_id": body.session_id,
        "conversation_id": body.conversation_id,
        "user_id": str(current_user.id),
        "created_at": datetime.now(timezone.utc).timestamp(),
    }

    try:
        await redis.setex(
            f"req:{request_id}",
            30,  # TTL
            json.dumps(payload)
        )
    except Exception as e:
        print(f"❌ Redis error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Error temporal, intenta de nuevo"
        )

    return {"request_id": request_id}

    """print(f"📨 Mensaje encolado | request_id={request_id} | user={current_user.id}")
    return {"request_id": request_id}"""


# ── Endpoint 2: GET /agent/stream/{request_id} ────────────────────────────────

@router.get("/agent/stream/{request_id}")
async def sse_stream(request_id: str, request: Request):
    """
    Abre el stream SSE para un request_id previamente registrado via POST /send.
    La URL no contiene token ni mensaje — solo el ID de la operación.

    Eventos emitidos:
        analyzing   → clasificando intent
        loading     → cargando herramientas
        connecting  → iniciando sesión ADK
        thinking    → agente procesando
        planning    → planificando pasos
        executing   → ejecutando tool
        processing  → procesando resultado de tool
        saving      → guardando resultados
        warning     → advertencia no fatal
        completed   → operación completada (cierra stream)
        error       → error en algún paso (cierra stream)
    """

    raw = await redis.get(f"req:{request_id}")

    if raw is None:
        async def _not_found():
            yield _sse_event("error", {
                "message": "Request no encontrado o expirado.",
                "error_type": "RequestNotFound",
            })
        return StreamingResponse(_not_found(), media_type="text/event-stream")

    payload = json.loads(raw)

    # eliminar después de leer (importante)
    await redis.delete(f"req:{request_id}")

    # Extraer datos del payload
    message         = payload["message"]
    session_id      = payload["session_id"]
    conversation_id = payload["conversation_id"]
    
    user_id = payload["user_id"]

    db = SessionLocal()
    try:
        current_user = db.query(User).get(user_id)
    finally:
        db.close()

    # ── Generador principal ───────────────────────────────────────────────────
    async def event_generator():

        # Cola interna: event_callback encola, el generador desencola y emite
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        async def event_callback(event_type: str, event_data: dict):
            try:
                queue.put_nowait((event_type, event_data))
            except asyncio.QueueFull:
                pass

            if isinstance(event_data, dict):
                # Filtrar objetos no serializables que el orquestador pueda colar
                for key in ("mcp_clients", "client", "mcp_client"):
                    event_data.pop(key, None)
            await queue.put((event_type, event_data))

        async def drain_queue():
            while not queue.empty():
                evt_type, evt_data = await queue.get()
                yield _sse_event(evt_type, {
                    "session_id": session_id,
                    "timestamp":  datetime.now(timezone.utc).isoformat(),
                    **evt_data,
                })

        # Keep-alive inicial (Cloud Run necesita datos rápido para no cerrar)
        yield _sse_comment("connected")

        # Feedback inmediato al usuario
        yield _sse_event("validating", {
            "session_id": session_id,
            "message": "Validando sesión...",
        })

        try:
            # ── Ejecución Paralela: Límites e Inicialización ──
            limit_task = asyncio.create_task(
                asyncio.to_thread(check_limit_safe, current_user.id)
            )
            conv_task = asyncio.create_task(
                asyncio.to_thread(init_conversation_safe, current_user.id, conversation_id, message)
            )

            # ── Contexto e Historial Paralelo ──
            if conversation_id:
                context_task = asyncio.create_task(
                    asyncio.to_thread(
                        search_context,
                        query=message,
                        user_id=str(current_user.id),
                        conversation_id=str(conversation_id),
                        limit=10,
                        score_threshold=0.5,
                    )
                )
                history_task = asyncio.create_task(
                    asyncio.to_thread(
                        get_past_messages_safe,
                        conversation_id,
                        datetime.now(timezone.utc),
                    )
                )
                
                limit_check, conv_data, context_list, conversation_history = await asyncio.gather(
                    limit_task, conv_task, context_task, history_task
                )
            else:
                # Conversación nueva: No hay historial ni contexto.
                limit_check, conv_data = await asyncio.gather(limit_task, conv_task)
                context_list = []
                conversation_history = []

            # ── Límites de suscripción (Warning) ──
            remaining = limit_check.get("conversations_remaining")
            if remaining is not None and remaining <= 3:
                yield _sse_event("warning", {
                    "session_id":  session_id,
                    "message":     f"⚠️ Te quedan {remaining} conversaciones. Considera hacer upgrade.",
                    "upgrade_url": "/pricing",
                })

            actual_conversation_id = conv_data["id"]
            conversation_title = conv_data["title"]

            # ── Título: calcular en paralelo con el orquestador ──
            title_task = None
            if conversation_title == "Nueva conversacion":
                title_task = asyncio.create_task(
                    _update_title_background(
                        conversation_id=actual_conversation_id,
                        first_message=message,
                        user_id=current_user.id,
                    )
                )

            context_text = "\n".join(context_list) if context_list else ""
            print(f"🔍 Contexto recuperado: {len(context_list)} mensajes")

            # ── Orquestador en background + streaming de eventos ──────────
            orchestrator_task = asyncio.create_task(
                orchestrator(
                    user_input=message,
                    user_id=str(current_user.id),
                    context=context_text,
                    event_callback=event_callback,
                    conversation_history=conversation_history,
                )
            )

            # Emitir eventos mientras el orquestador trabaja
            while not orchestrator_task.done():
                if await request.is_disconnected():
                    orchestrator_task.cancel()
                    print(f"⚠️ Cliente desconectó: user={current_user.id} session={session_id}")
                    return

                async for chunk in drain_queue():
                    yield chunk

                yield _sse_comment("heartbeat")
                await asyncio.sleep(0.1)

            # Vaciar cola final tras completar
            async for chunk in drain_queue():
                yield chunk

            result = await orchestrator_task
            print(f"📊 Resultado orquestador: {result}")

            # ── Extraer respuesta ─────────────────────────────────────────
            result_text     = (
                result if isinstance(result, str)
                else result.get("message", str(result))
            )
            result_metadata = (
                result.get("data", {}) if isinstance(result, dict) else {}
            )

            # ── Guardar respuesta del agente ──────────────────────────────
            await asyncio.gather(
                asyncio.to_thread(
                    save_assistant_message_safe,
                    actual_conversation_id,
                    result_text,
                    result_metadata,
                ),
                asyncio.to_thread(
                    record_usage_safe,
                    current_user.id,
                )
            )

            # ── Indexar en Qdrant en background ───────────────────────────
            asyncio.create_task(
                _index_messages_background(
                    user_message=message,
                    result_text=result_text,
                    conversation_id=str(actual_conversation_id),
                    user_id=str(current_user.id),
                )
            )
            # ── Esperar título si se estaba generando ──
            if title_task is not None:
                await title_task
                db = SessionLocal()
                try:
                    from apps.models.conversation import Conversation
                    conv = db.query(Conversation).get(actual_conversation_id)
                    conversation_title = conv.title if conv else conversation_title
                finally:
                    db.close()

            # ── Evento final ──────────────────────────────────────────────
            yield _sse_event("completed", {
                "session_id": session_id,
                "message":    result_text,
                "data": {
                    "conversation_id": str(actual_conversation_id),
                    "title":           conversation_title,
                    **result_metadata,
                },
            })

        except SubscriptionLimitError as e:
            yield _sse_event("completed", {
                "session_id":       session_id,
                "message":          e.message,
                "upgrade_required": e.upgrade_required,
                "upgrade_url":      "/pricing" if e.upgrade_required else None,
            })

        except Exception as e:
            print(f"❌ Error en stream SSE: {e}")
            yield _sse_event("error", {
                "session_id": session_id,
                "message":    f"Error procesando tu mensaje: {str(e)}",
                "error_type": type(e).__name__,
            })

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":       "no-cache",
            "X-Accel-Buffering":   "no",
            "Connection":          "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )