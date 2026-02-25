from sqlalchemy import Column, String, ForeignKey, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID
import uuid
from apps.database import Base
from datetime import datetime


class ContextFile(Base):
    __tablename__ = "contextfile"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=False)  # ← Corregido (antes: mine_type)
    file_size = Column(Integer, nullable=False)       # ← NUEVO
    gcs_path = Column(String(500), nullable=False)    # ← NUEVO
    file_hash = Column(String(64), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)  # ← NUEVO
    
    # path = Column(String(500))  # ← ELIMINAR