

import logging

from fastapi import APIRouter, Request, Response, status

from app.config import settings
from app.services.webhook_store import store_webhook_event
from app.utils.signature import verify_signature

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def receive_webhook(request: Request):
    
    raw_body = await request.body()

    signature = request.headers.get("X-PseudoGram-Signature")

    logger.info(f"DEBUG signature header: {signature}")
    logger.info(f"DEBUG all headers: {dict(request.headers)}")
    logger.info(f"DEBUG body length: {len(raw_body)}")
    logger.info(f"DEBUG body sample: {raw_body[:200]}")
    
    if not verify_signature(raw_body, settings.pseudogram_api_key, signature):
        logger.warning("Invalid webhook signature")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
    
    if not verify_signature(raw_body, settings.pseudogram_api_key, signature):
        logger.warning("Invalid webhook signature")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    try:
        payload = await request.json()
    except Exception:
        logger.error("Invalid webhook JSON")
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    event_id = payload.get("event_id")
    event_type = payload.get("event_type")

    if not event_id or not event_type:
        logger.warning("Webhook missing event_id or event_type")
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    await store_webhook_event(payload)

    return {"status": "ok"}