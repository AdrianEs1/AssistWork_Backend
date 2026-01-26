from sqlalchemy import Column, String, DateTime, Boolean, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
import uuid

from apps.database import Base

class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # 🔐 Nunca guardamos el código en texto plano
    code_hash = Column(String, nullable=False)

    expires_at = Column(DateTime, nullable=False)
    attempts = Column(Integer, default=0)
    used = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


    # relación opcional
    #user = relationship("User", backref="email_verifications")
