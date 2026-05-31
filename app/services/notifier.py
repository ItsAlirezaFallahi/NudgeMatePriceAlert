import logging
import resend
from decimal import Decimal
from jinja2 import Environment, FileSystemLoader
from app.config import settings
from app.models.user import User
from app.models.tracked_item import TrackedItem

logger = logging.getLogger(__name__)

jinja_env = Environment(
    loader=FileSystemLoader("app/templates"),
    autoescape=True,
)

resend.api_key = settings.RESEND_API_KEY

async def send_price_alert(
    user,
    item,
    current_price,
):
    import asyncio
    tasks = []

    if user.notify_email:
        tasks.append(
            send_email_alert(
                to_email=user.email,
                product_name=item.product_name or "Your tracked item",
                current_price=current_price,
                target_price=item.target_price,
                affiliate_url=item.affiliate_url or item.url,
            )
        )

    if user.notify_telegram and user.telegram_chat_id:
        tasks.append(
            send_telegram_alert(
                chat_id=user.telegram_chat_id,
                product_name=item.product_name or "Your tracked item",
                current_price=current_price,
                target_price=item.target_price,
                affiliate_url=item.affiliate_url or item.url,
            )
        )

    if user.is_pro and user.notify_sms and user.phone_number and user.phone_verified:
        from app.services.sms import send_sms_alert
        tasks.append(
            send_sms_alert(
                phone_number=user.phone_number,
                product_name=item.product_name or "Your tracked item",
                current_price=current_price,
                target_price=item.target_price,
                affiliate_url=item.affiliate_url or item.url,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Alert failed: {result}")


async def send_email_alert(
    to_email: str,
    product_name: str,
    current_price: Decimal,
    target_price: Decimal,
    affiliate_url: str,
):
    template = jinja_env.get_template("email_alert.html")
    html = template.render(
        product_name=product_name,
        current_price=f"{current_price:.2f}",
        target_price=f"{target_price:.2f}",
        affiliate_url=affiliate_url,
    )

    try:
        resend.Emails.send({
            "from": f"Nudgemate <{settings.FROM_EMAIL}>",
            "to": [to_email],
            "subject": f"Price Drop: {product_name[:60]}",
            "html": html,
        })
        logger.info(f"Email alert sent to {to_email}")
    except Exception as e:
        logger.error(f"Resend error: {e}")
        raise


async def send_telegram_alert(
    chat_id: int,
    product_name: str,
    current_price: Decimal,
    target_price: Decimal,
    affiliate_url: str,
):
    from telegram import Bot

    savings = target_price - current_price

    message = (
        f"🎯 Price Drop Alert!\n\n"
        f"{product_name[:100]}\n\n"
        f"💰 Current price: ${current_price:.2f}\n"
        f"🎯 Your target: ${target_price:.2f}\n"
        f"✅ You save: ${savings:.2f}\n\n"
        f"Buy Now: {affiliate_url}"
    )

    try:
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=chat_id,
            text=message,
        )
        logger.info(f"Telegram alert sent to chat_id {chat_id}")
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        raise


def escape_markdown(text: str) -> str:
    special = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    result = ""
    for c in text:
        if c in special:
            result += f"\\{c}"
        else:
            result += c
    return result