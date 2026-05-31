from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str
    APP_URL: str
    SECRET_KEY: str

    DATABASE_URL: str

    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str

    RESEND_API_KEY: str
    FROM_EMAIL: str

    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_WEBHOOK_SECRET: str

    AMAZON_AFFILIATE_TAG: str
    PRICE_CHECK_INTERVAL_HOURS: int = 3

    class Config:
        env_file = ".env"

settings = Settings()
