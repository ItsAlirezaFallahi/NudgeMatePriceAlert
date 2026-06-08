import asyncio
import logging
from decimal import Decimal
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.database import AsyncSessionLocal
from app.models.tracked_item import TrackedItem
from app.models.price_history import PriceHistory
from app.models.alert_log import AlertLog
from app.services.scraper import scrape_product
from app.services.notifier import send_price_alert
from app.config import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def start_scheduler():
    scheduler.add_job(
        check_all_prices,
        trigger=IntervalTrigger(hours=settings.PRICE_CHECK_INTERVAL_HOURS),
        id="price_check",
        name="Check all tracked prices",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info(f"Scheduler started — price checks every {settings.PRICE_CHECK_INTERVAL_HOURS} hours")


async def check_all_prices():
    logger.info("Starting price check run")

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(TrackedItem)
            .where(
                TrackedItem.is_active == True,
                TrackedItem.deleted_at == None,
            )
            .options(selectinload(TrackedItem.user))
        )
        items = result.scalars().all()

    logger.info(f"Checking {len(items)} tracked items")

    for item in items:
        await check_single_item(item)
        await asyncio.sleep(5)

    logger.info("Price check run complete")


async def check_single_item(item: TrackedItem):
    logger.info(f"Checking item {item.id} — ASIN {item.asin}")

    result = await scrape_product(item.url)

    async with AsyncSessionLocal() as db:
        db_item = await db.get(TrackedItem, item.id)
        if not db_item:
            return

        if not result.success or result.current_price is None:
            logger.warning(f"Scrape failed for item {item.id}: {result.error}")
            from sqlalchemy.sql import func
            db_item.last_checked_at = func.now()
            await db.commit()
            return

        new_price = result.current_price

        history = PriceHistory(item_id=db_item.id, price=new_price)
        db.add(history)

        db_item.current_price = new_price
        db_item.product_name = result.product_name or db_item.product_name
        db_item.affiliate_url = result.affiliate_url or db_item.affiliate_url
        from sqlalchemy.sql import func
        db_item.last_checked_at = func.now()

        should_alert = should_send_alert(
            current_price=new_price,
            target_price=db_item.target_price,
            last_alert_price=db_item.last_alert_price,
        )

        await db.commit()

        if should_alert:
            logger.info(
                f"Price drop detected for item {item.id}: {new_price} (target: {db_item.target_price})"
            )
            await trigger_alert(db_item, new_price)


MEANINGFUL_DROP_THRESHOLD = 0.05  # 5%

def should_send_alert(current_price: Decimal, target_price: Decimal, last_alert_price: Decimal | None) -> bool:
    # Price not below target — no alert
    if current_price > target_price:
        return False

    # Never alerted before — alert
    if last_alert_price is None:
        return True

    # Last alert was above target — price dropped below again — alert
    if last_alert_price > target_price:
        return True

    # Price dropped 5%+ from last alert price — alert
    drop_pct = (last_alert_price - current_price) / last_alert_price
    if drop_pct >= MEANINGFUL_DROP_THRESHOLD:
        return True

    return False


async def trigger_alert(item: TrackedItem, price: Decimal):
    user = item.user
    channels_used = []

    try:
        await send_price_alert(user=user, item=item, current_price=price)
        channels_used = ["email"]
        if user.telegram_chat_id and user.notify_telegram:
            channels_used.append("telegram")
    except Exception as e:
        logger.error(f"Failed to send alert for item {item.id}: {e}")
        return

    async with AsyncSessionLocal() as db:
        db_item = await db.get(TrackedItem, item.id)
        if db_item:
            db_item.last_alert_price = price

        alert = AlertLog(
            item_id=item.id,
            user_id=user.id,
            price_at_alert=price,
            channels=channels_used,
        )
        db.add(alert)
        await db.commit()
