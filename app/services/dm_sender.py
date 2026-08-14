

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select, text

from app.config import settings
from app.database import get_db_session
from app.models import RateLimitLog

logger = logging.getLogger(__name__)

PSEUDOGRAM_DM_URL = f"{settings.pseudogram_base_url}/v1/dm/send"


async def check_rate_limit() -> float:
    
    window_start = datetime.now(timezone.utc) - timedelta(seconds=settings.rate_limit_window)

    async with get_db_session() as db:
        result = await db.execute(
            select(RateLimitLog)
            .where(RateLimitLog.sent_at >= window_start)
            .order_by(RateLimitLog.sent_at)
        )
        recent_sends = result.scalars().all()

        if len(recent_sends) < settings.rate_limit_max:
            return 0.0

        # Window full — find when oldest send expires
        oldest = recent_sends[0].sent_at

        # Make oldest timezone-aware if it isn't
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)

        expires_at = oldest + timedelta(seconds=settings.rate_limit_window)
        wait_seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()

        return max(0.0, wait_seconds)


async def record_send_attempt():
    
    async with get_db_session() as db:
        db.add(RateLimitLog())
        await db.flush()


async def send_dm(
    recipient_user_id: str,
    message: str,
    comment_id: str,
    idempotency_key: str,
) -> dict:
    headers = {
        "X-API-Key": settings.pseudogram_api_key,
        "Content-Type": "application/json",
        "Idempotency-Key": idempotency_key,
    }

    body = {
        "recipient_user_id": recipient_user_id,
        "message": message,
        "comment_id": comment_id,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                PSEUDOGRAM_DM_URL,
                json=body,
                headers=headers,
            )

        # DM accepted (200 or 202)
        if response.status_code in (200, 202):
            data = response.json()
            dm_id = data.get("dm_id")
            logger.info(f"DM accepted | dm_id={dm_id} user={recipient_user_id}")
            return {
                "success": True,
                "dm_id": dm_id,
                "should_retry": False,
                "retry_after": 0.0,
                "error": None,
            }

        # 429 Rate limited
        elif response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 60))
            logger.warning(
                f"Rate limited by PseudoGram | retry_after={retry_after}s user={recipient_user_id}"
            )
            return {
                "success": False,
                "dm_id": None,
                "should_retry": True,
                "retry_after": retry_after,
                "error": "rate_limited",
            }

        # 500 Server error
        elif response.status_code == 500:
            logger.warning(f"PseudoGram 500 error | user={recipient_user_id}")
            return {
                "success": False,
                "dm_id": None,
                "should_retry": True,
                "retry_after": 0.0,
                "error": "internal_error",
            }

        # 400 Bad request
        elif response.status_code == 400:
            detail = response.json().get("detail", "unknown")
            logger.error(f"PseudoGram 400 bad request | user={recipient_user_id} detail={detail}")
            return {
                "success": False,
                "dm_id": None,
                "should_retry": False,
                "retry_after": 0.0,
                "error": f"bad_request: {detail}",
            }

        else:
            logger.error(
                f"Unexpected PseudoGram response | status={response.status_code} user={recipient_user_id}"
            )
            return {
                "success": False,
                "dm_id": None,
                "should_retry": True,
                "retry_after": 0.0,
                "error": f"unexpected_status: {response.status_code}",
            }

    except httpx.TimeoutException:
        logger.warning(f"DM send timeout | user={recipient_user_id}")
        return {
            "success": False,
            "dm_id": None,
            "should_retry": True,
            "retry_after": 0.0,
            "error": "timeout",
        }

    except httpx.RequestError as e:
        logger.error(f"DM send network error | user={recipient_user_id} error={e}")
        return {
            "success": False,
            "dm_id": None,
            "should_retry": True,
            "retry_after": 0.0,
            "error": f"network_error: {e}",
        }