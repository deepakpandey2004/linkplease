
import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.database import create_tables, init_stats
from app.routes import rules, stats, webhook
from app.workers.dm_worker import dm_worker
from app.workers.event_worker import event_worker, reset_stuck_webhook_events
from app.workers.poller_worker import poller_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting LinkPlease backend...")

    await create_tables()
    await init_stats()
    await reset_stuck_webhook_events()

    event_task = asyncio.create_task(event_worker())
    dm_task = asyncio.create_task(dm_worker())
    poll_task = asyncio.create_task(poller_worker())

    logger.info("LinkPlease backend is ready")
    yield

    logger.info("Shutting down LinkPlease backend...")

    event_task.cancel()
    dm_task.cancel()
    poll_task.cancel()

    with suppress(asyncio.CancelledError):
        await event_task

    with suppress(asyncio.CancelledError):
        await dm_task

    with suppress(asyncio.CancelledError):
        await poll_task


app = FastAPI(
    title="LinkPlease",
    description="Instagram comment-to-DM automation backend",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(rules.router)
app.include_router(stats.router)
app.include_router(webhook.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "linkplease"}