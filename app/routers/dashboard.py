from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db, AsyncSessionLocal
from app.models.user import User
from app.models.tracked_item import TrackedItem
from app.models.price_history import PriceHistory
from app.models.event import Event
from app.utils.jwt import decode_access_token
from app.utils.amazon import extract_asin
from app.services.scraper import scrape_amazon_product
from decimal import Decimal
import asyncio

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")

FREE_TIER_LIMIT = 5
PRO_TIER_LIMIT = 50


async def get_user_from_cookie(request: Request, db: AsyncSession) -> User | None:
    token = request.cookies.get("nm_token")
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    result = await db.execute(
        select(User).where(User.id == payload.get("sub"), User.deleted_at == None)
    )
    return result.scalar_one_or_none()


async def scrape_and_update_bg(item_id):
    from sqlalchemy.sql import func as sqlfunc
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


# --- Pages ---

@router.get("/", response_class=HTMLResponse)
async def landing(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("index.html", context={"request": request, "current_user": None})


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("auth.html", context={
        "request": request, "mode": "login", "current_user": None,
    })


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("auth.html", context={
        "request": request, "mode": "register", "current_user": None,
    })


@router.post("/auth/login")
async def web_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from app.utils.password import verify_password
    from app.utils.jwt import create_access_token

    result = await db.execute(
        select(User).where(User.email == email, User.deleted_at == None)
    )
    user = result.scalar_one_or_none()

    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        return templates.TemplateResponse("auth.html", context={
            "request": request, "mode": "login",
            "error": "Invalid email or password", "current_user": None,
        })

    token = create_access_token({"sub": str(user.id)})
    response = RedirectResponse("/dashboard", status_code=302)
    response.set_cookie("nm_token", token, httponly=True, samesite="lax", max_age=60*60*24*7)
    return response


@router.post("/auth/register")
async def web_register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from app.utils.password import hash_password
    from app.utils.jwt import create_access_token

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        return templates.TemplateResponse("auth.html", context={
            "request": request, "mode": "register",
            "error": "Email already registered", "current_user": None,
        })

    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.add(Event(email=email, event_type="signup", event_metadata={"method": "email"}))
    await db.commit()
    await db.refresh(user)

    token = create_access_token({"sub": str(user.id)})
    response = RedirectResponse("/dashboard", status_code=302)
    response.set_cookie("nm_token", token, httponly=True, samesite="lax", max_age=60*60*24*7)
    return response


@router.get("/auth/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("nm_token")
    return response


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    result = await db.execute(
        select(TrackedItem)
        .where(TrackedItem.user_id == user.id, TrackedItem.deleted_at == None)
        .order_by(TrackedItem.created_at.desc())
    )
    items = result.scalars().all()
    limit = PRO_TIER_LIMIT if user.is_pro else FREE_TIER_LIMIT

    return templates.TemplateResponse("dashboard.html", context={
        "request": request,
        "current_user": user,
        "items": items,
        "limit": limit,
        "is_pro": user.is_pro,
    })


@router.get("/items/add", response_class=HTMLResponse)
async def add_item_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("add_item.html", context={
        "request": request, "current_user": user,
    })


@router.post("/items/add")
async def add_item_web(
    request: Request,
    url: str = Form(...),
    target_price: Decimal = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    def render_error(msg):
        return templates.TemplateResponse("add_item.html", context={
            "request": request, "current_user": user,
            "error": msg, "url": url, "target_price": target_price,
        })

    if "amazon.com" not in url:
        return render_error("Only Amazon URLs are supported right now")

    asin = extract_asin(url)
    if not asin:
        return render_error("Could not find a valid Amazon product in that URL")

    count_result = await db.execute(
        select(func.count()).select_from(TrackedItem).where(
            TrackedItem.user_id == user.id,
            TrackedItem.is_active == True,
            TrackedItem.deleted_at == None,
        )
    )
    count = count_result.scalar_one()
    limit = PRO_TIER_LIMIT if user.is_pro else FREE_TIER_LIMIT
    if count >= limit:
        return render_error(f"You've reached the {limit}-item limit for your plan")

    dup = await db.execute(
        select(TrackedItem).where(
            TrackedItem.user_id == user.id,
            TrackedItem.asin == asin,
            TrackedItem.deleted_at == None,
        )
    )
    if dup.scalar_one_or_none():
        return render_error("You're already tracking this product")

    item = TrackedItem(
        user_id=user.id, url=url, asin=asin, target_price=target_price,
    )
    db.add(item)
    db.add(Event(user_id=user.id, email=user.email, event_type="item_added", event_metadata={"asin": asin}))
    await db.commit()
    await db.refresh(item)

    asyncio.create_task(scrape_and_update_bg(item.id))

    return RedirectResponse("/dashboard", status_code=302)


@router.get("/items/{item_id}", response_class=HTMLResponse)
async def item_detail(item_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    result = await db.execute(
        select(TrackedItem).where(
            TrackedItem.id == item_id,
            TrackedItem.user_id == user.id,
            TrackedItem.deleted_at == None,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        return RedirectResponse("/dashboard", status_code=302)

    history_result = await db.execute(
        select(PriceHistory)
        .where(PriceHistory.item_id == item_id)
        .order_by(PriceHistory.checked_at.asc())
        .limit(100)
    )
    history = history_result.scalars().all()
    lowest = min((h.price for h in history), default=None)

    return templates.TemplateResponse("item_detail.html", context={
        "request": request,
        "current_user": user,
        "item": item,
        "history": history,
        "lowest": lowest,
        "history_dates": [h.checked_at.strftime("%b %d %H:%M") for h in history],
        "history_prices": [float(h.price) for h in history],
    })


@router.post("/items/{item_id}/pause")
async def pause_item_web(item_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    result = await db.execute(
        select(TrackedItem).where(
            TrackedItem.id == item_id,
            TrackedItem.user_id == user.id,
            TrackedItem.deleted_at == None,
        )
    )
    item = result.scalar_one_or_none()
    if item:
        item.is_active = not item.is_active
        await db.commit()

    return RedirectResponse("/dashboard", status_code=302)


@router.post("/items/{item_id}/delete")
async def delete_item_web(item_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    from sqlalchemy.sql import func
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    result = await db.execute(
        select(TrackedItem).where(
            TrackedItem.id == item_id,
            TrackedItem.user_id == user.id,
            TrackedItem.deleted_at == None,
        )
    )
    item = result.scalar_one_or_none()
    if item:
        item.deleted_at = func.now()
        item.is_active = False
        await db.commit()

    return RedirectResponse("/dashboard", status_code=302)


@router.post("/items/{item_id}/target")
async def update_target_web(
    item_id: str,
    request: Request,
    target_price: Decimal = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    result = await db.execute(
        select(TrackedItem).where(
            TrackedItem.id == item_id,
            TrackedItem.user_id == user.id,
            TrackedItem.deleted_at == None,
        )
    )
    item = result.scalar_one_or_none()
    if item:
        item.target_price = target_price
        await db.commit()

    return RedirectResponse(f"/items/{item_id}", status_code=302)


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("settings.html", context={
        "request": request, "current_user": user,
    })


@router.post("/settings/telegram/unlink")
async def unlink_telegram(request: Request, db: AsyncSession = Depends(get_db)):
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    user.telegram_chat_id = None
    user.telegram_username = None
    await db.commit()
    return RedirectResponse("/settings", status_code=302)


@router.post("/settings/delete-account")
async def delete_account(request: Request, db: AsyncSession = Depends(get_db)):
    from sqlalchemy.sql import func
    user = await get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    user.deleted_at = func.now()
    await db.commit()
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("nm_token")
    return response
