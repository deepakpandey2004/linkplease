# LinkPlease Backend

Instagram comment-to-DM automation backend built for the LinkPlease tech intern
assignment. When users comment matching keywords on posts, the system automatically
sends them a DM via the PseudoGram mock API.

## Stack
- Python 3.11 + FastAPI (async)
- PostgreSQL (Neon)
- SQLAlchemy 2.0 async ORM
- httpx for async HTTP
- Deployed on Render

## Endpoints

- `POST /rules` — create a keyword → DM message rule
- `POST /webhook` — receive comment events from PseudoGram
- `GET /stats` — live counters: sent, failed, queued, duplicates_blocked
- `GET /health` — health check

## Architecture

1. Webhook receives event, verifies (currently disabled — see FAILURES.md), stores
   in `webhook_events` table, returns 200 immediately.
2. `event_worker` picks pending events, matches comments against rules, creates
   `dm_jobs` with `UniqueConstraint(user_id, rule_id)` for dedup.
3. `dm_worker` picks pending jobs, checks rate limit (10/60s), sends via
   PseudoGram, handles 202/429/500/400 with exponential backoff.
4. `poller_worker` checks `/v1/dm/{dm_id}` every 30s to confirm delivery,
   retries jobs that failed at delivery.

All state is persistent in PostgreSQL. Nothing critical lives in memory.

## Read `FAILURES.md` for known limitations.