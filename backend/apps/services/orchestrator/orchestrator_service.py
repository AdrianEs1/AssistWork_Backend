import google.generativeai as genai
import google.ai.generativelanguage as glm
from typing import Callable, Awaitable, Optional
import anyio
import json

from apps.services.mcp_client.mcp_manager import get_manager
from apps.services.prompt.agent_identity import build_system_prompt
from apps.services.orchestrator.intent_classifier import classify_intent
from config import GOOGLE_API_KEY

#Funciones para determinar el tiempo gastado durante un loop en el orchestrator
from .time_spent_global import measure_time
from .time_spent_specific import timer

genai.configure(api_key=GOOGLE_API_KEY)

EventCallback = Optional[Callable[[str, dict], Awaitable[None]]]

@measure_time
async def orchestrator(
    user_input: str,
    user_id: Optional[str] = None,
    context: str = "",
    event_callback: EventCallback = None,
    conversation_history: Optional[list] = None,
) -> dict:
    """Orquestador unificado con system prompt dinámico y agente loop MCP."""

    
    if event_callback:
        await event_callback("analyzing", {"message": "Analizando tu petición..."})

    # ── 1. Clasificar intención ─────────────────────────────────────────────
    async with timer("...Tiempo empleado Analizando peticion.."):
        intent = classify_intent(user_input)
        print(f"🎯 Intención detectada: {intent}")

    # ── 2. Cargar herramientas MCP (Solo si es agentTask) ───────────────────
    manager = None
    gemini_tools = []
    disconnected_apps = []

    if intent == "agentTask":
        try:
            manager = await get_manager(user_id)
            mcp_tools = await manager.get_all_tools()
            gemini_tools = manager.to_gemini_tools(mcp_tools)

            total_decls = sum(len(t.function_declarations) for t in gemini_tools)
            print(f"🛠️ Tools cargadas: {len(mcp_tools)} MCP | {total_decls} Gemini decls")

        except Exception:
            import traceback
            print("⚠️ Error cargando herramientas MCP:")
            traceback.print_exc()
    else:
        print(f"ℹ️ Saltando carga de herramientas MCP para intención: {intent}")

    # ── 2. Detectar apps desconectadas (rápido, sin llamadas extra) ─────────
    # Inferimos del resultado del test de conexión que ya hace el manager.
    # Si prefieres, puedes pasar `connected_apps` como parámetro desde el frontend.
    tool_names = [
        decl.name
        for tool in gemini_tools
        for decl in tool.function_declarations
    ]
    if not any("gmail" in t for t in tool_names):
        disconnected_apps.append("Gmail")
    if not any("teams" in t for t in tool_names):
        disconnected_apps.append("Microsoft Teams")

    # ── 3. Construir system prompt dinámico ─────────────────────────────────
    is_first_message = not conversation_history  # Sin historial = primer turno

    system_instruction = build_system_prompt(
        intent=intent,
        disconnected_apps=disconnected_apps,
        is_first_message=is_first_message,
        has_tool_error=False,
    )

    print(f"\nEsto es la System_instruction que se envia al LLM según la intencion {intent}:\n {system_instruction}\n")

    # ── 4. Construir historial para ChatSession ──────────────────────────────
    history_for_chat = []

    if context:
        history_for_chat.append({
            "role": "user",
            "parts": [f"CONTEXTO SEMÁNTICO RELEVANTE:\n{context}"],
        })
        history_for_chat.append({
            "role": "model",
            "parts": ["Entendido, tendré este contexto en cuenta."],
        })

    if conversation_history:
        for msg in conversation_history:
            role = "user" if msg.get("role") in ["user", "tool_response"] else "model"
            history_for_chat.append({"role": role, "parts": [msg.get("content", "")]})

    # ── 5. Crear modelo y ChatSession ───────────────────────────────────────
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        tools=gemini_tools or [],
        system_instruction=system_instruction,
        generation_config=genai.GenerationConfig(
            temperature=0.4,
            max_output_tokens=8000,
        ),
    )

    chat = model.start_chat(history=history_for_chat)

    # ── 6. Agent loop ────────────────────────────────────────────────────────
    max_steps = 10
    step = 0
    current_message = user_input
    is_first_turn = True
    has_tool_error = False

    # Si NO es agentTask, no forzamos tools y limitamos a 1 paso
    if intent != "agentTask":
        max_steps = 1

    while step < max_steps:
        step += 1

        if event_callback and step > 1:
            await event_callback("processing", {"message": f"Pensando... (Paso {step})"})

        print(f"🧠 Llamando al LLM (Turno {step})...")

        # Primer turno: forzar uso de herramienta si hay tools disponibles
        tool_config = None
        if gemini_tools and is_first_turn:
            tool_config = glm.ToolConfig(
                function_calling_config=glm.FunctionCallingConfig(
                    mode=glm.FunctionCallingConfig.Mode.AUTO
                )
            )

        _message = current_message
        _tool_config = tool_config

        def _send():
            kwargs = {}
            if _tool_config:
                kwargs["tool_config"] = _tool_config
            return chat.send_message(_message, **kwargs)

        response = await anyio.to_thread.run_sync(_send)
        is_first_turn = False

        if not response or not response.candidates:
            return {
                "success": False,
                "message": "El modelo no generó una respuesta válida.",
                "error": "NoCandidates",
            }

        model_content = response.candidates[0].content
        finish_reason = response.candidates[0].finish_reason

        print(f"🔍 Finish reason: {finish_reason} | Parts: {len(model_content.parts)}")
        for i, p in enumerate(model_content.parts):
            has_fc = hasattr(p, "function_call") and p.function_call.name
            has_txt = hasattr(p, "text") and bool(p.text)
            print(f"   Part[{i}]: function_call={has_fc} | text={has_txt}")

        # Detectar function calls
        function_calls = [
            part.function_call
            for part in model_content.parts
            if hasattr(part, "function_call") and part.function_call.name
        ]

        # Sin function calls → respuesta final de texto
        if not function_calls:
            final_text = "".join(
                part.text
                for part in model_content.parts
                if hasattr(part, "text") and part.text
            ) or "Operación completada."

            if event_callback:
                await event_callback("saving", {"message": "Finalizando..."})

            return {
                "success": True,
                "message": final_text,
                "data": {"total_steps": step},
                "error": None,
            }

        # ── Ejecutar herramientas ────────────────────────────────────────────
        tool_response_parts = []

        for call in function_calls:
            tool_name = call.name
            args = {key: value for key, value in call.args.items()} if hasattr(call, "args") else {}

            if user_id:
                args["user_id"] = user_id

            if event_callback:
                await event_callback("executing", {"message": f"Ejecutando {tool_name}..."})

            print(f"🔧 Ejecutando: {tool_name} | args: {args}")

            result = (
                await manager.call_tool(tool_name, args)
                if manager
                else {"error": "Manager no encontrado"}
            )

            tool_result_text = result.get("result", result.get("error", "Sin resultado"))
            print(f"   ↳ {tool_name}: {str(tool_result_text)[:200]}")

            # Detectar error en herramienta para ajustar el prompt en el siguiente turno
            if isinstance(tool_result_text, str) and (
                '"success": false' in tool_result_text or "error" in tool_result_text.lower()
            ):
                has_tool_error = True

            try:
                tool_result_payload = (
                    json.loads(tool_result_text)
                    if isinstance(tool_result_text, str)
                    else tool_result_text
                )
            except (json.JSONDecodeError, TypeError):
                tool_result_payload = {"text": tool_result_text}

            tool_response_parts.append(
                glm.Part(
                    function_response=glm.FunctionResponse(
                        name=tool_name,
                        response=tool_result_payload,
                    )
                )
            )

        # Si hubo error, reconstruir el system prompt antes del siguiente turno
        # Nota: Gemini no permite cambiar system_instruction en mid-session,
        # pero sí podemos incluir el hint en el mensaje de tool response.
        if has_tool_error:
            from apps.services.prompt.agent_identity import TROUBLESHOOTING_HINT
            tool_response_parts.append(
                glm.Part(text=f"\n[SISTEMA]: {TROUBLESHOOTING_HINT}")
            )

        current_message = tool_response_parts

    return {
        "success": False,
        "message": "Se alcanzó el límite de pasos del agente.",
        "error": "MaxStepsReached",
    }