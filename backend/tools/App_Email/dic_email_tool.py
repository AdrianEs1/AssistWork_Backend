from typing import Dict, Any
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import re
import html
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from sqlalchemy.orm import Session
from apps.models.oauth_connection import OAuthConnection
from apps.database import SessionLocal
from datetime import datetime, timedelta
from tools.google_service_base import GoogleServiceBase


#SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

class GmailService(GoogleServiceBase):
    def __init__(self):
        super().__init__(service_name="gmail", api_version="v1")
    
    def _ping_service(self, service):
        """Verifica conexión con Gmail obteniendo perfil."""
        profile = service.users().getProfile(userId="me").execute()
        
        print(f"ℹ️ Ping Gmail ejecutado correctamente. Email: {profile.get('emailAddress')}")
        
        return {
            "emailAddress": profile.get("emailAddress"),
            "messagesTotal": profile.get("messagesTotal"),
            "threadsTotal": profile.get("threadsTotal"),
            "historyId": profile.get("historyId")
        }

gmail = GmailService()


def send_email(user_id: str, to: str, subject: str, body: str, **kwargs) -> Dict[str, Any]:
    """
    Envía un email usando Gmail API
    
    Args:
        user_id: UUID del usuario
        to: Email destinatario
        subject: Asunto del email
        body: Contenido del email
    """
    try:
        service = gmail.get_service(user_id)
       
        message = MIMEMultipart()
        message['to'] = to
        message['subject'] = subject
       
        is_html = (
            '<html>' in body.lower() or '<body>' in body.lower() or
            '<p>' in body.lower() or '<div>' in body.lower() or
            '<h1>' in body.lower() or '<h2>' in body.lower() or
            '<br>' in body.lower() or '</html>' in body.lower()
        )
       
        content_type = kwargs.get('content_type', 'auto')
       
        if content_type == 'text/html' or (content_type == 'auto' and is_html):
            msg = MIMEText(body, 'html', 'utf-8')
        else:
            msg = MIMEText(body, 'plain', 'utf-8')
       
        message.attach(msg)
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        email_message = {'raw': raw_message}
       
        sent_message = service.users().messages().send(
            userId="me",
            body=email_message
        ).execute()
       
        return {
            "success": True,
            "id": sent_message["id"],
            "to": to,
            "subject": subject,
            "message": f"✅ **Email enviado exitosamente**\n\n📧 **Para:** {to}\n📝 **Asunto:** {subject}\n🕐 **Estado:** Entregado correctamente"
        }
       
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"❌ **Error enviando email**\n\n📧 **Destinatario:** {to}\n📝 **Asunto:** {subject}\n🚫 **Error:** {str(e)}"
        }


def list_emails(user_id: str, label: str = "INBOX", max_results: int = 5, query: str = None, **kwargs) -> Dict[str, Any]:
    """
    Lista emails del usuario
    
    Args:
        user_id: ID del usuario
        label: Etiqueta de Gmail (INBOX, SENT, DRAFT, SPAM, TRASH)
        max_results: Número máximo de emails a listar
        query: Búsqueda adicional opcional (ej: "from:juan subject:proyecto")
    """
    try:
        service = gmail.get_service(user_id)
        
        # Construir parámetros de búsqueda
        search_params = {
            "userId": "me",
            "maxResults": max_results
        }
        
        # Si hay query específica, usarla (búsqueda avanzada)
        if query:
            search_params["q"] = query
        else:
            # Si no hay query, usar labelIds para filtrar por bandeja
            search_params["labelIds"] = [label]
        
        results = service.users().messages().list(**search_params).execute()
        messages = results.get("messages", [])
        
        if not messages:
            return {
                "success": True,
                "messages": [],
                "message": "📧 **No se encontraron emails**\n\nNo hay emails que coincidan con tu búsqueda."
            }
        
        detailed_messages = []
        user_message = f"📧 **Encontrados {len(messages)} emails:**\n\n"
        
        for i, msg in enumerate(messages, 1):
            try:
                msg_details = service.users().messages().get(
                    userId="me", 
                    id=msg['id'], 
                    format="metadata",
                    metadataHeaders=['Subject', 'From', 'Date']
                ).execute()
                
                headers = msg_details.get('payload', {}).get('headers', [])
                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'Sin asunto')
                from_email = next((h['value'] for h in headers if h['name'] == 'From'), 'Desconocido')
                date = next((h['value'] for h in headers if h['name'] == 'Date'), 'Fecha desconocida')
                from_clean = from_email.split('<')[0].strip().strip('"') if '<' in from_email else from_email
                
                user_message += f"**{i}. {subject}**\n"
                user_message += f"   📤 **De:** {from_clean}\n"
                user_message += f"   📅 **Fecha:** {date[:25]}...\n"
                user_message += f"   🆔 **ID:** `{msg['id']}`\n\n"
                
                detailed_messages.append({
                    "id": msg['id'],
                    "subject": subject,
                    "from": from_clean,
                    "date": date,
                    "snippet": msg_details.get('snippet', '')
                })
                
            except Exception as e:
                user_message += f"**{i}. Error obteniendo email**\n   🚫 **Error:** {str(e)}\n\n"
        
        return {
            "success": True,
            "messages": detailed_messages,
            "raw_messages": messages,
            "message": user_message
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"❌ **Error listando emails**\n\n🚫 **Error:** {str(e)}"
        }


