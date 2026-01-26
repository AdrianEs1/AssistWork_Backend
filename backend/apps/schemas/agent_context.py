from pydantic import BaseModel
from typing import List, Optional


class DriveFileInput(BaseModel):
    id: str
    name: Optional[str] = None
    mime_type: Optional[str] = None


class ConversationFilesInput(BaseModel):
    conversation_id: str
    files: List[DriveFileInput]
