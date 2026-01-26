from fastapi import APIRouter, Depends, HTTPException, status, Query 
from sqlalchemy.orm import Session
from sqlalchemy import desc, or_
from apps.core.dependencies import get_db, get_current_user
from apps.models.user import User
from apps.models.conversation import Conversation
from apps.models.message import Message
from typing import List, Optional, Literal
from pydantic import BaseModel
from datetime import datetime
import uuid
from apps.schemas.conversation import ConversationListItem, ConversationDetail

router = APIRouter(prefix="/conversations", tags=["Conversations"])


# Endpoints
@router.get("", response_model=List[ConversationListItem])
async def list_conversations(
    status: Literal["active", "archived", "all"] = Query("active"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session =Depends(get_db),
):
    """
    Lista las conversaciones del usuario.
    - active (default)
    - archived
    - all
    """
    query = (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
    )

    if status != "all":
        query = query.filter(Conversation.status == status)

    conversations = (
        query
        .order_by(desc(Conversation.last_message_at))
        .limit(limit)
        .offset(offset)
        .all()
    )

    return conversations


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
): 
    """
    Obtiene una conversación específica con todos sus mensajes
    """
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id
    ).first()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversación no encontrada"
        )
    
    # Obtener mensajes
    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.created_at).all()
    
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        status=conversation.status,
        message_count=conversation.message_count,
        created_at=conversation.created_at,
        last_message_at=conversation.last_message_at,
        messages=messages
    )


@router.post("", response_model=ConversationListItem)
async def create_conversation(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Crea una nueva conversación manualmente (botón Nueva Tarea)
    """
    new_conversation = Conversation(
        user_id=current_user.id,
        title="Nueva conversacióneeeees",
        status='active'
    )
    db.add(new_conversation)
    db.commit()
    db.refresh(new_conversation)
    
    return new_conversation


@router.post("/{conversation_id}/archive")
async def archive_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Archiva una conversación
    """
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id
    ).first()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversación no encontrada"
        )

    if conversation.status == "archived":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La conversación ya está archivada"
        )
    
    conversation.status = 'archived'
    conversation.archived_at = datetime.utcnow() 
    db.commit()
    
    return {"success": True, "message": "Conversación archivada"}


@router.delete("/{conversation_id}/delete-permanent")
async def delete_conversation_permanently(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Elimina una conversación definitivamente
    """
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id
    ).first()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversación no encontrada"
        )

    # ⚠️ Eliminación definitiva
    db.delete(conversation)
    db.commit()

    return {
        "success": True,
        "message": "Conversación eliminada permanentemente"
    }



@router.get("/search", response_model=List[ConversationListItem])
async def search_conversations(
    q: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Busca conversaciones por título o contenido de mensajes
    """
    # Buscar en títulos
    conversations = db.query(Conversation).filter(
        Conversation.user_id == current_user.id,
        Conversation.title.ilike(f"%{q}%")
    ).order_by(desc(Conversation.last_message_at)).limit(20).all()
    
    return conversations


@router.get("/archived")
def get_archived_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):  
    """Obtiene Conversaciones Archivadas"""
    return db.query(Conversation).filter(
        Conversation.user_id == current_user.id,
        Conversation.status == "archived"
    ).order_by(Conversation.archived_at.desc()).all()



@router.patch("/{conversation_id}/restore")
def restore_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Permite desarchivar una conversacion"""
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id,
        Conversation.status == "archived"
    ).first()

    if not conversation:
        raise HTTPException(404, "Conversación no encontrada o no archivada")

    conversation.status = "active"
    conversation.archived_at = None
    db.commit()

    return {"message": "Conversación restaurada"}

