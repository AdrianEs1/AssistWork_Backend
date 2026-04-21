import google.adk as adk
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.events import Event
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part
from typing import Callable, Awaitable, Optional, List
import anyio
import json
import traceback

import integrations
from integrations import TOOL_REGISTRY
from apps.services.prompt.agent_identity import build_system_prompt
from apps.services.orchestrator.intent_classifier import classify_intent
from config import GOOGLE_API_KEY

# Funciones para determinar el tiempo gastado durante un loop en el orchestrator
from .time_spent_global import measure_time
from .time_spent_specific import timer

import google.generativeai as genai
genai.configure(api_key=GOOGLE_API_KEY)

EventCallback = Optional[Callable[[str, dict], Awaitable[None]]]

# Usamos un session service global durante la ejecución del proceso para el historial
# En una app de producción real, esto podría estar en una base de datos
_global_session_service = InMemorySessionService()

@measure_time
async def orchestrator(
    user_input: str,
    user_id: Optional[str] = None,
    context: str = "",
    event_callback: EventCallback = None,
    conversation_history: Optional[list] = None,
) -> dict:
    """Orquestador unificado utilizando Google ADK para la ejecución del agente."""

    if event_callback:
        await event_callback("analyzing", {"message": "Analizando tu petición..."})

    # ── 1. Clasificar intención ─────────────────────────────────────────────
    async with timer("...Tiempo empleado Analizando peticion.."):
        intent = classify_intent(user_input)
        print(f"🎯 Intención detectada: {intent}")

    # ── 2. Cargar herramientas (In-Process) ──────────────────────────────────
    adk_tools = []
    disconnected_apps = []

    if intent == "agentTask":
        async with timer("...Tiempo empleado cargando herramientas en agenTask : "):
            try:
                # Obtenemos las herramientas directamente del registry (sin subprocesos)
                adk_tools = TOOL_REGISTRY.get_adk_tools(user_id=user_id)
                
                # Detectar apps disponibles dinámicamente
                registered_groups = {t["group"] for t in TOOL_REGISTRY.tools.values()}
                
                # Mapa de grupos a nombres legibles para el prompt
                app_names = {
                    "gmail": "Gmail",
                    "sheets": "Sheets",
                    "teams": "Microsoft Teams",
                    "localfiles": "Local Files"
                }
                
                for group_id, group_name in app_names.items():
                    if group_id not in registered_groups:
                        disconnected_apps.append(group_name)

                print(f"🛠️ Tools ADK cargadas: {len(adk_tools)}")
            except Exception:
                print("⚠️ Error cargando herramientas del registry:")
                traceback.print_exc()
    else:
        print(f"ℹ️ Saltando carga de herramientas para intención: {intent}")

    # ── 3. Construir system prompt dinámico ─────────────────────────────────
    is_first_message = not conversation_history
    system_instruction = build_system_prompt(
        intent=intent,
        disconnected_apps=disconnected_apps,
        is_first_message=is_first_message,
        has_tool_error=False,
    )

    # ── 4. Configurar Agente y Runner ADK ─────────────────────────────────────
    agent = Agent(
        name="AssistWork_Agent",
        model="gemini-2.5-flash-lite", # Mantenemos el modelo solicitado
        instruction=system_instruction,
        tools=adk_tools,
    )

    # Usamos el user_id para identificar al usuario en ADK
    session_id = user_id or "anonymous_session"

    # ── La sesión SIEMPRE debe existir antes de llamar a run_async ───────────
    # CRÍTICO: pasamos session_id explícitamente para que el Runner pueda
    # encontrarla al buscarlo por ese mismo ID.
    try:
        session = await _global_session_service.create_session(
            user_id=session_id,
            app_name="AssistWork_Agent",
            session_id=session_id,   # ← fijamos el ID para que coincida con run_async
        )
    except Exception as e:
        print(f"⚠️ Error creando sesión ADK (intentando obtener existente): {e}")
        session = await _global_session_service.get_session(
            user_id=session_id,
            app_name="AssistWork_Agent",
            session_id=session_id,
        )

    # Usamos el ID real del objeto sesión por si ADK lo normalizó
    adk_session_id = session.id if session else session_id
    print(f"✅ Sesión ADK lista: {adk_session_id}")

    # IMPORTANTE: Si hay historial externo, lo inyectamos en la sesión de ADK
    # append_event(session, event) — primer arg es el objeto Session, no el ID
    if conversation_history and session:
        try:
            for msg in conversation_history:
                # ADK reconoce 'user' para el usuario y el nombre del agente para el modelo
                author = "user" if msg.get("role") in ["user", "tool_response"] else "AssistWork_Agent"
                content_obj = Content(parts=[Part(text=msg.get("content", ""))])
                hist_event = Event(author=author, content=content_obj)
                await _global_session_service.append_event(session, hist_event)
        except Exception as e:
            print(f"⚠️ Error cargando historial en ADK session: {e}")

    runner = Runner(
        agent=agent,
        app_name="AssistWork_Agent",
        session_service=_global_session_service
    )

    # ── 5. Ejecutar con Runner de ADK y mapear eventos ────────────────────────
    final_text = ""
    total_steps = 0

    try:
        async with timer("...Tiempo empleado en ejecución ADK : "):
            # Ejecutamos pasando el session_id para que use el historial cargado
            # ADK v1.30+ requiere que el mensaje sea un objeto Content
            async for event in runner.run_async(
                new_message=Content(parts=[Part(text=user_input)]),
                session_id=adk_session_id,
                user_id=session_id
            ):
                total_steps += 1


                # ═══ DEBUG COMPLETO ═══
                print(f"\n{'='*50}")
                print(f"🔔 STEP {total_steps} | Tipo: {type(event).__name__}")
                print(f"   author: {getattr(event, 'author', 'N/A')}")
                print(f"   is_final_response: {event.is_final_response() if hasattr(event, 'is_final_response') else 'N/A'}")
                
                if hasattr(event, 'content') and event.content:
                    for i, part in enumerate(event.content.parts):
                        print(f"   Part[{i}]: {type(part).__name__}")
                        if hasattr(part, 'text') and part.text:
                            print(f"     text: {part.text[:100]}")
                        if hasattr(part, 'function_call') and part.function_call:
                            print(f"     🛠️ function_call: {part.function_call.name}")
                            print(f"     args: {part.function_call.args}")
                        if hasattr(part, 'function_response') and part.function_response:
                            print(f"     ✅ function_response: {part.function_response.name}")
                            print(f"     response: {str(part.function_response.response)[:200]}")
                
                if hasattr(event, 'error') and event.error:
                    print(f"   ❌ ERROR en evento: {event.error}")
                print(f"{'='*50}\n")
                # ═══ FIN DEBUG ═══
                
                # Mapeo de eventos ADK -> Callbacks de UI
                if event_callback and hasattr(event, 'content') and event.content:
                    for part in event.content.parts:
                        
                        # Modelo decidió llamar una tool
                        if hasattr(part, 'function_call') and part.function_call:
                            # Quitar prefijo del servidor para mostrar nombre limpio
                            tool_display = "_".join(part.function_call.name.split("_")[1:])
                            await event_callback("executing", {
                                "message": f"Ejecutando {tool_display}..."
                            })
                        
                        # Tool respondió, modelo está procesando el resultado
                        if hasattr(part, 'function_response') and part.function_response:
                            await event_callback("processing", {
                                "message": "Procesando resultado..."
                            })
                
                # Extraer texto plano del objeto Content retornado por ADK
                # Extraer texto de la respuesta final
                if hasattr(event, "is_final_response") and event.is_final_response():
                    content = getattr(event, "content", None)
                    if content and hasattr(content, "parts") and content.parts:
                        final_text = " ".join(
                            p.text for p in content.parts 
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
            "data": {"total_steps": total_steps},
            "error": None,
        }

    except Exception as e:
        traceback.print_exc()
        print(f"❌ Error en la ejecución de ADK: {e}")
        return {
            "success": False,
            "message": "Hubo un problema procesando tu solicitud con ADK.",
            "error": str(e),
        }