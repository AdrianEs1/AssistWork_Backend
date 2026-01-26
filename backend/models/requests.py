from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

# Modelos Pydantic para validación
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    user_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    model: Optional[str] = "default"
    conversation_id: Optional[str] = None

class AudioRequest(BaseModel):
    audio_data: str  # Base64 encoded
    user_id: Optional[str] = None
    format: Optional[str] = "wav"
    sample_rate: Optional[int] = 16000