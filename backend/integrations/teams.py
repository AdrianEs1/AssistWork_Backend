import json
from typing import Optional
from apps.services.oauth.microsoft_service_base.microsoft_service_base import MicrosoftServiceBase
from apps.services.tool_registry import tool

# --- SERVICE ---

class TeamsService(MicrosoftServiceBase):
    def __init__(self):
        super().__init__("teams")

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

teams_instance = TeamsService()

# -------------------- TOOLS --------------------

@tool(group="teams")
async def list_teams_chats(user_id: str) -> str:
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

@tool(group="teams")
async def list_teams_messages(user_id: str, chat_id: str) -> str:
    """Lista mensajes de un chat de Teams"""
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

@tool(group="teams")
async def send_teams_message(user_id: str, chat_id: str, content: str) -> str:
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

@tool(group="teams")
async def test_teams_connection(user_id: str) -> str:
    """Verifica conexión con Microsoft Teams"""
    result = teams_instance.test_connection(user_id)
    return json.dumps(result)
