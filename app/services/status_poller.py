
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def check_dm_status(dm_id: str) -> str | None:
    
    url = f"{settings.pseudogram_base_url}/v1/dm/{dm_id}"
    headers = {"X-API-Key": settings.pseudogram_api_key}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)

        if response.status_code == 200:
            data = response.json()
            status = data.get("status")
            logger.debug(f"DM status check | dm_id={dm_id} status={status}")
            return status

        else:
            logger.warning(
                f"Unexpected status check response | dm_id={dm_id} "
                f"http_status={response.status_code}"
            )
            return None

    except httpx.TimeoutException:
        logger.warning(f"Status check timeout | dm_id={dm_id}")
        return None

    except httpx.RequestError as e:
        logger.error(f"Status check network error | dm_id={dm_id} error={e}")
        return None