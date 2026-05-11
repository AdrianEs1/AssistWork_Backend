import traceback
from typing import Callable, Awaitable, Optional

#import google.adk as adk  # noqa: F401
from google.adk.agents import Agent
from google.adk.runners import Runner
#from google.adk.events import Event
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

import google.generativeai as genai

from integrations import TOOL_REGISTRY
from apps.services.prompt.agent_identity import build_system_prompt
from apps.services.orchestrator.intent_classifier import classify_intent
from config import GOOGLE_API_KEY, MODEL_GOOGLE_IA
from .time_spent_global import measure_time
from .time_spent_specific import timer
import uuid

genai.configure(api_key=GOOGLE_API_KEY)

EventCallback = Optional[Callable[[str, dict], Awaitable[None]]]



# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_disconnected_apps_from_db(user_id: str) -> list[str]:
    from apps.services.oauth.oauth_service import oauth_service
    from apps.database import SessionLocal

    app_integrations = {
        "gmail":      "Gmail",
        "sheets":     "Sheets",
        "teams":      "Microsoft Teams",
        "localfiles": "Local Files",
    }

    try:
        db = SessionLocal()
        disconnected = []
        for integration, app_name in app_integrations.items():
            conn = oauth_service.get_user_connection(user_id, integration, db)
            if not conn:
                disconnected.append(app_name)
        return disconnected
    except Exception as e:
        print(f"⚠️ Error consultando apps conectadas: {e}")
        return []
    finally:
        db.close()


async def _build_runner(user_id: str, disconnected_apps: list[str]) -> Runner:
    adk_tools = TOOL_REGISTRY.get_adk_tools(user_id=user_id)
    prompt_base = build_system_prompt(
        intent="agentTask",
        disconnected_apps=disconnected_apps,
        is_first_message=False,
        has_tool_error=False,
    )
    agent = Agent(
        name="AssistWork_Agent",
        model=MODEL_GOOGLE_IA,
        instruction=prompt_base,
        tools=adk_tools,
    )
    session_service = InMemorySessionService()
    session_id = str(uuid.uuid4())
    await session_service.create_session(
        user_id=user_id,
        app_name="AssistWork_Agent",
        session_id=session_id,
    )
    runner = Runner(
        agent=agent,
        app_name="AssistWork_Agent",
        session_service=session_service,
    )
    return runner, session_id, session_service


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
    - El historial externo se inyecta en los mensajes.
    - Se emiten eventos de progreso entre cada fase costosa para que el
      frontend no se quede bloqueado en "analyzing".
    """

    session_key = user_id or "anonymous"
    #is_new_session = session_key not in _session_cache

    # ── 1. Clasificar intención ───────────────────────────────────────────────
    # Siempre necesario; es rápido y determina el comportamiento del agente.
    # ── 2. Feedback temprano al frontend ─────────────────────────────────────
    if event_callback:
        await event_callback("analyzing", {"message": "Analizando tu petición..."})

    async with timer("classify_intent"):
        intent = await classify_intent(user_input)
        print(f"🎯 Intención: {intent}")

    disconnected_apps = _get_disconnected_apps_from_db(session_key)
    runner, session_id, _ = await _build_runner(session_key, disconnected_apps)
    print(f"🛠️ Runner construido para user_id={session_key}")

    # ── 4. System prompt (solo necesita intent; tools ya están en el Agent) ──
    # Reconstruimos el prompt cuando el intent o las apps desconectadas cambian.
    # En la mayoría de los mensajes esto es O(1) de string concatenación.
    is_first_message = not bool(conversation_history)
    system_instruction = build_system_prompt(
        intent=intent,
        disconnected_apps=disconnected_apps,
        is_first_message=is_first_message,
        has_tool_error=False,
    )
    runner.agent.instruction = system_instruction
    # Actualizar la instrucción del agente si cambió el intent
    # (ADK permite mutar agent.instruction antes de cada turno)
    #runner.agent.instruction = system_instruction


    # ── 6. Notificar que el agente está pensando ──────────────────────────────
    if event_callback:
        await event_callback("thinking", {"message": "El agente está procesando..."})

    # ── 7. Ejecutar con Runner de ADK ─────────────────────────────────────────
    final_text = ""
    total_steps = 0

    try:

        if conversation_history:
            history_text = "\n".join(
                f"{'Usuario' if m.get('role') == 'user' else 'Asistente'}: {m.get('content', '')}"
                for m in conversation_history
            )
            message_to_send = f"Contexto previo:\n{history_text}\n\nMensaje actual: {user_input}"
        else:
            message_to_send = user_input

        #message_to_send = f"[CONTEXTO DEL SISTEMA: {system_instruction}]\n\n{message_to_send}"
        # ✅ Correcto
        
        # Sin concatenar al mensaje
        print("message_to_send", message_to_send)

        
        async with timer("adk_run_async"):
            async for event in runner.run_async(
                new_message=Content(parts=[Part(text=message_to_send)]),
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
        #invalidate_session(session_key)

        return {
            "success": False,
            "message": "Hubo un problema procesando tu solicitud con ADK.",
            "error":   str(e),
        }