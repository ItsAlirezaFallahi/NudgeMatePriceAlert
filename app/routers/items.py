from cmath import asin
import logging
import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.database import get_db, AsyncSessionLocal
from app.dependencies import get_current_user
from app.models.user import User
from app.models.tracked_item import TrackedItem
from app.models.price_history import PriceHistory
from app.models.event import Event
from app.schemas.item import AddItemRequest, ItemResponse, PriceHistoryResponse
from app.services.scraper import scrape_amazon_product
from sqlalchemy.sql import func as sqlfunc
from decimal import Decimal
from app.utils.amazon import extract_asin, resolve_and_extract_asin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/items", tags=["items"])

FREE_TIER_LIMIT = 5
PRO_TIER_LIMIT = 50


async def get_active_item_count(db: AsyncSession, user_id) -> int:
    result = await db.execute(
        select(func.count()).select_from(TrackedItem).where(
            TrackedItem.user_id == user_id,
            TrackedItem.is_active == True,
            TrackedItem.deleted_at == None,
        )
    )
    return result.scalar_one()


async def scrape_and_update(item_id):
    async with AsyncSessionLocal() as db:
        item = await db.get(TrackedItem, item_id)
        if not item or not item.asin:
            return
        url = f"https://www.amazon.com/dp/{item.asin}"

    result = await scrape_amazon_product(url)

    async with AsyncSessionLocal() as db:
        item = await db.get(TrackedItem, item_id)
        if not item:
            return
        if result.success:
            item.product_name = result.product_name
            item.current_price = result.current_price
            item.affiliate_url = result.affiliate_url
            item.last_checked_at = sqlfunc.now()
            if result.current_price:
                db.add(PriceHistory(item_id=item.id, price=result.current_price))
        await db.commit()


@router.post("/", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def add_item(
    payload: AddItemRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if "amazon.com" not in payload.url and "amzn.to" not in payload.url and "amzn.com" not in payload.url:
        raise HTTPException(status_code=400, detail="Only Amazon URLs are supported right now")

    asin = await resolve_and_extract_asin(payload.url)
    if not asin:
        raise HTTPException(status_code=400, detail="Could not find a valid Amazon product in that URL")

    limit = PRO_TIER_LIMIT if current_user.is_pro else FREE_TIER_LIMIT
    count = await get_active_item_count(db, current_user.id)
    if count >= limit:
        raise HTTPException(status_code=403, detail=f"You've reached the {limit}-item limit for your plan")

    dup = await db.execute(
        select(TrackedItem).where(
            TrackedItem.user_id == current_user.id,
            TrackedItem.asin == asin,
            TrackedItem.deleted_at == None,
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="You are already tracking this product")

    if payload.target_price <= 0:
        raise HTTPException(status_code=400, detail="Target price must be greater than zero")

    item = TrackedItem(
        user_id=current_user.id,
        url=payload.url,
        asin=asin,
        target_price=payload.target_price,
    )
    db.add(item)
    db.add(Event(
        user_id=current_user.id,
        email=current_user.email,
        event_type="item_added",
        event_metadata={"asin": asin, "target_price": str(payload.target_price)},
    ))
    await db.commit()
    await db.refresh(item)

    background_tasks.add_task(scrape_and_update, item.id)

    return ItemResponse(
        id=str(item.id),
        url=item.url,
        asin=item.asin,
        product_name=item.product_name,
        current_price=item.current_price,
        target_price=item.target_price,
        affiliate_url=item.affiliate_url,
        is_active=item.is_active,
        last_checked_at=item.last_checked_at,
        created_at=item.created_at,
    )


@router.get("/", response_model=list[ItemResponse])
async def list_items(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TrackedItem)
        .where(TrackedItem.user_id == current_user.id, TrackedItem.deleted_at == None)
        .order_by(TrackedItem.created_at.desc())
    )
    items = result.scalars().all()
    return [
        ItemResponse(
            id=str(i.id), url=i.url, asin=i.asin,
            product_name=i.product_name, current_price=i.current_price,
            target_price=i.target_price, affiliate_url=i.affiliate_url,
            is_active=i.is_active, last_checked_at=i.last_checked_at,
            created_at=i.created_at,
        )
        for i in items
    ]


@router.get("/{item_id}/history", response_model=list[PriceHistoryResponse])
async def get_price_history(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item_result = await db.execute(
        select(TrackedItem).where(
            TrackedItem.id == item_id,
            TrackedItem.user_id == current_user.id,
            TrackedItem.deleted_at == None,
        )
    )
    if not item_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Item not found")

    result = await db.execute(
        select(PriceHistory)
        .where(PriceHistory.item_id == item_id)
        .order_by(PriceHistory.checked_at.desc())
        .limit(100)
    )
    return result.scalars().all()


@router.patch("/{item_id}/pause")
async def pause_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TrackedItem).where(
            TrackedItem.id == item_id,
            TrackedItem.user_id == current_user.id,
            TrackedItem.deleted_at == None,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.is_active = not item.is_active
    await db.commit()
    return {"id": str(item.id), "is_active": item.is_active}


@router.patch("/{item_id}/target")
async def update_target_price(
    item_id: str,
    target_price: Decimal,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TrackedItem).where(
            TrackedItem.id == item_id,
            TrackedItem.user_id == current_user.id,
            TrackedItem.deleted_at == None,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.target_price = target_price
    await db.commit()
    return {"id": str(item.id), "target_price": str(item.target_price)}


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TrackedItem).where(
            TrackedItem.id == item_id,
            TrackedItem.user_id == current_user.id,
            TrackedItem.deleted_at == None,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.deleted_at = sqlfunc.now()
    item.is_active = False
    db.add(Event(
        user_id=current_user.id,
        email=current_user.email,
        event_type="item_deleted",
        event_metadata={"asin": item.asin},
    ))
    await db.commit()
