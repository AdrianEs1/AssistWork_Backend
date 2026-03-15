import os

# Determinar el entorno (puedes cambiarlo a "production" cuando lances)
ENV = os.getenv("APP_ENV", "development")

MCP_CONFIG = {
    "gmail": {
        "development": {
            "command": "python",
            "args": ["-m", "mcp_Server.GMAIL_ServerMCP"]
        },
        "production": "https://mcp-gmail.assistwork.ai/sse" # URL futura para producción
    },
    "localfiles": {
        "development": {
            "command": "python",
            "args": ["-m", "mcp_Server.LOCAL_FILES_ServerMCP"]
        },
        "production": "python" # A verificar futura ubicación en producción
    }
}