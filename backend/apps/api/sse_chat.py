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
from apps.models.message import Message
from apps.services.orchestrator.orchestrator_service import orchestrator
from apps.services.orchestrator.time_spent_specific import timer
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
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event_type}\ndata: {payload}\n\n"


def _sse_comment(text: str = "") -> str:
    """Heartbeat / keep-alive comment — mantiene la conexión viva en Cloud Run."""
    return f": {text}\n\n"


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def _update_title_background(
    conversation_id,
    first_message: str,
    user_id,
):
    """
    Genera y guarda el título de la conversación en segundo plano.
    Abre su propia sesión de DB para no interferir con el flujo principal.
    Si falla, el título queda como 'Nueva conversacion' — fallback aceptable.
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
    Con Qdrant local el costo es bajo (~5-20ms), pero así el evento
    'completed' llega al frontend sin esperar las escrituras vectoriales.
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

    Cambios respecto a la versión anterior:
        - Una sola sesión de DB para todo el flujo principal (antes: 3 separadas).
        - Auth usa su propia sesión efímera (necesario por el scope del generador).
        - update_conversation_title se lanza en background con asyncio.create_task.
        - Las escrituras de Qdrant (×2) se mueven a background: el evento
          'completed' llega al frontend sin esperar la indexación vectorial.
        - Heartbeat cada 8s en lugar de 300ms (reducción de ~94% de overhead).
        - Filtro de historial por created_at en lugar de content != message.

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

    # ── 1. Autenticación — sesión efímera propia ──────────────────────────
    # Necesita su propio bloque porque el generador de abajo es asíncrono
    # y no podemos compartir la sesión de forma segura entre ambos scopes.
    async with timer("...Tiempo empleado en Autenticación: "):
        db_auth = SessionLocal()
        try:
            current_user: User = await get_user_from_token(token, db_auth)
        except Exception as e:
            db_auth.close()

            async def auth_error():
                yield _sse_format("error", {
                    "message": f"Autenticación fallida: {str(e)}",
                    "error_type": "AuthError",
                    "session_id": session_id,
                })

            return StreamingResponse(auth_error(), media_type="text/event-stream")
        finally:
            db_auth.close()

    # ── 2. Generador principal ────────────────────────────────────────────
    async def event_generator():

        # Cola interna: el event_callback encola eventos,
        # el generador los saca y los formatea como SSE.
        queue: asyncio.Queue = asyncio.Queue()

        async def event_callback(event_type: str, event_data: dict):
            """Callback que recibe el orquestador y encola eventos SSE."""
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

        # Keep-alive inicial (Cloud Run necesita datos rápido)
        yield _sse_comment("connected")

        # ── Una sola sesión de DB para todo el flujo principal ────────────
        # Antes había 3 SessionLocal() separadas (auth + sub-check + bloque
        # principal). Ahora auth tiene la suya (ver arriba) y todo lo demás
        # comparte esta única sesión, que se cierra en el finally.
        db = SessionLocal()
        try:

            # ── 3. Verificar límites de suscripción ───────────────────────
            async with timer("...Tiempo empleado verificando límites de suscripción: "):
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

            # ── 4. Conversación ───────────────────────────────────────────
            async with timer("...Tiempo empleado obteniendo o creando conversación: "):
                conversation = conversation_service.get_or_create_active_conversation(
                    user_id=current_user.id,
                    conversation_id=conversation_id,
                    db=db,
                )

            # ── 5. Guardar mensaje usuario ────────────────────────────────
            async with timer("...Tiempo empleado guardando mensaje de usuario: "):
                saved_user_msg = conversation_service.save_user_message(
                    conversation_id=conversation.id,
                    content=message,
                    db=db,
                )
                # Guardamos el timestamp del mensaje recién insertado para
                # usarlo como corte al recuperar el historial (evita el
                # filtro frágil `content != message`).
                user_msg_created_at = (
                    saved_user_msg.created_at
                    if saved_user_msg and hasattr(saved_user_msg, "created_at")
                    else datetime.utcnow()
                )

            # ── 6. Título en background (no bloquea) ─────────────────────
            # Se lanza inmediatamente pero no esperamos su resultado.
            # Usa su propia sesión de DB (ver _update_title_background).
            if conversation.title == "Nueva conversacion":
                asyncio.create_task(
                    _update_title_background(
                        conversation_id=conversation.id,
                        first_message=message,
                        user_id=current_user.id,
                    )
                )

            # ── 7. Contexto semántico (Qdrant local — síncrono, es rápido) ─
            async with timer("...Tiempo empleado buscando contexto: "):
                context_list = search_context(
                    query=message,
                    user_id=str(current_user.id),
                    conversation_id=str(conversation.id),
                    limit=10,
                    score_threshold=0.5,
                )
                context_text = "\n".join(context_list) if context_list else ""
                print(f"🔍 Contexto recuperado: {len(context_list)} mensajes")

            # ── 8. Historial previo ───────────────────────────────────────
            # Filtramos por created_at < timestamp del mensaje recién guardado
            # en lugar de `content != message`, que era frágil (fallaba si el
            # usuario enviaba el mismo texto dos veces).
            past_messages = (
                db.query(Message)
                .filter(
                    Message.conversation_id == conversation.id,
                    Message.created_at < user_msg_created_at,
                )
                .order_by(Message.created_at.asc())
                .limit(20)
                .all()
            )
            conversation_history = [
                {"role": m.role, "content": m.content} for m in past_messages
            ]

            # ── 9. Orquestador en background + streaming de eventos ───────
            orchestrator_task = asyncio.create_task(
                orchestrator(
                    user_input=message,
                    user_id=str(current_user.id),
                    context=context_text,
                    event_callback=event_callback,
                    conversation_history=conversation_history,
                )
            )

            # Emitir eventos mientras el orquestador trabaja.
            # Heartbeat cada 8s — antes era 300ms (generaba ~200 eventos/min
            # vacíos por conexión activa, innecesario para Cloud Run).
            while not orchestrator_task.done():
                if await request.is_disconnected():
                    orchestrator_task.cancel()
                    print(f"⚠️ Cliente desconectó: user={current_user.id} session={session_id}")
                    return

                async for chunk in drain_queue():
                    yield chunk

                yield _sse_comment("heartbeat")
                await asyncio.sleep(8)

            # Vaciar cola final tras completar
            async for chunk in drain_queue():
                yield chunk

            # Obtener resultado
            result = await orchestrator_task
            print(f"📊 Resultado orquestador (SSE): {result}")

            # ── 10. Extraer respuesta ─────────────────────────────────────
            result_text = (
                result if isinstance(result, str)
                else result.get("message", str(result))
            )
            result_metadata = (
                result.get("data", {}) if isinstance(result, dict) else {}
            )

            # ── 11. Guardar respuesta agente ──────────────────────────────
            conversation_service.save_assistant_message(
                conversation_id=conversation.id,
                content=result_text,
                metadata=result_metadata,
                db=db,
            )

            # ── 12. Registrar uso ─────────────────────────────────────────
            # db.refresh eliminado: record_conversation_usage solo necesita
            # el user_id, no el objeto conversation completo.
            record_conversation_usage(current_user.id, db)

            # ── 13. Indexar en Qdrant en background (no bloquea) ─────────
            # El evento 'completed' se emite inmediatamente después de guardar
            # en DB. La indexación vectorial ocurre en paralelo.
            asyncio.create_task(
                _index_messages_background(
                    user_message=message,
                    result_text=result_text,
                    conversation_id=str(conversation.id),
                    user_id=str(current_user.id),
                )
            )

            # ── 14. Evento final → frontend cierra EventSource ────────────
            yield _sse_format("completed", {
                "session_id": session_id,
                "message": result_text,
                "data": {
                    "conversation_id": str(conversation.id),
                    "title": conversation.title,
                    **result_metadata,
                },
            })

        except SubscriptionLimitError as e:
            yield _sse_format("completed", {
                "session_id": session_id,
                "message": e.message,
                "upgrade_required": e.upgrade_required,
                "upgrade_url": "/pricing" if e.upgrade_required else None,
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
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )