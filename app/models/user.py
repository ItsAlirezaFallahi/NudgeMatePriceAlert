from sqlalchemy import Column, Text, Boolean, BigInteger, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text, nullable=True)
    google_id = Column(Text, unique=True, nullable=True)
    telegram_chat_id = Column(BigInteger, unique=True, nullable=True)
    telegram_username = Column(Text, nullable=True)
    is_pro = Column(Boolean, default=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    deleted_at = Column(TIMESTAMP(timezone=True), nullable=True)

    items = relationship("TrackedItem", back_populates="user")
    alerts = relationship("AlertLog", back_populates="user")
    events = relationship("Event", back_populates="user")

    notify_email = Column(Boolean, default=True)
    notify_telegram = Column(Boolean, default=True)
    notify_sms = Column(Boolean, default=False)
    phone_number = Column(Text, nullable=True)
    phone_verified = Column(Boolean, default=False)
