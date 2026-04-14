import base64
import re
import html
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any, List, Optional
from mcp.server.fastmcp import FastMCP

# Importa tu base (ajusta la ruta según tu proyecto)
from apps.services.oauth.google_service_base.google_service_base import GoogleServiceBase

# 1. Mantenemos tu clase de servicio intacta

import json

# Importa tu infraestructura base

# --- CLASE DE SERVICIO ORIGINAL ---
class GmailService(GoogleServiceBase):
    def __init__(self):
        super().__init__(service_name="gmail", api_version="v1")
    
    def _ping_service(self, service):
        profile = service.users().getProfile(userId="me").execute()
        return {
            "emailAddress": profile.get("emailAddress"),
            "messagesTotal": profile.get("messagesTotal")
        }

gmail_instance = GmailService()

# --- INICIALIZACIÓN FAST_MCP ---
mcp = FastMCP("AssistWork-Gmail")

# --- FUNCIONES AUXILIARES (Tu lógica de procesamiento) ---

def html_to_text(html_content: str) -> str:
    if not html_content: return ""
    html_content = html_content.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
    html_content = html_content.replace('</p>', '\n\n').replace('</div>', '\n')
    html_content = html_content.replace('</h1>', '\n').replace('</h2>', '\n')
    link_pattern = r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>'
    html_content = re.sub(link_pattern, r'\2 (\1)', html_content, flags=re.IGNORECASE)
    clean = re.compile('<.*?>')
    text = re.sub(clean, '', html_content)
    text = html.unescape(text)
    return '\n'.join([line.strip() for line in text.split('\n') if line.strip() or not line]).strip()

def extract_message_body(payload) -> str:
    body_parts = []
    def extract_parts(payload_part):
        if 'parts' in payload_part:
            for part in payload_part['parts']: extract_parts(part)
        else:
            mime_type = payload_part.get('mimeType', '')
            if mime_type in ['text/plain', 'text/html']:
                body_data = payload_part.get('body', {}).get('data')
                if body_data:
                    decoded = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')
                    if mime_type == 'text/html': decoded = html_to_text(decoded)
                    body_parts.append(decoded.strip())
    extract_parts(payload)
    return '\n\n'.join(body_parts).strip()

# --- HERRAMIENTAS MCP (MIGRACIÓN) ---

@mcp.tool()
async def send_email(user_id: str, to: str, subject: str, body: str, content_type: str = "auto") -> str:
    """Envía un email usando Gmail API. content_type: 'html' o 'text/html' para HTML, 'plain' para texto plano, 'auto' para detección automática."""
    try:
        service = gmail_instance.get_service(user_id)
        message = MIMEMultipart()
        message['to'] = to
        message['subject'] = subject
        
        is_html = (
            '<html>' in body.lower() or '<body>' in body.lower() or
            '<p>' in body.lower() or '<div>' in body.lower() or
            '<h1>' in body.lower() or '<h2>' in body.lower() or
            '<br>' in body.lower() or '</html>' in body.lower()
        )
        
        m_type = 'html' if content_type in ('text/html', 'html') or (content_type == 'auto' and is_html) else 'plain'
        
        message.attach(MIMEText(body, m_type, 'utf-8'))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        sent = service.users().messages().send(userId="me", body={'raw': raw}).execute()
        
        return json.dumps({
            "success": True,
            "id": sent["id"],
            "status_message": f"✅ Email enviado a {to}"
        })
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def list_emails(user_id: str, label: str = "INBOX", max_results: int = 5, query: str = None) -> str:
    """
    Lista emails. Retorna lista de IDs y metadata.
    IMPORTANTE: Para leer el contenido usa read_email(message_id=<id>) 
    donde <id> es SOLO el valor del campo 'id' de cada email (ej: '19ce00779ad89ecc').
    """
    try:
        service = gmail_instance.get_service(user_id)
        params = {"userId": "me", "maxResults": max_results}
        if query: params["q"] = query
        else: params["labelIds"] = [label.upper()]
        
        results = service.users().messages().list(**params).execute()
        messages = results.get("messages", [])
        
        detailed = []
        for msg in messages:
            m = service.users().messages().get(
                userId="me", id=msg['id'], format="metadata",
                metadataHeaders=['Subject', 'From', 'Date']
            ).execute()
            headers = m.get('payload', {}).get('headers', [])
            detailed.append({
                "message_id": msg['id'],  # ← Renombrado de 'id' a 'message_id'
                "subject": next((h['value'] for h in headers if h['name'] == 'Subject'), 'N/A'),
                "from": next((h['value'] for h in headers if h['name'] == 'From'), 'N/A'),
                "date": next((h['value'] for h in headers if h['name'] == 'Date'), 'N/A'),
                "snippet": m.get('snippet', '')
            })
        
        return json.dumps({
            "success": True,
            "count": len(detailed),
            "instruction": "Para leer cada email usa read_email con el campo 'message_id' de cada item",
            "emails": detailed
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def read_email(user_id: str, message_id: str, preview_length: int = 500, show_full: bool = False) -> str:
    """Lee el contenido completo de un email por su ID."""
    try:
        service = gmail_instance.get_service(user_id)
        msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        body = extract_message_body(msg.get('payload', {}))
        
        headers = msg.get('payload', {}).get('headers', [])
        return json.dumps({
            "success": True,
            "subject": next((h['value'] for h in headers if h['name'] == 'Subject'), ''),
            "from": next((h['value'] for h in headers if h['name'] == 'From'), ''),
            "body": body if show_full else f"{body[:preview_length]}..."
        }, indent=2)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
async def search_emails(user_id: str, query: str, max_results: int = 5) -> str:
    """Busca emails usando la sintaxis de búsqueda de Gmail (ej: 'from:google after:2024/01/01')."""
    return await list_emails(user_id=user_id, max_results=max_results, query=query)

@mcp.tool()
async def test_connection(user_id: str) -> str:
    """Verifica la conexión con la API de Gmail."""
    result = gmail_instance.test_connection(user_id)
    return json.dumps(result)

if __name__ == "__main__":
    mcp.run()