print("🚀 IMPORTANDO TEAMS MCP...")
import json
from typing import Optional
from mcp.server.fastmcp import FastMCP

from apps.services.oauth.microsoft_service_base.microsoft_service_base import MicrosoftServiceBase

print("MicrosoftServiceBase importado correctamente")
# --- SERVICE ---

class TeamsService(MicrosoftServiceBase):
    def __init__(self):
        super().__init__("teams")

    # -------------------- CHATS --------------------

    def list_chats(self, user_id: str):
        token = self.get_access_token(user_id)
        return self._request("GET", "/me/chats", token)

    def get_messages(self, user_id: str, chat_id: str):
        token = self.get_access_token(user_id)
        return self._request("GET", f"/chats/{chat_id}/messages", token)

    def send_message(self, user_id: str, chat_id: str, content: str):
        token = self.get_access_token(user_id)

        body = {
            "body": {
                "content": content
            }
        }

        return self._request(
            "POST",
            f"/chats/{chat_id}/messages",
            token,
            json=body
        )

# --- INSTANCE ---

teams_instance = TeamsService()

# --- MCP ---

mcp = FastMCP("AssistWork-Teams")

# -------------------- TOOLS --------------------

@mcp.tool()
async def list_chats(user_id: str) -> str:
    """Lista los chats del usuario en Microsoft Teams"""
    try:
        data = teams_instance.list_chats(user_id)

        chats = [
            {
                "chat_id": chat.get("id"),
                "topic": chat.get("topic"),
                "chat_type": chat.get("chatType")
            }
            for chat in data.get("value", [])
        ]

        return json.dumps({
            "success": True,
            "count": len(chats),
            "chats": chats
        }, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
async def list_messages(user_id: str, chat_id: str) -> str:
    """Lista mensajes de un chat"""
    try:
        data = teams_instance.get_messages(user_id, chat_id)

        messages = [
            {
                "message_id": msg.get("id"),
                "from": msg.get("from", {}).get("user", {}).get("displayName"),
                "content": msg.get("body", {}).get("content"),
                "created": msg.get("createdDateTime")
            }
            for msg in data.get("value", [])
        ]

        return json.dumps({
            "success": True,
            "count": len(messages),
            "messages": messages
        }, indent=2)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
async def send_message(user_id: str, chat_id: str, content: str) -> str:
    """Envía un mensaje a un chat de Teams"""
    try:
        data = teams_instance.send_message(user_id, chat_id, content)

        return json.dumps({
            "success": True,
            "message_id": data.get("id"),
            "status_message": "✅ Mensaje enviado en Teams"
        })

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


@mcp.tool()
async def test_connection(user_id: str) -> str:
    """Verifica conexión con Microsoft"""
    result = teams_instance.test_connection(user_id)
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run()