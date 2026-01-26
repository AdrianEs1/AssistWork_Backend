from fastapi import APIRouter,Depends
import base64
from io import BytesIO
from sqlalchemy.orm import Session

# Importar modelos Pydantic desde models/
from models.requests import ChatRequest
from models.responses import ModelResponse, AudioResponse

# Importar servicios
from apps.services.text_speach.stt_service import connect_deepgram_stream, speech_to_text
from apps.services.text_speach.tts_service import text_to_speech
from apps.services.memory.qdrant_service import store_message, search_context
from apps.services.orchestrator.orchestrator_service import orchestrator

from apps.services.conversation.conversation_service import conversation_service  # ✅ Nuevo
from apps.core.dependencies import get_current_user, get_db  # ✅ Nuevo
from apps.models.user import User  # ✅ Nuevo

router = APIRouter()

# ---------------------
# Endpoint de texto
# ---------------------
@router.post("/ask", response_model=ModelResponse)
async def call_model(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),  # ✅ Requiere autenticación
    db: Session = Depends(get_db)  # ✅ Sesión de BD
):
    # 1. Obtener o crear conversación activa
    conversation = conversation_service.get_or_create_active_conversation(
        user_id=current_user.id,
        conversation_id= request.conversation_id,
        db=db
    )
    
    # 2. Guardar mensaje del usuario en BD
    user_message = conversation_service.save_user_message(
        conversation_id=conversation.id,
        content=request.message,
        db=db
    )
    
    """# 3. Actualizar título si es el primer mensaje
    if conversation.message_count == 1:  # El trigger ya incrementó a 1
        conversation_service.update_conversation_title(
            conversation_id=conversation.id,
            first_message=request.message,
            db=db
        )"""
    # 3. Actualizar título si es el primer mensaje
    if conversation.title == "Nueva conversacion":
        title= await conversation_service.update_conversation_title(
            conversation_id=conversation.id,
            first_message=request.message,
            user_id=current_user.id,  # ✅ nuevo argumento
            db=db
        )
        if title:
            conversation.title = title
    
    
    # 4. TU LÓGICA ACTUAL (sin cambios)
    context_list = search_context(request.message)
    context_text = "\n".join(context_list)
    
    result = await orchestrator(request.message, user_id=str(current_user.id),context=context_text)
    print(f"Respuesta del orquestador: {result}")
    
    # 5. Guardar respuesta del agente en BD
    # Extraer metadata si tu orchestrator la retorna
    result_text = result if isinstance(result, str) else result.get("message", str(result))
    result_metadata = result.get("metadata", {}) if isinstance(result, dict) else {}
    
    assistant_message = conversation_service.save_assistant_message(
        conversation_id=conversation.id,
        content=result_text,
        metadata=result_metadata,
        db=db
    )
    
    # 6. Guardar en Qdrant (como haces ahora)
    store_message(
        request.message, 
        metadata={
            "role": "user", 
            "conversation_id": str(conversation.id),
            "user_id": str(current_user.id)
        }
    )
    store_message(
        result_text, 
        metadata={
            "role": "assistant", 
            "conversation_id": str(conversation.id),
            "user_id": str(current_user.id)
        }
    )
    
    # ✅ 7. Asegurar que tenemos el título más reciente
    db.refresh(conversation)

    return ModelResponse(
        success=True, 
        message=result_text,
        conversation_id=conversation.id,
        title= conversation.title
    )
