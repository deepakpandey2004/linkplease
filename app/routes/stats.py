import logging

from fastapi import APIRouter
from sqlalchemy import select

from app.database import get_db_session
from app.models import StatsCounter
from app.schemas import StatsResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """
    Return live statistics.
    """
    async with get_db_session() as db:
        result = await db.execute(select(StatsCounter))
        rows = result.scalars().all()

        stats = {row.key: row.value for row in rows}

        return StatsResponse(
            sent=stats.get("sent", 0),
            failed=stats.get("failed", 0),
            queued=stats.get("queued", 0),
            duplicates_blocked=stats.get("duplicates_blocked", 0),
        )