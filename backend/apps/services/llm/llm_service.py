import google.generativeai as genai
import google.ai.generativelanguage as glm
import anyio
from config import GOOGLE_API_KEY
from apps.services.prompt.agent_identity import AGENT_IDENTITY, OAUTH_GUIDE

# Configura la API key
genai.configure(api_key=GOOGLE_API_KEY)

async def call_llm(prompt: str, max_tokens: int = 8000) -> str:
    """Fallback para llamadas de texto simples (sin historial ni herramientas)."""
    def _sync_generate():
        model = genai.GenerativeModel("gemini-2.5-flash")
        generation_config = genai.GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=0.7,
        )
        return model.generate_content(prompt, generation_config=generation_config)
    
    response = await anyio.to_thread.run_sync(_sync_generate)
    if response and response.candidates:
        return response.candidates[0].content.parts[0].text.strip()
    return "No se pudo generar respuesta"

async def call_agentic_llm(history: list, tools: list | None = None, system_instruction: str | None = None, force_tool_use: bool = False) -> genai.types.GenerateContentResponse:
    """
    Función principal para el Worker Loop usando Function Calling.
    
    Args:
        history: Lista de mensajes en formato de Gemini [{'role': 'user'|'model', 'parts': [...]}]
        tools: Lista de herramientas (genai.types.Tool)
        system_instruction: Instrucciones base para el modelo
        force_tool_use: Si True usa mode=ANY (fuerza 1ra tool call). Si False usa mode=AUTO (permite text).
    """
    
    # Si no nos pasan instrucción, usamos la identidad por defecto combinada
    if not system_instruction:
        system_instruction = f"{AGENT_IDENTITY}\n\n{OAUTH_GUIDE}"

    def _sync_agent():
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            tools=tools or [],
            system_instruction=system_instruction
        )
        
        # Temperatura baja para function calling más determinista
        generation_config = genai.GenerationConfig(
            temperature=0.4,
            max_output_tokens=8000
        )
        
        request_kwargs = {
            "generation_config": generation_config
        }
        
        if tools:
            # Turno 1 (force_tool_use=True): mode=ANY fuerza al modelo a llamar una herramienta.
            # Turno 2+ (force_tool_use=False): mode=AUTO permite al modelo responder con texto
            # una vez que tiene los resultados de las herramientas.
            fc_mode = glm.FunctionCallingConfig.Mode.ANY if force_tool_use else glm.FunctionCallingConfig.Mode.AUTO
            request_kwargs["tool_config"] = glm.ToolConfig(
                function_calling_config=glm.FunctionCallingConfig(mode=fc_mode)
            )
        
        return model.generate_content(
            history,
            **request_kwargs
        )

    return await anyio.to_thread.run_sync(_sync_agent)