def read_email(user_id: str, message_id: str, **kwargs) -> Dict[str, Any]:
    """Lee un email específico"""
    try:
        service = gmail.get_service(user_id)
        msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
       
        headers = msg.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'Sin asunto')
        from_email = next((h['value'] for h in headers if h['name'] == 'From'), 'Desconocido')
        to_email = next((h['value'] for h in headers if h['name'] == 'To'), 'Desconocido')
        date = next((h['value'] for h in headers if h['name'] == 'Date'), 'Fecha desconocida')
        from_clean = from_email.split('<')[0].strip().strip('"') if '<' in from_email else from_email
        
        body = extract_message_body(msg.get('payload', {}))
        preview_length = kwargs.get('preview_length', 500)
        show_full = kwargs.get('show_full', False)
        
        user_message = f"📧 **Email leído exitosamente**\n\n"
        user_message += f"📝 **Asunto:** {subject}\n"
        user_message += f"📤 **De:** {from_clean}\n"
        user_message += f"📥 **Para:** {to_email}\n"
        user_message += f"📅 **Fecha:** {date}\n"
        user_message += f"🆔 **ID:** `{message_id}`\n\n"
        
        if show_full or len(body) <= preview_length:
            user_message += f"📄 **Contenido:**\n```\n{body}\n```"
        else:
            user_message += f"📄 **Contenido:**\n```\n{body[:preview_length]}...\n```\n\n*(Vista previa truncada)*"
       
        return {
            "success": True,
            "message_id": message_id,
            "subject": subject,
            "from": from_clean,
            "to": to_email,
            "date": date,
            "body": body,
            "body_length": len(body),
            "body_preview": body[:preview_length] if len(body) > preview_length else body,
            "raw_message": msg,
            "message": user_message
        }
       
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"❌ **Error leyendo email**\n\n🆔 **ID:** `{message_id}`\n🚫 **Error:** {str(e)}"
        }

def search_emails(
    user_id: str, 
    from_email: str = None, 
    to_email: str = None,
    subject: str = None, 
    content: str = None,
    date_after: str = None,
    date_before: str = None,
    has_attachment: bool = None,
    max_results: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """
    Busca emails específicos usando criterios de búsqueda de Gmail
    
    Args:
        user_id: ID del usuario
        from_email: Buscar por remitente (ej: "juan@example.com" o solo "juan")
        to_email: Buscar por destinatario
        subject: Buscar por palabras en el asunto
        content: Buscar por palabras en el contenido
        date_after: Buscar después de fecha (formato: YYYY/MM/DD)
        date_before: Buscar antes de fecha (formato: YYYY/MM/DD)
        has_attachment: True para emails con adjuntos
        max_results: Número máximo de resultados
    
    Examples:
        search_emails(user_id, from_email="juan", subject="proyecto")
        → Busca correos de Juan con "proyecto" en el asunto
        
        search_emails(user_id, date_after="2024/01/01", has_attachment=True)
        → Busca correos con adjuntos desde enero 2024
    """
    try:
        service = gmail.get_service(user_id)
        
        # Construir query de búsqueda de Gmail
        query_parts = []
        
        if from_email:
            query_parts.append(f"from:{from_email}")
        
        if to_email:
            query_parts.append(f"to:{to_email}")
        
        if subject:
            query_parts.append(f"subject:{subject}")
        
        if content:
            query_parts.append(f"{content}")
        
        if date_after:
            query_parts.append(f"after:{date_after}")
        
        if date_before:
            query_parts.append(f"before:{date_before}")
        
        if has_attachment:
            query_parts.append("has:attachment")
        
        # Combinar todos los criterios
        query = " ".join(query_parts)
        
        if not query:
            return {
                "success": False,
                "error": "No search criteria provided",
                "message": "❌ **Error en búsqueda**\n\nDebes especificar al menos un criterio de búsqueda."
            }
        
        # Ejecutar búsqueda
        results = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results
        ).execute()
        
        messages = results.get("messages", [])
        
        if not messages:
            return {
                "success": True,
                "messages": [],
                "query": query,
                "message": f"📧 **No se encontraron emails**\n\n🔍 **Búsqueda:** `{query}`\n\nNo hay emails que coincidan con estos criterios."
            }
        
        # Obtener detalles de cada mensaje
        detailed_messages = []
        user_message = f"📧 **Encontrados {len(messages)} emails:**\n🔍 **Búsqueda:** `{query}`\n\n"
        
        for i, msg in enumerate(messages, 1):
            try:
                msg_details = service.users().messages().get(
                    userId="me", 
                    id=msg['id'], 
                    format="metadata",
                    metadataHeaders=['Subject', 'From', 'To', 'Date']
                ).execute()
                
                headers = msg_details.get('payload', {}).get('headers', [])
                subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'Sin asunto')
                from_email = next((h['value'] for h in headers if h['name'] == 'From'), 'Desconocido')
                to_email = next((h['value'] for h in headers if h['name'] == 'To'), 'Desconocido')
                date = next((h['value'] for h in headers if h['name'] == 'Date'), 'Fecha desconocida')
                
                # Limpiar nombres de emails
                from_clean = from_email.split('<')[0].strip().strip('"') if '<' in from_email else from_email
                to_clean = to_email.split('<')[0].strip().strip('"') if '<' in to_email else to_email
                
                snippet = msg_details.get('snippet', '')
                
                user_message += f"**{i}. {subject}**\n"
                user_message += f"   📤 **De:** {from_clean}\n"
                user_message += f"   📥 **Para:** {to_clean}\n"
                user_message += f"   📅 **Fecha:** {date[:25]}...\n"
                user_message += f"   💬 **Preview:** {snippet[:80]}...\n"
                user_message += f"   🆔 **ID:** `{msg['id']}`\n\n"
                
                detailed_messages.append({
                    "id": msg['id'],
                    "subject": subject,
                    "from": from_clean,
                    "to": to_clean,
                    "date": date,
                    "snippet": snippet
                })
                
            except Exception as e:
                user_message += f"**{i}. Error obteniendo email**\n   🚫 **Error:** {str(e)}\n\n"
        
        return {
            "success": True,
            "messages": detailed_messages,
            "query": query,
            "raw_messages": messages,
            "message": user_message
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"❌ **Error en búsqueda de emails**\n\n🚫 **Error:** {str(e)}"
        }


