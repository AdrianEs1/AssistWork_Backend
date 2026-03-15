import google.generativeai as genai
import google.ai.generativelanguage as glm
from typing import Callable, Awaitable, Optional, Any

#from apps.services.mcp_client.mcp_manager import mcp_manager
from apps.services.mcp_client.mcp_manager import get_manager
from apps.services.prompt.agent_identity import AGENT_IDENTITY, OAUTH_GUIDE
from config import GOOGLE_API_KEY
import json

genai.configure(api_key=GOOGLE_API_KEY)

EventCallback = Optional[Callable[[str, dict], Awaitable[None]]]



async def orchestrator(
    user_input: str,
    user_id: Optional[str] = None,
    context: str = "",
    event_callback: EventCallback = None,
    conversation_history: Optional[list] = None
) -> dict:
    """Orquestador unificado basado en MCP y Function Calling nativo con ChatSession."""

    if event_callback:
        await event_callback("analyzing", {"message": "Analizando tu petición y conectando herramientas..."})
    
    manager=None
    # 1. Obtener herramientas de los servidores MCP conectados
    try:
        #from mcp_config import MCP_CONFIG
        # REEMPLAZA por:
        manager = await get_manager(user_id)
        mcp_tools = await manager.get_all_tools()
        gemini_tools = manager.to_gemini_tools(mcp_tools)
        print(f"🛠️ Tools cargadas: {len(mcp_tools)} MCP | {len(gemini_tools[0].function_declarations) if gemini_tools else 0} Gemini decls")
        if gemini_tools:
            for decl in gemini_tools[0].function_declarations:
                print(f"   → {decl.name}")
    except Exception as e:
        print(f"⚠️ Error cargando herramientas MCP: {e}")
        gemini_tools = []

    # 2. Construir el historial previo (solo mensajes anteriores, sin el input actual)
    history_for_chat = []

    if context:
        history_for_chat.append({"role": "user", "parts": [f"CONTEXTO SEMÁNTICO RELEVANTE:\n{context}"]})
        history_for_chat.append({"role": "model", "parts": ["Entendido, tendré este contexto en cuenta."]})

    if conversation_history:
        for msg in conversation_history:
            role = "user" if msg.get("role") in ["user", "tool_response"] else "model"
            history_for_chat.append({"role": role, "parts": [msg.get("content", "")]})

    # 3. Crear modelo y ChatSession con historial
    system_instruction = f"{AGENT_IDENTITY}\n\n{OAUTH_GUIDE}"

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        tools=gemini_tools or [],
        system_instruction=system_instruction,
        generation_config=genai.GenerationConfig(temperature=0.4, max_output_tokens=8000)
    )

    chat = model.start_chat(history=history_for_chat)

    # 4. Agent Loop usando ChatSession.send_message
    max_steps = 10
    step = 0

    # El primer mensaje usa mode=ANY para forzar el uso de una herramienta
    # Los siguientes usan AUTO para que el modelo pueda responder con texto
    current_message = user_input
    is_first_turn = True

    while step < max_steps:
        step += 1

        if event_callback and step > 1:
            await event_callback("processing", {"message": f"Pensando... (Paso {step})"})

        print(f"🧠 Llamando al LLM (Turno {step})...")

        # Configurar tool_config según el turno
        if gemini_tools and is_first_turn:
            tool_config = glm.ToolConfig(
                function_calling_config=glm.FunctionCallingConfig(
                    mode=glm.FunctionCallingConfig.Mode.ANY
                )
            )
        else:
            tool_config = None

        import anyio

        # Capturar variables para el closure
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
                "error": "NoCandidates"
            }

        model_content = response.candidates[0].content
        finish_reason = response.candidates[0].finish_reason
        print(f"🔍 Finish reason: {finish_reason} | Parts count: {len(model_content.parts)}")
        for i, p in enumerate(model_content.parts):
            has_fc = hasattr(p, 'function_call') and p.function_call.name
            has_txt = hasattr(p, 'text') and bool(p.text)
            print(f"   Part[{i}]: function_call={has_fc} | text={has_txt}")

        # Detectar function calls
        function_calls = [
            part.function_call
            for part in model_content.parts
            if hasattr(part, "function_call") and part.function_call.name
        ]

        if not function_calls:
            # Respuesta de texto final
            final_text = ""
            for part in model_content.parts:
                if hasattr(part, "text") and part.text:
                    final_text += part.text
            if not final_text:
                final_text = "Operación completada."

            if event_callback:
                await event_callback("saving", {"message": "Finalizando..."})

            return {
                "success": True,
                "message": final_text,
                "data": {"total_steps": step},
                "error": None
            }

        # Ejecutar herramientas y preparar la respuesta
        tool_response_parts = []
        for call in function_calls:
            tool_name = call.name

            args = {}
            if hasattr(call, 'args'):
                for key, value in call.args.items():
                    args[key] = value

            if user_id:
                args["user_id"] = user_id

            if event_callback:
                await event_callback("executing", {"message": f"Ejecutando {tool_name}..."})

            print(f"🔧 Ejecutando herramienta MCP: {tool_name} con args: {args}")

            if manager:
                result = await manager.call_tool(tool_name, args)
            else:
                result = {"success": False, "error": "Manager no encontrado"}
            tool_result_text = result.get("result", result.get("error", "Sin resultado"))
            print(f"DEBUG tool_result_text type: {type(tool_result_text)}")
            print(f"DEBUG tool_result_text value: {tool_result_text[:300]}")

            print(f"   ↳ Resultado de {tool_name}: {str(tool_result_text)[:200]}")

            try:
                tool_result_payload = json.loads(tool_result_text) if isinstance(tool_result_text, str) else tool_result_text
            except (json.JSONDecodeError, TypeError):
                tool_result_payload = {"text": tool_result_text}

            tool_response_parts.append(
                glm.Part(
                    function_response=glm.FunctionResponse(
                        name=tool_name,
                        response=tool_result_payload  # ← dict, no string
                    )
                )
            )

        # El próximo mensaje al chat son las respuestas de las herramientas
        current_message = tool_response_parts

    return {
        "success": False,
        "message": "Se alcanzó el límite de pasos lógicos del agente (max_steps).",
        "error": "MaxStepsReached"
    }