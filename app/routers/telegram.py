
import logging
from fastapi import APIRouter, Request, HTTPException, Depends
from telegram import Update, Bot
from telegram.constants import ParseMode
from app.config import settings
from app.services.telegram_link import confirm_link_token, generate_link_token
from app.dependencies import get_current_user
from app.models.user import User
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram"])


async def get_bot() -> Bot:
    return Bot(token=settings.TELEGRAM_BOT_TOKEN)


@router.post("/webhook")
async def telegram_webhook(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if secret != settings.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    data = await request.json()
    update = Update.de_json(data, await get_bot())

    if not update.message:
        return {"ok": True}

    text = update.message.text or ""
    chat_id = update.message.chat_id
    username = update.message.from_user.username if update.message.from_user else None
    bot = await get_bot()

    if text.startswith("/start link_"):
        token = text.removeprefix("/start link_").strip()
        success = await confirm_link_token(token, chat_id, username)
        if success:
            await bot.send_message(
                chat_id=chat_id,
                text="✅ *Telegram linked successfully\\!*\n\nYou'll now receive price drop alerts here\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Invalid or expired link. Please generate a new one from your dashboard.",
            )

    elif text.startswith("/start"):
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "👋 Welcome to Nudgemate\\!\n\n"
                "To link your account, go to your dashboard at "
                "[nudgemate\\.net](https://nudgemate.net) "
                "and click *Connect Telegram*\\."
            ),
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    elif text.startswith("/stop"):
        from sqlalchemy import update as sql_update
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await db.execute(
                sql_update(User)
                .where(User.telegram_chat_id == chat_id)
                .values(telegram_chat_id=None, telegram_username=None)
            )
            await db.commit()
        await bot.send_message(
            chat_id=chat_id,
            text="✅ Telegram unlinked. You'll no longer receive alerts here.",
        )

    return {"ok": True}


@router.get("/link-token")
async def get_link_token(request: Request, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    from app.utils.jwt import decode_access_token
    from app.models.user import User

    token = request.cookies.get("nm_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(
        select(User).where(User.id == payload.get("sub"), User.deleted_at == None)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    link_token = generate_link_token(str(user.id))
    bot_username = "NudgemateAlertBot" 

    return {
        "token": link_token,
        "link_url": f"https://t.me/{bot_username}?start=link_{link_token}",
        "expires_in": "10 minutes",
    }
