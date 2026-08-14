
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.database import get_db_session
from app.models import DmJob
from app.services.dm_sender import check_rate_limit, record_send_attempt, send_dm
from app.services.event_processor import update_stat

logger = logging.getLogger(__name__)

DM_WORKER_SLEEP_SECONDS = 1


async def claim_next_dm_job() -> DmJob | None:
    
    async with get_db_session() as db:
        stmt = (
            select(DmJob)
            .where(
                DmJob.status == "pending",
                or_(
                    DmJob.next_retry_at.is_(None),
                    DmJob.next_retry_at <= datetime.now(timezone.utc),
                ),
            )
            .order_by(DmJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )

        result = await db.execute(stmt)
        job = result.scalar_one_or_none()

        if not job:
            return None

        job.status = "sending"
        await db.flush()

        return job


async def mark_job_accepted(job_id: str, dm_id: str):
    
    async with get_db_session() as db:
        job = await db.get(DmJob, job_id)
        if not job:
            return

        job.status = "accepted"
        job.dm_id = dm_id
        job.updated_at = datetime.now(timezone.utc)
        await db.flush()


async def mark_job_failed(job_id: str, error_message: str):
    
    async with get_db_session() as db:
        job = await db.get(DmJob, job_id)
        if not job:
            return

        job.status = "failed"
        job.error_message = error_message
        job.updated_at = datetime.now(timezone.utc)
        await db.flush()

    # Update stats
    await update_stat("queued", -1)
    await update_stat("failed", 1)
    logger.error(f"DM job permanently failed | job_id={job_id} error={error_message}")


async def mark_job_for_retry(job_id: str, error_message: str, retry_after: float = 0.0):
    
    async with get_db_session() as db:
        job = await db.get(DmJob, job_id)
        if not job:
            return

        job.retry_count += 1
        job.error_message = error_message

        if job.retry_count >= job.max_retries:
            # Max retries hit — give up
            job.status = "failed"
            job.updated_at = datetime.now(timezone.utc)
            await db.flush()

            await update_stat("queued", -1)
            await update_stat("failed", 1)
            logger.error(
                f"DM job max retries exceeded | job_id={job_id} retries={job.retry_count}"
            )
            return

        # Calculate wait time
        if retry_after > 0:
            wait_seconds = retry_after
        else:
            # Exponential backoff: 2, 4, 8, 16, 32 seconds
            wait_seconds = 2 ** job.retry_count

        job.status = "pending"
        job.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=wait_seconds)
        job.updated_at = datetime.now(timezone.utc)
        await db.flush()

        logger.warning(
            f"DM job retry scheduled | job_id={job_id} "
            f"retry={job.retry_count} wait={wait_seconds}s"
        )


async def process_dm_job(job: DmJob):
    
    # Step 1: Check rate limit
    wait_seconds = await check_rate_limit()
    if wait_seconds > 0:
        logger.info(f"Rate limit reached, waiting {wait_seconds:.1f}s | job_id={job.job_id}")
        await asyncio.sleep(wait_seconds)

    # Step 2: Record this attempt for rate limit tracking
    await record_send_attempt()

    # Step 3: Send DM
    result = await send_dm(
        recipient_user_id=job.user_id,
        message=job.dm_message,
        comment_id=job.comment_id,
        idempotency_key=job.idempotency_key,
    )

    # Step 4: Handle result
    if result["success"]:
        await mark_job_accepted(job.job_id, result["dm_id"])

    elif result["should_retry"]:
        await mark_job_for_retry(
            job_id=job.job_id,
            error_message=result["error"],
            retry_after=result["retry_after"],
        )

    else:
        # 400 or permanent failure
        await mark_job_failed(job.job_id, result["error"])


async def dm_worker():
    
    logger.info("DM worker started")

    while True:
        try:
            job = await claim_next_dm_job()

            if not job:
                await asyncio.sleep(DM_WORKER_SLEEP_SECONDS)
                continue

            await process_dm_job(job)

        except Exception:
            logger.exception("DM worker loop crashed unexpectedly")
            await asyncio.sleep(DM_WORKER_SLEEP_SECONDS)