from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, ARRAY, Text, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime
import uuid
from apps.database import Base

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(500), nullable=True)
    status = Column(String(50), default="active")
    services_used = Column(ARRAY(Text))
    meta_data = Column(JSONB)
    message_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_message_at = Column(DateTime, default=datetime.utcnow)
    archived_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    context = Column(JSON, default=dict)