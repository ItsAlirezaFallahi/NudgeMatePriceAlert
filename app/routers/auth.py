from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from authlib.integrations.httpx_client import AsyncOAuth2Client
from app.database import get_db
from app.models.user import User
from app.models.event import Event
from app.utils.password import hash_password, verify_password
from app.utils.jwt import create_access_token
from app.config import settings
from pydantic import BaseModel, EmailStr

router = APIRouter(prefix="/auth", tags=["auth"])

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_SCOPES = "openid email profile"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/register", response_model=TokenResponse)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == payload.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    db.add(Event(email=payload.email, event_type="signup", event_metadata={"method": "email"}))
    await db.commit()
    await db.refresh(user)

    return TokenResponse(access_token=create_access_token({"sub": str(user.id)}))


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(User).where(User.email == payload.email, User.deleted_at == None)
    )
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    return TokenResponse(access_token=create_access_token({"sub": str(user.id)}))


@router.get("/google")
async def google_login():
    client = AsyncOAuth2Client(
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scope=GOOGLE_SCOPES,
        redirect_uri=f"{settings.APP_URL}/auth/google/callback",
    )
    uri, _ = client.create_authorization_url(GOOGLE_AUTHORIZE_URL)
    return RedirectResponse(uri)


@router.get("/google/callback")
async def google_callback(code: str, db: AsyncSession = Depends(get_db)):
    client = AsyncOAuth2Client(
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        redirect_uri=f"{settings.APP_URL}/auth/google/callback",
    )

    await client.fetch_token(GOOGLE_TOKEN_URL, code=code)
    resp = await client.get(GOOGLE_USERINFO_URL)
    userinfo = resp.json()

    google_id = userinfo.get("sub")
    email = userinfo.get("email")

    if not google_id or not email:
        raise HTTPException(status_code=400, detail="Could not retrieve Google account info")

    result = await db.execute(
        select(User).where((User.google_id == google_id) | (User.email == email))
    )
    user = result.scalar_one_or_none()

    if user:
        if not user.google_id:
            user.google_id = google_id
            await db.commit()
    else:
        user = User(email=email, google_id=google_id)
        db.add(user)
        db.add(Event(email=email, event_type="signup", event_metadata={"method": "google"}))
        await db.commit()
        await db.refresh(user)

    token = create_access_token({"sub": str(user.id)})
    response = RedirectResponse(f"{settings.APP_URL}/dashboard", status_code=302)
    response.set_cookie("nm_token", token, httponly=True, samesite="lax", max_age=60*60*24*7)
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("nm_token")
    return response
