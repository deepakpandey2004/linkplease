# FAILURES.md — Known Limitations of LinkPlease Backend

This document lists every way my system can still lose a DM, send a duplicate,
or report a wrong number. Every item was observed during actual testing with
the PseudoGram simulator (500 events, 10 seconds, deployed on Render).

---

## Observed Test Results

500 events fired over 10 seconds against my deployed URL:

| Metric | Actual | Notes |
|---|---|---|
| Total events received (webhook_200_count) | 544 / 544 | 100% accepted (includes ~8% redeliveries) |
| duplicates_blocked | 152 | Event + business-level dedup combined |
| DMs delivered (sent) | 163 | Confirmed by polling `/v1/dm/{dm_id}` |
| DMs permanently failed | 22 | Gave up after 5 retries |
| DMs still queued after 20 min | 1 | Stuck in retry loop, see #7 |
| Expected unique recipients (from truth) | 97 | Truth from `/simulate/{run_id}/truth` |
| Actual (user_id, rule_id) jobs created | 186 | 97 users × 2 rules = 194 theoretical max |
| Missing jobs | 8 | See failure #6 |
| Delivery rate | 87.6% | Close to PseudoGram's ~85% expected |

---

## 1. Webhook Signature Verification Is Disabled

**Condition:** All incoming webhook events.  
**What happens:** My HMAC-SHA256 computation using the API key as the secret does
not match the `X-PseudoGram-Signature` header sent by PseudoGram.  
**What I tried:** 7 different secret variations — raw UTF-8 key, base64-decoded,
URL-safe base64-decoded, split before/after the dot (`.`), hex-decoded of the
part after the dot. None produced a matching signature.  
**Current state:** `VERIFY_SIGNATURE = False` in `app/routes/webhook.py`. My
webhook currently accepts unsigned/forged requests too.  
**Impact:** Part B is not truly complete. A forged request could inject fake
comment events and cause spurious DMs.  
**What I would do with more time:** Ask the assignment owner what secret
PseudoGram uses to sign, since the documented "your API key" does not work.

---

## 2. Rate Limit Tracking Diverges From PseudoGram's Actual Count

**Condition:** High-throughput periods (during the 500-event test).  
**What happens:** My `rate_limit_log` table tracks send attempts on my side.
PseudoGram may count differently (network delays, its own window boundary).  
**Impact:** I sometimes hit 429 even when my internal counter says I have room.
No data loss — retry handles it — but extra API calls and delays.  
**Observed:** Multiple `Rate limited by PseudoGram | retry_after=X` warnings
during the 500-event test.

---

## 3. Race Condition Window for Business Dedup Is Protected by DB Constraint

**Condition:** Two events for the same (user_id, rule_id) arriving within
milliseconds of each other.  
**What happens:** Both events reach `create_dm_job()`. The `UniqueConstraint`
on (user_id, rule_id) in the DB causes one `INSERT` to raise `IntegrityError`.
The application catches this and increments `duplicates_blocked`.  
**Impact:** No duplicate DMs. This is reliable.  
**Confidence:** High. Protected by DB-level constraint, not fragile application
logic.

---

## 4. `comment.deleted` Arriving Before `comment.created`

**Condition:** Out-of-order webhook delivery.  
**What happens:** The `comment.deleted` handler runs first, finds no pending
DM to cancel (because it hasn't been created yet), and does nothing. Then
the `comment.created` event arrives and queues a DM normally.  
**Impact:** DM is sent for a comment that was already deleted.  
**Mitigation:** None. Would require recording all deleted `comment_id`s in a
tombstone table so future `comment.created` events for that ID are ignored.

---

## 5. Stats Non-Atomicity Between Job Status and Counter Updates

**Condition:** Worker crashes between updating `dm_jobs.status` and calling
`update_stat()`.  
**What happens:** Job may be marked `delivered` in `dm_jobs` but `sent` counter
never incremented. Or `queued` counter goes negative if decrement runs but
increment did not.  
**Impact:** `/stats` numbers may drift from actual DB truth.  
**Confidence:** Not observed in this test run, but possible under crash/restart.

---

## 6. Some Jobs Never Get Created

**Condition:** Observed in 500-event test.  
**What happens:** Truth reports 97 unique recipients. With 2 rules, that's a
theoretical maximum of 194 (user_id, rule_id) jobs. My system created 186 —
so 8 are missing.  
**Possible causes:**
- Some events processed while worker was mid-transaction and got skipped
- Race condition between webhook receipt and event processing
- Some comments genuinely did not match any rule (this is expected behavior,
  but 8 seems high)  
**Impact:** ~4% of potential DMs never queued.  
**Root cause not identified.** Would need to add more detailed tracing to
find the exact skipped events.

---

## 7. Delivery-Failed Retry Uses Existing retry_count

**Condition:** DM is accepted by PseudoGram (202), later confirmed `failed`
by polling.  
**What happens:** Poller resets job to `pending`, but `retry_count` continues
from where it was. So a DM that succeeded at send but failed at delivery may
only have 1-2 retries left instead of a fresh 5.  
**Impact:** Some delivery-failed DMs give up earlier than intended.  
**Trade-off:** Prevents infinite retry loops on permanently broken DMs.

---

## 8. Stuck Jobs in `sending` State After Sudden Restart

**Condition:** App killed mid-request (SIGKILL, not graceful shutdown).  
**What happens:** Any `dm_job` with `status='sending'` at that moment stays
there forever. My startup only resets `webhook_events` from `processing` →
`pending`, not `dm_jobs`.  
**Impact:** Potentially lost DMs on abrupt restart.  
**Fix would be:** Add equivalent `reset_stuck_dm_jobs()` on startup.

---

## 9. Unbounded Table Growth

**Condition:** System runs for a long time.  
**What happens:** `seen_events`, `webhook_events`, `rate_limit_log`, and
completed `dm_jobs` all accumulate forever. No TTL, no cleanup.  
**Impact:** Query performance degrades. DB size grows.  
**Mitigation:** None. Would add a periodic cleanup job to delete rows older
than some cutoff.

---

## 10. Single Worker Instance

**Condition:** Currently only one instance of each background worker runs.  
**What happens:** Throughput is limited to what one worker can handle. Rate
limit is 10/60s anyway, so single worker is fine for that. But if the process
hangs, everything stops.  
**Impact:** No horizontal scaling. Single point of failure.  
**Note:** The queue design uses `FOR UPDATE SKIP LOCKED` so multiple workers
COULD run concurrently, but I haven't set that up.