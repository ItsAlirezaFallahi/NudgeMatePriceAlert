import logging
from twilio.rest import Client
from app.config import settings

logger = logging.getLogger(__name__)

async def send_sms_alert(
    phone_number: str,
    product_name: str,
    current_price,
    target_price,
    affiliate_url: str,
):
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=(
                f"🎯 Price Drop! {product_name[:50]}\n"
                f"Now ${current_price:.2f} (target ${target_price:.2f})\n"
                f"Buy: {affiliate_url}"
            ),
            from_=settings.TWILIO_PHONE_NUMBER,
            to=phone_number,
        )
        logger.info(f"SMS sent to {phone_number}: {message.sid}")
    except Exception as e:
        logger.error(f"SMS error: {e}")
        raise