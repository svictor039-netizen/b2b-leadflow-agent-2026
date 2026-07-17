# Stage 5 Final Code Review (pre-commit)

**Branch:** `feature/stage-5-test-campaign-orchestration`
**Base:** `main @ 748f2c5`
**Commit / push / merge:** not performed
**Status:** READY_FOR_COMMIT

## Findings

| Severity | Issue | Fix |
|---|---|---|
| HIGH | Stale PROCESSING treated any SendAttempt as UNKNOWN, including fresh in-flight PENDING | Fresh PENDING/SENDING left alone; stale → UNKNOWN; APPROVED+no attempt → reset PENDING |
| HIGH | RUNNING with only fresh PROCESSING could busy-loop (sync) or false-complete | Exit without COMPLETED; counters recomputed; no busy-loop |
| HIGH | One active run per campaign+sequence only app-checked (race) | Partial unique index `uq_execution_runs_active_campaign_sequence` + IntegrityError handling |
| MEDIUM | `started_at` / `paused_at` / `cancelled_at` could be overwritten on races | `func.coalesce(...)` on claim/pause/cancel/STOP |
| MEDIUM | Empty `message_ids=[]` not validated; duplicates not normalized | Schema validator |
| MEDIUM | Celery task lacked rollback on error; AppError returned as FAILED | `db.rollback()`; response `ERROR` (does not mark run FAILED incorrectly) |
| LOW | Frontend Start enabled for PAUSED/terminal | Start only for DRAFT/PENDING |
| LOW | Stage 1 index drift | Known, not fixed in Stage 5 |

No BLOCKER remaining after fixes.

## Semantics locked

- Already SENT before item claim → item **SKIPPED** (no provider)
- Concurrent RUNNING workers OK via atomic item claim
- Next-batch enqueue after batch commit; double delivery safe
- STOP between items: first result kept; remaining PENDING; run BLOCKED; no auto-resume
- Cancel during send: in-flight result kept as SENT; other PENDING → CANCELLED

## Verification

| Check | Result |
|---|---|
| pytest | **160 passed**, 1 skipped |
| frontend build | OK |
| docker compose config | OK |
| alembic heads | `0006_test_campaign_execution` |
| alembic 0005↔0006 | OK (IF EXISTS downgrade) |
| Stage5 smoke | OK |

## Safety

TestEmailProvider only via Stage 4; `@example.test`; empty `beat_schedule`; SYSTEM_STOP_ALL; no UNKNOWN→SENT; no auto-retry.