def test_connection(user_id: str, **kwargs) -> Dict[str, Any]:
    connect_service = gmail.test_connection(user_id)
    return  connect_service 


# Funciones auxiliares sin cambios
def extract_message_body(payload) -> str:
    """Extrae el cuerpo del mensaje desde el payload de Gmail"""
    body_parts = []
    
    def extract_parts(payload_part):
        if 'parts' in payload_part:
            for part in payload_part['parts']:
                extract_parts(part)
        else:
            mime_type = payload_part.get('mimeType', '')
            if mime_type in ['text/plain', 'text/html']:
                body_data = payload_part.get('body', {}).get('data')
                if body_data:
                    try:
                        decoded_body = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='ignore')
                        if mime_type == 'text/html':
                            decoded_body = html_to_text(decoded_body)
                        if decoded_body.strip():
                            body_parts.append(decoded_body.strip())
                    except Exception as e:
                        print(f"Error decodificando parte: {e}")
    
    extract_parts(payload)
    full_body = '\n\n'.join(body_parts)
    
    if not full_body and payload.get('body', {}).get('data'):
        try:
            data = payload['body']['data']
            full_body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            if payload.get('mimeType') == 'text/html':
                full_body = html_to_text(full_body)
        except Exception as e:
            print(f"Error decodificando mensaje principal: {e}")
    
    return full_body.strip()


def html_to_text(html_content: str) -> str:
    """Convierte HTML a texto plano"""
    if not html_content:
        return ""
    
    html_content = html_content.replace('<br>', '\n').replace('<br/>', '\n').replace('<br />', '\n')
    html_content = html_content.replace('</p>', '\n\n').replace('</div>', '\n')
    html_content = html_content.replace('</h1>', '\n').replace('</h2>', '\n').replace('</h3>', '\n')
    html_content = html_content.replace('</li>', '\n')
    
    link_pattern = r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>'
    html_content = re.sub(link_pattern, r'\2 (\1)', html_content, flags=re.IGNORECASE)
    
    clean = re.compile('<.*?>')
    text = re.sub(clean, '', html_content)
    text = html.unescape(text)
    
    lines = [line.strip() for line in text.split('\n')]
    final_lines = []
    empty_count = 0
    
    for line in lines:
        if line == '':
            empty_count += 1
            if empty_count <= 1:
                final_lines.append(line)
        else:
            empty_count = 0
            final_lines.append(line)
    
    return '\n'.join(final_lines).strip()


GMAIL_TOOL_METHODS = {
    "send_email": {"func": send_email, "description": "Enviar email con Gmail API"},
    "list_emails": {"func": list_emails, "description": "Listar emails de Gmail"},
    "read_email": {"func": read_email, "description": "Leer contenido de un email"},
    "search_emails": {"func": search_emails, "description": "Buscar email por criterio especifico"},
    "test_connection": {"func": test_connection, "description": "Probar conexión con Gmail API"},
}