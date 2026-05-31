from sqlalchemy import Column, Numeric, TIMESTAMP, ForeignKey, ARRAY, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.database import Base

class AlertLog(Base):
    __tablename__ = "alerts_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(UUID(as_uuid=True), ForeignKey("tracked_items.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    price_at_alert = Column(Numeric(10, 2), nullable=False)
    channels = Column(ARRAY(Text), nullable=True)
    sent_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    item = relationship("TrackedItem", back_populates="alerts")
    user = relationship("User", back_populates="alerts")
