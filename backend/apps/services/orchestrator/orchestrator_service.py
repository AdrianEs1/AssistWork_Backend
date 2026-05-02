import traceback
from typing import Callable, Awaitable, Optional

import google.adk as adk  # noqa: F401
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.events import Event
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

import google.generativeai as genai

from integrations import TOOL_REGISTRY
from apps.services.prompt.agent_identity import build_system_prompt
from apps.services.orchestrator.intent_classifier import classify_intent
from config import GOOGLE_API_KEY, MODEL_GOOGLE_IA
from .time_spent_global import measure_time
from .time_spent_specific import timer

genai.configure(api_key=GOOGLE_API_KEY)

EventCallback = Optional[Callable[[str, dict], Awaitable[None]]]

# ── Servicios y caché globales ────────────────────────────────────────────────
# InMemorySessionService mantiene el historial de ADK entre mensajes.
# En producción real, reemplazar por un SessionService persistente (Redis, DB).
_global_session_service = InMemorySessionService()

# Caché de contexto por user_id.
# Estructura: { user_id: { "runner": Runner, "session_id": str, "tools": list,
#                          "disconnected_apps": list, "prompt_base": str } }
_session_cache: dict[str, dict] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_disconnected_apps(registered_groups: set[str]) -> list[str]:
    """Detecta apps configuradas pero no registradas en el registry."""
    app_names = {
        "gmail":      "Gmail",
        "sheets":     "Sheets",
        "teams":      "Microsoft Teams",
        "localfiles": "Local Files",
    }
    return [name for gid, name in app_names.items() if gid not in registered_groups]


async def _build_session(user_id: str) -> tuple[Runner, str, list, list[str]]:
    """
    Crea Agent, Runner y sesión ADK para un user_id nuevo.
    Solo se llama UNA VEZ por usuario (primer mensaje).
    Devuelve (runner, session_id, adk_tools, disconnected_apps).
    """
    # Cargar herramientas
    adk_tools = TOOL_REGISTRY.get_adk_tools(user_id=user_id)
    registered_groups = {t["group"] for t in TOOL_REGISTRY.tools.values()}
    disconnected_apps = _detect_disconnected_apps(registered_groups)

    # System prompt base (sin is_first_message ni intent; se usará la versión
    # mínima aquí; el prompt real se pasa al Agent en cada turno si varía).
    # Para simplificar, construimos el prompt base con intent="agentTask" y
    # lo reconstruimos solo cuando cambien disconnected_apps.
    prompt_base = build_system_prompt(
        intent="agentTask",
        disconnected_apps=disconnected_apps,
        is_first_message=True,
        has_tool_error=False,
    )

    agent = Agent(
        name="AssistWork_Agent",
        model=MODEL_GOOGLE_IA,
        instruction=prompt_base,
        tools=adk_tools,
    )

    # Crear sesión ADK con ID fijo igual a user_id para poder recuperarla.
    try:
        session = await _global_session_service.create_session(
            user_id=user_id,
            app_name="AssistWork_Agent",
            session_id=user_id,
        )
    except Exception as e:
        print(f"⚠️ create_session falló, intentando get_session: {e}")
        session = await _global_session_service.get_session(
            user_id=user_id,
            app_name="AssistWork_Agent",
            session_id=user_id,
        )

    session_id = session.id if session else user_id

    runner = Runner(
        agent=agent,
        app_name="AssistWork_Agent",
        session_service=_global_session_service,
    )

    print(f"✅ Sesión ADK creada para user_id={user_id} | session_id={session_id}")
    return runner, session_id, adk_tools, disconnected_apps


def invalidate_session(user_id: str) -> None:
    """
    Invalida la caché de un usuario.
    Llamar cuando el usuario conecta o desconecta una integración,
    o cuando se quiera forzar un nuevo Agent con tools actualizadas.
    """
    if user_id in _session_cache:
        del _session_cache[user_id]
        print(f"🗑️ Caché invalidada para user_id={user_id}")


# ── Orquestador principal ─────────────────────────────────────────────────────

