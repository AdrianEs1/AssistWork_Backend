from typing import Optional, Dict, Any, Union
from pydantic import BaseModel
import uuid

class ModelResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    message: Optional[Union[str, Dict[str, Any]]] = None  # <- ahora acepta dict también
    error: Optional[str] = None
    conversation_id: Optional[uuid.UUID] = None  # ✅ Agregar esto
    title: Optional[str] = None

class AudioResponse(BaseModel):
    transcription: str
    message: str
    audio_base64: str
    conversation_id: Optional[uuid.UUID] = None  # ✅ Agregar esto