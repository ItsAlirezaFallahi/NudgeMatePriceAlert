from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from app.config import settings
from app.database import engine
from app.models import User, TrackedItem, PriceHistory, AlertLog, Event
from app.services.scheduler import start_scheduler, scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"Starting {settings.APP_NAME}")
    start_scheduler()
    yield
    scheduler.shutdown()
    await engine.dispose()


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

from app.routers import auth, admin, telegram, items, dashboard
app.include_router(dashboard.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(telegram.router)
app.include_router(items.router)


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME}
