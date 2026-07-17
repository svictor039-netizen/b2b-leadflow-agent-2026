# Stage 4 Final Code Review (pre-commit)

**Branch:** `feature/stage-4-safe-outreach-approval`
**Commit/push/merge:** not performed
**Status:** READY_FOR_COMMIT

## Recovery semantics (HIGH fix closed)

Stale `SendAttempt` **PENDING** never becomes SENT.

| Situation | Message | SendAttempt | Provider |
|---|---|---|---|
| Confirmed provider + DB SUCCESS | SENT | SUCCESS | once |
| Fresh PENDING (&lt;30s) | 409 SENDING | PENDING | not by peer |
| **Stale PENDING** | **FAILED** | **FAILED** + `DELIVERY_OUTCOME_UNKNOWN` | **not** again |
| Provider exception | FAILED | FAILED | once |
| STOP before claim | BLOCKED | no success | not called |

- **At-most-once** on `outreach:send:{message_id}`
- **Exactly-once not promised**
- Possible lost test send on unknown outcome
- **False SENT forbidden**
- **Auto-resend forbidden**

UI: «Результат тестовой отправки не подтверждён. Автоматический повтор заблокирован.»

## State machine

```
DRAFT → APPROVED → SENDING → SENT          (only confirmed success + DB)
                 ↘ REJECTED
SENDING + stale PENDING → FAILED (DELIVERY_OUTCOME_UNKNOWN)
SENDING + provider error → FAILED
APPROVED + STOP → BLOCKED
```

## Verification

| Check | Result |
|---|---|
| pytest | **138 passed**, 1 skipped |
| frontend build | OK |
| docker compose config | OK |
| Stage4 smoke | OK |

## Git

Dirty working tree on `feature/stage-4-safe-outreach-approval` — no commit.
