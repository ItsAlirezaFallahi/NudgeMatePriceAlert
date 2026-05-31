from pydantic import BaseModel
from decimal import Decimal
from datetime import datetime
from typing import Optional

class AddItemRequest(BaseModel):
    url: str
    target_price: Decimal

class ItemResponse(BaseModel):
    id: str
    url: str
    asin: Optional[str]
    product_name: Optional[str]
    current_price: Optional[Decimal]
    target_price: Decimal
    affiliate_url: Optional[str]
    is_active: bool
    last_checked_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

class PriceHistoryResponse(BaseModel):
    price: Decimal
    checked_at: datetime

    class Config:
        from_attributes = True
