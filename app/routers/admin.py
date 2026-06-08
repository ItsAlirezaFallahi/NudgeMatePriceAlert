from fastapi import APIRouter, BackgroundTasks
from app.services.scheduler import check_all_prices

router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/trigger-check")
async def trigger_check(background_tasks: BackgroundTasks):
    background_tasks.add_task(check_all_prices)
    return {"status": "check triggered"}
