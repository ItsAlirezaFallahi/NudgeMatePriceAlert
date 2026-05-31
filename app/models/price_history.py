from sqlalchemy import Column, Numeric, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.database import Base

class PriceHistory(Base):
    __tablename__ = "price_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(UUID(as_uuid=True), ForeignKey("tracked_items.id"), nullable=False)
    price = Column(Numeric(10, 2), nullable=False)
    checked_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    item = relationship("TrackedItem", back_populates="price_history")
