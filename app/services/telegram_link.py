import secrets
import logging
from datetime import datetime, timedelta
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.user import User

logger = logging.getLogger(__name__)

_link_tokens: dict = {}


def generate_link_token(user_id: str) -> str:
    token = secrets.token_urlsafe(16)
    _link_tokens[token] = {
        "user_id": user_id,
        "expires_at": datetime.utcnow() + timedelta(minutes=10),
    }
    return token


async def confirm_link_token(token: str, chat_id: int, username: str | None) -> bool:
    entry = _link_tokens.get(token)
    if not entry:
        return False

    if datetime.utcnow() > entry["expires_at"]:
        del _link_tokens[token]
        return False

    user_id = entry["user_id"]

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.id == user_id, User.deleted_at == None)
        )
        user = result.scalar_one_or_none()
        if not user:
            return False

        user.telegram_chat_id = chat_id
        user.telegram_username = username
        await db.commit()

    del _link_tokens[token]
    logger.info(f"Telegram linked for user {user_id} — chat_id {chat_id}")
    return True
