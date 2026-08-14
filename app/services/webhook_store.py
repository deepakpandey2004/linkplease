

import logging

from sqlalchemy.exc import IntegrityError

from app.database import get_db_session
from app.models import WebhookEvent

logger = logging.getLogger(__name__)


async def store_webhook_event(payload: dict) -> bool:
    
    event_id = payload["event_id"]
    event_type = payload["event_type"]

    async with get_db_session() as db:
        try:
            db.add(
                WebhookEvent(
                    event_id=event_id,
                    event_type=event_type,
                    payload=payload,
                    status="pending",
                )
            )
            await db.flush()

            logger.info(f"Webhook event stored | event_id={event_id} type={event_type}")
            return True

        except IntegrityError:
            await db.rollback()
            logger.info(f"Duplicate webhook event ignored | event_id={event_id}")
            return False