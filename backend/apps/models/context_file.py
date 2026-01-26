from sqlalchemy import Column, String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid
from apps.database import Base


class ContextFile(Base):
    __tablename__ = "contextfile"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(500), nullable=True)
    mine_type = Column(String(500), nullable=True)
    path =  Column(String(500), nullable=True)