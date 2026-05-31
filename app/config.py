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
    SCRAPER_API_KEY: str = "dda74f5797b4e129896b92f95492efde"

    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
