from pydantic import BaseModel
from typing import List, Optional
import uuid


class DriveFileInput(BaseModel):
    id: str
    name: Optional[str] = None
    mime_type: Optional[str] = None


class ConversationFilesInput(BaseModel):
    conversation_id: str
    files: List[DriveFileInput]

class FilesUploaded(BaseModel):
    id: uuid.UUID
    name: Optional [str]

    class Config:
        from_attributes = True

class FilesDetail(BaseModel):
    file: List[FilesUploaded] = []
