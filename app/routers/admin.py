from fastapi import APIRouter, Depends
from app.dependencies import get_current_user
from app.models.user import User
from app.services.scheduler import check_all_prices

router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/trigger-check")
async def trigger_check(current_user: User = Depends(get_current_user)):
    await check_all_prices()
    return {"status": "check triggered"}
