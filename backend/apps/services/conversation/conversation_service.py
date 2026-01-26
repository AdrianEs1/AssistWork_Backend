from sqlalchemy.orm import Session
from apps.models.conversation import Conversation
from apps.models.message import Message
from apps.services.orchestrator.orchestrator_service import orchestrator
from datetime import datetime
from typing import Optional
import uuid
from apps.services.llm.llm_service import call_llm

class ConversationService:
    
    def get_or_create_active_conversation(self, user_id: uuid.UUID, conversation_id, db: Session) -> Conversation:
        if conversation_id:
            conversation = db.query(Conversation).filter_by(
                id=conversation_id, 
                user_id=user_id
            ).first()
            if conversation:
                return conversation
        
        # Crear nueva si no existe o conversation_id es None
        new_conversation = Conversation(
            user_id=user_id,
            title="Nueva conversacion",
            status='active'
        )
        db.add(new_conversation)
        db.commit()
        db.refresh(new_conversation)
        return new_conversation

    
    def save_user_message(
        self, 
        conversation_id: uuid.UUID, 
        content: str, 
        db: Session
    ) -> Message:
        """Guarda un mensaje del usuario"""
        message = Message(
            conversation_id=conversation_id,
            role='user',
            content=content
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        return message
    
    def save_assistant_message(
        self,
        conversation_id: uuid.UUID,
        content: str,
        metadata: Optional[dict] = None,
        db: Session = None
    ) -> Message:
        """Guarda un mensaje del asistente"""
        message = Message(
            conversation_id=conversation_id,
            role='assistant',
            content=content,
            metadata=metadata
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        return message
    

    
    async def update_conversation_title(self, conversation_id: uuid.UUID, first_message: str, user_id: uuid.UUID, db: Session):
        conversation = db.query(Conversation).filter_by(id=conversation_id).first()
        if conversation and conversation.title == "Nueva conversacion":
            title = await self.generate_smart_title(first_message, user_id)
            conversation.title = title
            db.commit()
            db.refresh(conversation)
            print(f"✅ Título actualizado: {title}")
            return title
        return None

        

    async def generate_smart_title(self, first_message: str, user_id: uuid.UUID) -> str:
        """
        Usa el LLM para generar un título corto y descriptivo del primer mensaje.
        Si el modelo no responde, se genera un título genérico basado en el mensaje.
        """
        prompt = (
            "Eres un asistente que genera títulos cortos y claros para conversaciones de chat.\n"
            "Tu tarea es crear un título de no más de 6 palabras basado en el mensaje inicial del usuario.\n\n"
            "Requisitos:\n"
            "- El título debe ser descriptivo y resumir el tema general del mensaje.\n"
            "- No uses emojis, comillas, símbolos, ni puntuación innecesaria.\n"
            "- Usa mayúsculas solo al inicio o en nombres propios.\n"
            "- Evita frases completas o respuestas; usa un estilo tipo 'Consulta sobre factura' o 'Conexión a Gmail'.\n\n"
            f"Mensaje del usuario:\n{first_message}\n\n"
            "Devuelve únicamente el título, sin explicación."
        )

        try:
            result = await call_llm(prompt)
            # Asegura que result tenga formato esperado
            if isinstance(result, str):
                title = result.strip()
            elif isinstance(result, dict):
                title = result.get("message", "").strip()
            else:
                title = ""

            # Si está vacío o None, usa fallback
            if not title:
                title = first_message[:50].strip() or "Nueva conversacion"

            return title[:80]

        except Exception as e:
            print(f"⚠️ Error generando título inteligente: {e}")
            return (first_message[:50].strip() or "Nueva conversacion")


# Singleton
conversation_service = ConversationService() 