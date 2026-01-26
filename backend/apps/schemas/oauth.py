from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

# Response schemas
class OAuthConnectionResponse(BaseModel):
    id: uuid.UUID
    service: str
    service_user_id: Optional[str]
    is_active: bool
    connected_at: datetime
    last_used_at: Optional[datetime]
    meta_data: Optional[dict]
    
    class Config:
        from_attributes = True

class OAuthConnectResponse(BaseModel):
    authorization_url: Optional[str] = None
    state: Optional[str] = None
    status: Optional[str] = None
    message: Optional[str] = None

class OAuthCallbackResponse(BaseModel):
    success: bool
    message: str
    service: str
    email: Optional[str]