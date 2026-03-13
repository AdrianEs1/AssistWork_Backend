"""
sse_chat.py
SSE endpoint para chat en tiempo real con streaming de eventos.
Reemplaza ws_chat.py — misma lógica, protocolo HTTP/SSE en lugar de WebSocket.
"""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
import json
import asyncio
from datetime import datetime

from apps.database import SessionLocal
from apps.api.dependencies import get_user_from_token
from apps.models.user import User
from apps.services.orchestrator.orchestrator_service import orchestrator
from apps.services.conversation.conversation_service import conversation_service
from apps.services.memory.qdrant_service import store_message, search_context
from apps.middleware.subscription_middleware import (
    check_conversation_limit,
    record_conversation_usage,
    SubscriptionLimitError
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers SSE
# ---------------------------------------------------------------------------

def _sse_format(event_type: str, data: dict) -> str:
    """Formatea un evento SSE estándar con serialización segura."""
    
    # default=str convierte cualquier objeto raro (como MCPClientManager) 
    # a su representación en string en lugar de lanzar error.
    payload = json.dumps(data, ensure_ascii=False, default=str) 
    
    return f"event: {event_type}\ndata: {payload}\n\n"


def _sse_comment(text: str = "") -> str:
    """Heartbeat / keep-alive comment — mantiene la conexión viva en Cloud Run."""
    return f": {text}\n\n"


# ---------------------------------------------------------------------------
# Endpoint principal
# ---------------------------------------------------------------------------

@router.get("/agent/stream")
async def sse_stream(
    request: Request,
    token: str = Query(..., description="JWT access token"),
    message: str = Query(..., description="Mensaje del usuario"),
    conversation_id: Optional[str] = Query(None, description="ID conversación existente"),
    session_id: str = Query(..., description="UUID único por pestaña del frontend"),
):
    """
    SSE endpoint — el cliente abre una conexión GET y recibe eventos hasta
    que el agente termina o ocurre un error.

    Eventos emitidos:
        analyzing   → Analizando petición
        planning    → Planificando secuencia
        executing   → Ejecutando paso X/Y
        processing  → Procesando con LLM
        saving      → Guardando resultados
        completed   → Operación completada (cierra stream)
        error       → Error en algún paso (cierra stream)

    Query params:
        token           JWT del usuario
        message         Instrucción en lenguaje natural
        conversation_id UUID conversación (opcional)
        session_id      UUID por pestaña — permite múltiples tabs
    """

    # ── 1. Autenticación ──────────────────────────────────────────────────
    db = SessionLocal()
    try:
        current_user: User = await get_user_from_token(token, db)
    except Exception as e:
        db.close()

        async def auth_error():
            yield _sse_format("error", {
                "message": f"Autenticación fallida: {str(e)}",
                "error_type": "AuthError",
                "session_id": session_id,
            })

        return StreamingResponse(auth_error(), media_type="text/event-stream")
    finally:
        db.close()

    # ── 2. Generador principal ────────────────────────────────────────────
    async def event_generator():

        # Cola interna: el event_callback encola eventos,
        # el generador los saca y los formatea como SSE.
        queue: asyncio.Queue = asyncio.Queue()

        async def event_callback(event_type: str, event_data: dict):
            """Callback que recibe el orquestador y encola eventos SSE."""
            # Eliminamos objetos pesados o no serializables si se colaron
            if isinstance(event_data, dict):
                event_data.pop("mcp_clients", None)
                event_data.pop("client", None)
                event_data.pop("mcp_client", None)
                
            await queue.put((event_type, event_data))

        async def drain_queue():
            """Vacía la cola y emite todos los eventos pendientes."""
            while not queue.empty():
                evt_type, evt_data = await queue.get()
                yield _sse_format(evt_type, {
                    "session_id": session_id,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    **evt_data,
                })

        # ── Keep-alive inicial (Cloud Run necesita datos rápido) ──────────
        yield _sse_comment("connected")

        # ── 3. Verificar límites de suscripción ───────────────────────────
        db = SessionLocal()
        try:
            limit_check = check_conversation_limit(current_user.id, db)

            if limit_check.get("conversations_remaining") and \
               limit_check["conversations_remaining"] <= 3:
                yield _sse_format("warning", {
                    "session_id": session_id,
                    "message": (
                        f"⚠️ Te quedan {limit_check['conversations_remaining']} "
                        f"conversaciones. Considera hacer upgrade."
                    ),
                    "upgrade_url": "/pricing",
                })

        except SubscriptionLimitError as e:
            yield _sse_format("completed", {
                "session_id": session_id,
                "message": e.message,
                "upgrade_required": e.upgrade_required,
                "upgrade_url": "/pricing" if e.upgrade_required else None,
            })
            db.close()
            return
        finally:
            db.close()

        # ── 4. Procesar mensaje ───────────────────────────────────────────
        db = SessionLocal()
        try:
            # 4.1 Conversación
            conversation = conversation_service.get_or_create_active_conversation(
                user_id=current_user.id,
                conversation_id=conversation_id,
                db=db,
            )

            # 4.2 Guardar mensaje usuario
            conversation_service.save_user_message(
                conversation_id=conversation.id,
                content=message,
                db=db,
            )

            # 4.3 Actualizar título si es nueva
            if conversation.title == "Nueva conversacion":
                title = await conversation_service.update_conversation_title(
                    conversation_id=conversation.id,
                    first_message=message,
                    user_id=current_user.id,
                    db=db,
                )
                if title:
                    conversation.title = title

            # 4.4 Contexto semántico
            context_list = search_context(
                query=message,
                user_id=str(current_user.id),
                conversation_id=str(conversation.id),
                limit=10,
                score_threshold=0.5,
            )
            context_text = "\n".join(context_list) if context_list else ""
            print(f"🔍 Contexto recuperado: {len(context_list)} mensajes")

            # 4.5 Lanzar orquestador en background y consumir eventos
            #     conforme van llegando a la cola.
            orchestrator_task = asyncio.create_task(
                orchestrator(
                    message,
                    user_id=str(current_user.id),
                    context=context_text,
                    event_callback=event_callback,
                )
            )

            # Emitir eventos mientras el orquestador trabaja
            while not orchestrator_task.done():
                # Verificar si el cliente desconectó
                if await request.is_disconnected():
                    orchestrator_task.cancel()
                    print(f"⚠️ Cliente desconectó: user={current_user.id} session={session_id}")
                    return

                # Vaciar cola
                async for chunk in drain_queue():
                    yield chunk

                # Keep-alive cada ~15 s para Cloud Run
                yield _sse_comment("heartbeat")
                await asyncio.sleep(0.3)

            # Vaciar cola final tras completar
            async for chunk in drain_queue():
                yield chunk

            # Obtener resultado
            result = await orchestrator_task

            print(f"📊 Resultado orquestador (SSE): {result}")

            # 4.6 Extraer respuesta
            result_text = (
                result if isinstance(result, str)
                else result.get("message", str(result))
            )
            result_metadata = (
                result.get("data", {}) if isinstance(result, dict) else {}
            )

            # 4.7 Guardar respuesta agente
            conversation_service.save_assistant_message(
                conversation_id=conversation.id,
                content=result_text,
                metadata=result_metadata,
                db=db,
            )

            # 4.8 Guardar en Qdrant
            user_message=message
            store_message(user_message, metadata={
                "role": "user",
                "conversation_id": str(conversation.id),
                "user_id": str(current_user.id),
            })
            store_message(result_text, metadata={
                "role": "assistant",
                "conversation_id": str(conversation.id),
                "user_id": str(current_user.id),
            })

            # 4.9 Registrar uso
            db.refresh(conversation)
            record_conversation_usage(current_user.id, db)

            # 4.10 Evento final → frontend cierra EventSource
            yield _sse_format("completed", {
                "session_id": session_id,
                "message": result_text,
                "data": {
                    "conversation_id": str(conversation.id),
                    "title": conversation.title,
                    **result_metadata,
                },
            })

        except Exception as e:
            print(f"❌ Error procesando mensaje SSE: {e}")
            yield _sse_format("error", {
                "session_id": session_id,
                "message": f"Error procesando tu mensaje: {str(e)}",
                "error_type": type(e).__name__,
            })
        finally:
            db.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            # Cabeceras críticas para SSE en Cloud Run / proxies
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",       # Desactiva buffer de Nginx/GCP
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",  # Ajusta al dominio real en prod
        },
    )