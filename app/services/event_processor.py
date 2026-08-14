

import logging

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db_session
from app.models import DmJob, Rule

logger = logging.getLogger(__name__)


async def update_stat(key: str, delta: int = 1):
    
    async with get_db_session() as db:
        await db.execute(
            text("UPDATE stats_counters SET value = value + :delta WHERE key = :key"),
            {"key": key, "delta": delta},
        )


async def find_matching_rules(comment_text: str, db: AsyncSession) -> list[Rule]:
    
    result = await db.execute(select(Rule))
    all_rules = result.scalars().all()

    comment_lower = comment_text.lower()
    return [rule for rule in all_rules if rule.keyword.lower() in comment_lower]


async def create_dm_job(
    user_id: str,
    username: str | None,
    rule_id: str,
    comment_id: str,
    dm_message: str,
    db: AsyncSession,
) -> bool:
    
    idempotency_key = f"{user_id}:{rule_id}"

    try:
        async with db.begin_nested():
            job = DmJob(
                user_id=user_id,
                username=username,
                rule_id=rule_id,
                comment_id=comment_id,
                dm_message=dm_message,
                idempotency_key=idempotency_key,
                status="pending",
            )
            db.add(job)
            await db.flush()

        logger.info(
            f"DM job created | user_id={user_id} rule_id={rule_id} comment_id={comment_id}"
        )
        return True

    except IntegrityError:
        logger.info(f"Duplicate blocked | user_id={user_id} rule_id={rule_id}")
        return False


async def process_comment_event(event_data: dict):
    
    comment_text = event_data.get("text", "")
    comment_id = event_data.get("comment_id", "")
    user_info = event_data.get("from", {})
    user_id = user_info.get("user_id", "")
    username = user_info.get("username", "")

    if not comment_text or not user_id or not comment_id:
        logger.warning("Invalid comment.created event data")
        return

    async with get_db_session() as db:
        matched_rules = await find_matching_rules(comment_text, db)

        if not matched_rules:
            logger.info(f"No rule matched | user_id={user_id} comment_id={comment_id}")
            return

        for rule in matched_rules:
            created = await create_dm_job(
                user_id=user_id,
                username=username,
                rule_id=rule.rule_id,
                comment_id=comment_id,
                dm_message=rule.dm_message,
                db=db,
            )

            if created:
                await update_stat("queued", 1)
            else:
                await update_stat("duplicates_blocked", 1)


async def process_comment_deleted(event_data: dict):
    
    comment_id = event_data.get("comment_id", "")
    if not comment_id:
        logger.warning("comment.deleted missing comment_id")
        return

    cancelled_count = 0

    async with get_db_session() as db:
        result = await db.execute(
            select(DmJob).where(
                DmJob.comment_id == comment_id,
                DmJob.status == "pending",
            )
        )
        jobs = result.scalars().all()

        for job in jobs:
            job.status = "cancelled"
            cancelled_count += 1
            logger.info(f"Cancelled pending DM job | job_id={job.job_id} comment_id={comment_id}")

        await db.flush()

    for _ in range(cancelled_count):
        await update_stat("queued", -1)