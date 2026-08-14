

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select

from app.database import get_db_session
from app.models import WebhookEvent
from app.services.event_processor import process_comment_event, process_comment_deleted

logger = logging.getLogger(__name__)

EVENT_WORKER_SLEEP_SECONDS = 1
EVENT_MAX_RETRIES = 5


async def reset_stuck_webhook_events():
    
    async with get_db_session() as db:
        result = await db.execute(
            select(WebhookEvent).where(WebhookEvent.status == "processing")
        )
        stuck_events = result.scalars().all()

        for event in stuck_events:
            event.status = "pending"
            event.next_retry_at = None

        if stuck_events:
            logger.warning(f"Reset {len(stuck_events)} stuck webhook events to pending")


async def claim_next_webhook_event() -> WebhookEvent | None:
    
    async with get_db_session() as db:
        stmt = (
            select(WebhookEvent)
            .where(
                WebhookEvent.status == "pending",
                or_(
                    WebhookEvent.next_retry_at.is_(None),
                    WebhookEvent.next_retry_at <= func.now(),
                ),
            )
            .order_by(WebhookEvent.received_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )

        result = await db.execute(stmt)
        event = result.scalar_one_or_none()

        if not event:
            return None

        event.status = "processing"
        await db.flush()

        # Detached snapshot return kar rahe hain
        return event


async def mark_event_processed(event_id: str):
    async with get_db_session() as db:
        event = await db.get(WebhookEvent, event_id)
        if not event:
            return

        event.status = "processed"
        event.processed_at = datetime.now(timezone.utc)
        event.last_error = None


async def mark_event_for_retry(event_id: str, error_message: str):
    async with get_db_session() as db:
        event = await db.get(WebhookEvent, event_id)
        if not event:
            return

        event.attempt_count += 1
        event.last_error = error_message

        if event.attempt_count >= EVENT_MAX_RETRIES:
            event.status = "failed"
            logger.error(
                f"Webhook event permanently failed | event_id={event_id} attempts={event.attempt_count}"
            )
            return

        backoff_seconds = 2 ** event.attempt_count
        event.status = "pending"
        event.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)

        logger.warning(
            f"Webhook event scheduled for retry | event_id={event_id} "
            f"attempt={event.attempt_count} retry_in={backoff_seconds}s"
        )


async def process_webhook_event(event: WebhookEvent):
    
    payload = event.payload
    event_type = payload.get("event_type")
    event_data = payload.get("data", {})

    if event_type == "comment.created":
        await process_comment_event(event_data)

    elif event_type == "comment.deleted":
        await process_comment_deleted(event_data)

    else:
        logger.warning(f"Unknown webhook event type: {event_type}")


async def event_worker():
    
    logger.info("Event worker started")

    while True:
        try:
            event = await claim_next_webhook_event()

            if not event:
                await asyncio.sleep(EVENT_WORKER_SLEEP_SECONDS)
                continue

            try:
                await process_webhook_event(event)
                await mark_event_processed(event.event_id)

            except Exception as e:
                logger.exception(f"Webhook event processing failed | event_id={event.event_id}")
                await mark_event_for_retry(event.event_id, str(e))

        except Exception:
            logger.exception("Event worker loop crashed")
            await asyncio.sleep(EVENT_WORKER_SLEEP_SECONDS)