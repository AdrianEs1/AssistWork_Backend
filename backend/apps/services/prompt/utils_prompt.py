import re

def clean_llm_response(text: str) -> str:
    """
    Limpia respuestas de modelos LLM que vienen envueltas en bloques de Markdown.
    Elimina ```json ... ``` o ``` ... ```, y espacios extra.
    """
    if not text:
        return text.strip()
    
    # Quitar delimitadores ```json ... ``` o ``` ... ```
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())

    # En algunos casos el modelo deja backticks sueltos
    cleaned = cleaned.replace("```", "").strip()
    
    return cleaned
