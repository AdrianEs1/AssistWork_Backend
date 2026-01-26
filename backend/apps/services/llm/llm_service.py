import google.generativeai as genai
import anyio
from config import GOOGLE_API_KEY

# Configura la API key
genai.configure(api_key=GOOGLE_API_KEY)

import google.generativeai as genai
import anyio
from config import GOOGLE_API_KEY

# Configura la API key
genai.configure(api_key=GOOGLE_API_KEY)

async def call_llm(prompt: str, max_tokens: int = 8000) -> str:
    """
    Envía un prompt al modelo Gemini y devuelve el texto generado (async safe)
    
    Args:
        prompt: El prompt a enviar al modelo
        max_tokens: Máximo de tokens en la respuesta (default: 8000)
    """
    
    # Prompt mejorado sin diluir la instrucción original
    enhanced_prompt = f"""
        Eres un asistente inteligente que genera respuestas completas y detalladas.

        INSTRUCCIONES IMPORTANTES:
        - Genera respuestas COMPLETAS y DETALLADAS, no resúmenes cortos
        - Si se te pide un resumen, debe ser EXTENSO y abarcar todos los puntos principales
        - Responde en el formato solicitado
        - NO uses backticks de markdown en la respuesta
        - NO inicies con frases como "Claro, aquí tienes..." - ve directo al contenido

        {prompt}
        """
    
    def _sync_generate():
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        # Configuración de generación con tokens extendidos
        generation_config = genai.GenerationConfig(
            max_output_tokens=max_tokens,  # 🔥 CLAVE: Permite respuestas largas
            temperature=0.7,  # Balance entre creatividad y coherencia
        )
        
        return model.generate_content(
            enhanced_prompt,
            generation_config=generation_config
        )
    
    # Ejecutamos en un thread para no bloquear el loop de FastAPI
    response = await anyio.to_thread.run_sync(_sync_generate)
    
    if response and response.candidates:
        return response.candidates[0].content.parts[0].text.strip()
    else:
        return "No se pudo generar respuesta"



    