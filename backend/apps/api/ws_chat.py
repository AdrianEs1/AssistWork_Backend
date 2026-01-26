"""
ws_chat.py
WebSocket endpoint para chat en tiempo real con streaming de eventos
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
import json
from datetime import datetime

from apps.database import SessionLocal
#from apps.core.dependencies import get_db
from apps.api.dependencies import get_user_from_token
from apps.models.user import User
from apps.services.orchestrator.orchestrator_service import orchestrator
#from apps.services.conversation_service import conversation_service
from apps.services.conversation.conversation_service import conversation_service
#from apps.services.qdrant_service import search_context, store_message
from apps.services.memory.qdrant_service import store_message, search_context

router = APIRouter()


"""def get_db():
    Dependency para obtener sesión de BD
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()"""


class ConnectionManager:
    """
    Gestiona conexiones WebSocket activas.
    Cada conexión es independiente (no hay broadcast).
    """
    
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        """Acepta conexión y la registra"""
        await websocket.accept()
        self.active_connections[user_id] = websocket
        print(f"✅ WebSocket conectado: user_id={user_id}")
    
    def disconnect(self, user_id: str):
        """Elimina conexión del registro"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            print(f"❌ WebSocket desconectado: user_id={user_id}")
    
    async def send_event(self, user_id: str, event_type: str, data: dict):
        """
        Envía un evento al cliente via WebSocket
        
        Args:
            user_id: ID del usuario
            event_type: Tipo de evento (analyzing, executing, completed, etc.)
            data: Datos del evento
        """
        websocket = self.active_connections.get(user_id)
        if websocket:
            try:
                message = {
                    "type": event_type,
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    **data
                }
                await websocket.send_json(message)
            except Exception as e:
                print(f"⚠️ Error enviando evento a {user_id}: {e}")


# Instancia global del gestor
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token")
):
    """
    WebSocket endpoint para chat con streaming de eventos.
    
    Query params:
        token: JWT access token (desde localStorage del frontend)
    
    Mensajes esperados del cliente:
        {
            "type": "chat",
            "message": "texto del usuario",
            "conversation_id": "uuid-opcional"
        }
    
    Eventos enviados al cliente:
        - analyzing: Analizando petición
        - planning: Planificando secuencia
        - executing: Ejecutando paso X/Y
        - processing: Procesando con LLM
        - saving: Guardando resultados
        - completed: Operación completada
        - error: Error en algún paso
    """
    
    # === 1. Autenticación ===
    db = SessionLocal()  # ← Crear sesión temporal para autenticación
    try:
        current_user: User = await get_user_from_token(token, db)
    except Exception as e:
        db.close()  # ← Cerrar sesión si falla
        await websocket.close(code=1008, reason=f"Autenticación fallida: {str(e)}")
        print(f"❌ Error autenticando WebSocket: {e}")
        return
    finally:
        db.close()  # ← Cerrar sesión después de autenticar
    
    # === 2. Conectar ===
    await manager.connect(websocket, str(current_user.id))
    
    try:
        # === 3. Loop de mensajes ===
        while True:
            # Recibir mensaje del cliente
            data = await websocket.receive_text()
            
            try:
                message_data = json.loads(data)
            except json.JSONDecodeError:
                await manager.send_event(
                    str(current_user.id),
                    "error",
                    {"message": "Formato JSON inválido"}
                )
                continue
            
            # Validar tipo de mensaje
            if message_data.get("type") != "chat":
                await manager.send_event(
                    str(current_user.id),
                    "error",
                    {"message": f"Tipo de mensaje no soportado: {message_data.get('type')}"}
                )
                continue
            
            user_message = message_data.get("message", "").strip()
            conversation_id = message_data.get("conversation_id")
            
            if not user_message:
                await manager.send_event(
                    str(current_user.id),
                    "error",
                    {"message": "El mensaje no puede estar vacío"}
                )
                continue
            
            # === 4. Procesar mensaje ===
            try:
                # ✅ Crear nueva sesión para ESTE mensaje específico
                db = SessionLocal()
                
                try:
                    # 4.1 Obtener o crear conversación
                    conversation = conversation_service.get_or_create_active_conversation(
                        user_id=current_user.id,
                        conversation_id=conversation_id,
                        db=db
                    )
                    
                    # 4.2 Guardar mensaje del usuario
                    user_message_obj = conversation_service.save_user_message(
                        conversation_id=conversation.id,
                        content=user_message,
                        db=db
                    )
                    
                    # 4.3 Actualizar título si es nuevo
                    if conversation.title == "Nueva conversacion":
                        title = await conversation_service.update_conversation_title(
                            conversation_id=conversation.id,
                            first_message=user_message,
                            user_id=current_user.id,
                            db=db
                        )
                        if title:
                            conversation.title = title
                    
                    # 4.4 Buscar contexto
                    context_list = search_context(user_message)
                    context_text = "\n".join(context_list)
                    
                    # 4.5 Definir callback para eventos del orquestador
                    async def event_callback(event_type: str, event_data: dict):
                        """Callback que el orquestador usará para emitir eventos"""
                        await manager.send_event(str(current_user.id), event_type, event_data)
                    
                    # 4.6 Ejecutar orquestador CON callback
                    result = await orchestrator(
                        user_message,
                        user_id=str(current_user.id),
                        context=context_text,
                        event_callback=event_callback
                    )
                    
                    print(f"📊 Resultado orquestador (WS): {result}")
                    
                    # 4.7 Extraer respuesta
                    result_text = result if isinstance(result, str) else result.get("message", str(result))
                    result_metadata = result.get("data", {}) if isinstance(result, dict) else {}
                    
                    # 4.8 Guardar respuesta del agente
                    assistant_message = conversation_service.save_assistant_message(
                        conversation_id=conversation.id,
                        content=result_text,
                        metadata=result_metadata,
                        db=db
                    )
                    
                    # 4.9 Guardar en Qdrant
                    store_message(
                        user_message,
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
                    
                    # 4.10 Refrescar conversación
                    db.refresh(conversation)
                    
                    # 4.11 Enviar evento final
                    await manager.send_event(
                        str(current_user.id),
                        "completed",
                        {
                            "message": result_text,
                            "data": {
                                "conversation_id": str(conversation.id),
                                "title": conversation.title,
                                **result_metadata
                            }
                        }
                    )
                
                finally:
                    # ✅ CRÍTICO: Cerrar sesión después de procesar el mensaje
                    db.close()
                    
            except Exception as e:
                print(f"❌ Error procesando mensaje: {e}")
                await manager.send_event(
                    str(current_user.id),
                    "error",
                    {
                        "message": f"Error procesando tu mensaje: {str(e)}",
                        "error_type": type(e).__name__
                    }
                )
    

    except WebSocketDisconnect:
        print(f"🔌 Cliente desconectado: user_id={current_user.id}")
    except Exception as e:
        print(f"❌ Error en WebSocket: {e}")
    finally:
        manager.disconnect(str(current_user.id))