from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

# Schemas
class ConversationListItem(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    message_count: int
    last_message_at: datetime
    created_at: datetime
    
    class Config:
        from_attributes = True


class MessageItem(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    meta_data: Optional[dict] = None
    
    class Config:
        from_attributes = True


class ConversationDetail(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    message_count: int
    created_at: datetime
    last_message_at: datetime
    messages: List[MessageItem]
    
    class Config:
        from_attributes = True