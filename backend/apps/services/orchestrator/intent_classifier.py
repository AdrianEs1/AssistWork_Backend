import google.generativeai as genai
from config import GOOGLE_API_KEY

genai.configure(api_key=GOOGLE_API_KEY)

def classify_intent(user_input: str) -> str:
    """
    Clasifica la instrucción del usuario en: agentConversation, agentHelp, o agentTask.
    """
    prompt = f"""
    Clasifica la siguiente instrucción del usuario en UNA de estas tres categorías:

    1. agentConversation: El usuario está saludando, despidiéndose, haciendo charla informal o comentarios generales que NO requieren buscar información ni ejecutar acciones. Ejemplo: "Hola", "¿Cómo estás?", "Gracias".
    2. agentHelp: El usuario pregunta sobre las funciones del agente, cómo usar la aplicación, configuraciones, o qué capacidades tiene AssistWork. Ejemplo: "¿Qué puedes hacer?", "¿Cómo conecto Gmail?", "Ayúdame con la configuración".
    3. agentTask: El usuario pide realizar una acción concreta que requiere herramientas como buscar correos, leer archivos, enviar mensajes, resumir documentos, etc. Ejemplo: "Busca correos de Juan", "Resume el archivo reporte.pdf", "Enviame un mensaje por Teams".

    Responde ÚNICAMENTE con el nombre de la categoría (agentConversation, agentHelp o agentTask).

    Instrucción: "{user_input}"
    Categoría:"""

    model = genai.GenerativeModel("gemini-2.5-flash")
    
    try:
        response = model.generate_content(prompt)
        intent = response.text.strip().lower()
        
        if "agentconversation" in intent:
            return "agentConversation"
        elif "agenthelp" in intent:
            return "agentHelp"
        elif "agenttask" in intent:
            return "agentTask"
        else:
            # Fallback a agentTask por seguridad
            return "agentTask"
    except Exception as e:
        print(f"⚠️ Error en clasificación de intención: {e}")
        return "agentTask"
