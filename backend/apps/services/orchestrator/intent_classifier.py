import google.generativeai as genai
from config import GOOGLE_API_KEY

genai.configure(api_key=GOOGLE_API_KEY)

_CLASSIFY_PROMPT = """Clasifica en una categoría:
- agentTask: acciones concretas (buscar, leer, enviar, resumir)
- agentHelp: preguntas sobre el agente o configuración
- agentConversation: saludos, charla, comentarios generales

Responde SOLO con el nombre. Instrucción: """

_model = genai.GenerativeModel(
    "gemini-2.0-flash-lite",
    generation_config=genai.GenerationConfig(
        max_output_tokens=20,
        temperature=0,
    )
)

async def classify_intent(user_input: str) -> str:
    try:
        response = _model.generate_content(_CLASSIFY_PROMPT + user_input)
        intent = response.text.strip().lower()

        if "agentconversation" in intent:
            return "agentConversation"
        elif "agenthelp" in intent:
            return "agentHelp"
        else:
            return "agentTask"
    except Exception:
        return "agentTask"