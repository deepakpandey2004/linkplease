

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.database import get_db_session
from app.models import DmJob
from app.services.event_processor import update_stat
from app.services.status_poller import check_dm_status

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 30
MAX_DM_RETRIES = 5


async def get_accepted_jobs() -> list[DmJob]:
    
    async with get_db_session() as db:
        result = await db.execute(
            select(DmJob).where(DmJob.status == "accepted")
        )
        return result.scalars().all()


async def handle_delivered(job_id: str):
    
    async with get_db_session() as db:
        job = await db.get(DmJob, job_id)
        if not job:
            return

        job.status = "delivered"
        job.updated_at = datetime.now(timezone.utc)
        await db.flush()

    await update_stat("queued", -1)
    await update_stat("sent", 1)
    logger.info(f"DM delivered confirmed | job_id={job_id}")


async def handle_delivery_failed(job_id: str):
    
    async with get_db_session() as db:
        job = await db.get(DmJob, job_id)
        if not job:
            return

        job.retry_count += 1

        if job.retry_count >= MAX_DM_RETRIES:
            job.status = "failed"
            job.error_message = "Delivery failed after max retries"
            job.updated_at = datetime.now(timezone.utc)
            await db.flush()

            await update_stat("queued", -1)
            await update_stat("failed", 1)
            logger.error(
                f"DM delivery permanently failed | job_id={job_id} "
                f"retries={job.retry_count}"
            )
            return

        # Put back to pending so dm_worker picks it up again
        job.status = "pending"
        job.dm_id = None
        job.error_message = "Delivery failed, retrying"
        job.updated_at = datetime.now(timezone.utc)
        await db.flush()

    logger.warning(
        f"DM delivery failed, queued for retry | job_id={job_id} "
        f"retry={job.retry_count}"
    )


async def poll_once():
    
    jobs = await get_accepted_jobs()

    if not jobs:
        return

    logger.info(f"Polling {len(jobs)} accepted DM(s) for delivery status")

    for job in jobs:
        if not job.dm_id:
            logger.warning(f"Job has no dm_id | job_id={job.job_id}")
            continue

        status = await check_dm_status(job.dm_id)

        if status == "delivered":
            await handle_delivered(job.job_id)

        elif status == "failed":
            await handle_delivery_failed(job.job_id)

        elif status == "queued":
            # Still processing — check again next cycle
            logger.debug(f"DM still queued | job_id={job.job_id} dm_id={job.dm_id}")

        else:
            # None — API error, skip this cycle
            logger.warning(
                f"Could not get DM status | job_id={job.job_id} dm_id={job.dm_id}"
            )


async def poller_worker():
    
    logger.info("Poller worker started")

    while True:
        try:
            await poll_once()
        except Exception:
            logger.exception("Poller worker cycle failed")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)