@measure_time
async def orchestrator(
    user_input: str,
    user_id: Optional[str] = None,
    context: str = "",
    event_callback: EventCallback = None,
    conversation_history: Optional[list] = None,
) -> dict:
    """
    Orquestador unificado con Google ADK.

    Optimizaciones respecto a la versión anterior:
    - Agent, Runner y sesión ADK se crean UNA SOLA VEZ por usuario y se
      reutilizan en mensajes posteriores (caché en _session_cache).
    - Las tools solo se recargan al invalidar la caché (conectar/desconectar app).
    - El historial externo se inyecta SOLO en el primer mensaje; en los
      siguientes ADK ya mantiene su propio historial.
    - Se emiten eventos de progreso entre cada fase costosa para que el
      frontend no se quede bloqueado en "analyzing".
    """

    session_key = user_id or "anonymous"
    is_new_session = session_key not in _session_cache

    # ── 1. Clasificar intención ───────────────────────────────────────────────
    # Siempre necesario; es rápido y determina el comportamiento del agente.
    # ── 2. Feedback temprano al frontend ─────────────────────────────────────
    if event_callback:
        await event_callback("analyzing", {"message": "Analizando tu petición..."})

    async with timer("classify_intent"):
        intent = classify_intent(user_input)
        print(f"🎯 Intención: {intent}")

    # ── 3. Obtener o crear contexto de sesión (costoso solo la primera vez) ──
    if is_new_session:
        if event_callback:
            await event_callback("loading", {"message": "Cargando herramientas..."})

        async with timer("build_session"):
            runner, session_id, adk_tools, disconnected_apps = await _build_session(session_key)

        _session_cache[session_key] = {
            "runner":           runner,
            "session_id":       session_id,
            "disconnected_apps": disconnected_apps,
        }
        print(f"🛠️ Tools cargadas: {len(adk_tools)} | Apps desconectadas: {disconnected_apps}")
    else:
        ctx = _session_cache[session_key]
        runner      = ctx["runner"]
        session_id  = ctx["session_id"]
        disconnected_apps = ctx["disconnected_apps"]
        print(f"♻️ Reutilizando sesión ADK para user_id={session_key}")

    # ── 4. System prompt (solo necesita intent; tools ya están en el Agent) ──
    # Reconstruimos el prompt cuando el intent o las apps desconectadas cambian.
    # En la mayoría de los mensajes esto es O(1) de string concatenación.
    is_first_message = bool(is_new_session)
    system_instruction = build_system_prompt(
        intent=intent,
        disconnected_apps=disconnected_apps,
        is_first_message=is_first_message,
        has_tool_error=False,
    )
    # Actualizar la instrucción del agente si cambió el intent
    # (ADK permite mutar agent.instruction antes de cada turno)
    runner.agent.instruction = system_instruction

    # ── 5. Inyectar historial externo SOLO en el primer mensaje ──────────────
    # En mensajes posteriores ADK ya tiene el historial dentro de la sesión.
    if is_new_session and conversation_history:
        if event_callback:
            await event_callback("connecting", {"message": "Cargando historial..."})

        async with timer("inject_history"):
            try:
                session_obj = await _global_session_service.get_session(
                    user_id=session_key,
                    app_name="AssistWork_Agent",
                    session_id=session_id,
                )
                if session_obj:
                    for msg in conversation_history:
                        author = (
                            "user"
                            if msg.get("role") in ["user", "tool_response"]
                            else "AssistWork_Agent"
                        )
                        content_obj = Content(parts=[Part(text=msg.get("content", ""))])
                        hist_event = Event(author=author, content=content_obj)
                        await _global_session_service.append_event(session_obj, hist_event)
                    print(f"📜 Historial inyectado: {len(conversation_history)} mensajes")
            except Exception as e:
                print(f"⚠️ Error inyectando historial: {e}")

    # ── 6. Notificar que el agente está pensando ──────────────────────────────
    if event_callback:
        await event_callback("thinking", {"message": "El agente está procesando..."})

    # ── 7. Ejecutar con Runner de ADK ─────────────────────────────────────────
    final_text = ""
    total_steps = 0

    try:
        async with timer("adk_run_async"):
            async for event in runner.run_async(
                new_message=Content(parts=[Part(text=user_input)]),
                session_id=session_id,
                user_id=session_key,
            ):
                total_steps += 1

                # ── Debug (quitar en producción) ──────────────────────────────
                print(f"\n{'='*50}")
                print(f"🔔 STEP {total_steps} | {type(event).__name__}")
                print(f"   author: {getattr(event, 'author', 'N/A')}")
                print(f"   is_final: {event.is_final_response() if hasattr(event, 'is_final_response') else 'N/A'}")
                if hasattr(event, "content") and event.content:
                    for i, part in enumerate(event.content.parts):
                        print(f"   Part[{i}]: {type(part).__name__}")
                        if hasattr(part, "text") and part.text:
                            print(f"     text: {part.text[:120]}")
                        if hasattr(part, "function_call") and part.function_call:
                            print(f"     🛠️ function_call: {part.function_call.name}")
                            print(f"     args: {part.function_call.args}")
                        if hasattr(part, "function_response") and part.function_response:
                            print(f"     ✅ function_response: {part.function_response.name}")
                            print(f"     response: {str(part.function_response.response)[:200]}")
                if hasattr(event, "error") and event.error:
                    print(f"   ❌ ERROR: {event.error}")
                print(f"{'='*50}\n")
                # ── Fin debug ─────────────────────────────────────────────────

                # Mapeo de eventos ADK → callbacks de UI
                if event_callback and hasattr(event, "content") and event.content:
                    for part in event.content.parts:
                        if hasattr(part, "function_call") and part.function_call:
                            # Nombre limpio sin prefijo del servidor MCP
                            tool_display = "_".join(part.function_call.name.split("_")[1:])
                            await event_callback("executing", {
                                "message": f"Ejecutando {tool_display}..."
                            })

                        if hasattr(part, "function_response") and part.function_response:
                            await event_callback("processing", {
                                "message": "Procesando resultado..."
                            })

                # Extraer texto de la respuesta final
                if hasattr(event, "is_final_response") and event.is_final_response():
                    content = getattr(event, "content", None)
                    if content and hasattr(content, "parts") and content.parts:
                        final_text = " ".join(
                            p.text
                            for p in content.parts
                            if hasattr(p, "text") and p.text
                        )
                    else:
                        final_text = str(content) if content else ""
                    break

        if event_callback:
            await event_callback("saving", {"message": "Finalizando..."})

        return {
            "success": True,
            "message": final_text or "Operación completada.",
            "data":    {"total_steps": total_steps},
            "error":   None,
        }

    except Exception as e:
        traceback.print_exc()
        print(f"❌ Error en ejecución ADK: {e}")

        # Si la sesión falló, la invalidamos para forzar recreación en el
        # siguiente mensaje en lugar de reutilizar un estado corrupto.
        invalidate_session(session_key)

        return {
            "success": False,
            "message": "Hubo un problema procesando tu solicitud con ADK.",
            "error":   str(e),
        }