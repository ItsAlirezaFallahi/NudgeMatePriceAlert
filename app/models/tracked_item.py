from sqlalchemy import Column, Text, Boolean, Numeric, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.database import Base

class TrackedItem(Base):
    __tablename__ = "tracked_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    url = Column(Text, nullable=False)
    asin = Column(Text, nullable=True)
    product_name = Column(Text, nullable=True)
    current_price = Column(Numeric(10, 2), nullable=True)
    target_price = Column(Numeric(10, 2), nullable=False)
    affiliate_url = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    last_checked_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    deleted_at = Column(TIMESTAMP(timezone=True), nullable=True)

    user = relationship("User", back_populates="items")
    price_history = relationship("PriceHistory", back_populates="item")
    alerts = relationship("AlertLog", back_populates="item")
