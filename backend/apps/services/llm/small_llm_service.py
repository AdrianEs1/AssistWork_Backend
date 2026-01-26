import httpx
from config import GROQ_API_KEY, GROQ_MODEL, GROQ_URL

async def call_small_llm(promp: str) -> str:
    """
    Envía prompt al modelo pequeño en Groq y devuelve la decisión.
    Este modelo sirve como orquestador (decide si usar tools o pasar a Gemini).
    """
    ROLE_CONTENT = (
        "Eres un orquestador. Decide si la instrucción del usuario es para ejecutar "
        "una herramienta o debe pasar al LLM principal."
        "Responde EN JSON valido"
    )

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY.strip()}",
        "Content-Type": "application/json"
    }

    body = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": ROLE_CONTENT},
            {"role": "user", "content": promp}
        ],
        "temperature": 0.2,
        "max_tokens": 256
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        response = await client.post(GROQ_URL, headers=headers, json=body)

    if response.status_code != 200:
        raise Exception(f"Error Groq API: {response.text}")

    data = response.json()
    return data["choices"][0]["message"]["content"].strip()
