import google.generativeai as genai
import google.ai.generativelanguage as glm
import anyio
from config import GOOGLE_API_KEY
#from apps.services.prompt.agent_identity import AGENT_IDENTITY, OAUTH_GUIDE

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


    
    