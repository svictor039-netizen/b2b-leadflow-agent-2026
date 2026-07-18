# HOMEWORK REPORT — Stage 7A (Final Review)

**Branch:** `feature/stage-7-controlled-live-pilot`  
**Base:** `main @ 5926629`  
**Review date:** 2026-07-18  
**Final status:** **READY_FOR_COMMIT**

---

## 1. Findings (BLOCKER / HIGH / MEDIUM / LOW)

### BLOCKER (fixed in review)

| ID | Finding | Fix |
|---|---|---|
| B1 | `create_live_pilot` used `msg.subject` / `msg.body` — fields do not exist on `OutreachMessage` (`subject_rendered` / `body_rendered`) | Corrected snapshot source in `live_pilot_service.py` |

### HIGH (fixed in review)

| ID | Finding | Fix |
|---|---|---|
| H1 | Dry-run idempotency had race: concurrent same key could invoke provider twice | Pre-claim via unique `LivePilotEvent` (`dry-run:{key}`) before provider loop |
| H2 | Approval token compared with `!=` (not constant-time) | `hmac.compare_digest` via `_verify_token()` |
| H3 | Repeated `POST /approve` created unlimited challenges/events | Reject with 409 `challenge_pending` if unconsumed challenge still valid |

### MEDIUM (fixed in review)

| ID | Finding | Fix |
|---|---|---|
| M1 | Blocker list order non-deterministic | `_BLOCKER_ORDER` + `_order_blockers()` |
| M2 | Approval challenge audit logged before `approval.id` flush | `db.flush()` before event log |
| M3 | Route test falsely flagged Stage 4 `/outreach/.../send` as live-send | Scoped assertions to `/api/live-pilots` only |

### LOW (accepted / documented)

| ID | Finding | Notes |
|---|---|---|
| L1 | Raw confirmation token returned once in approve API response | By design — not stored; user must copy for confirmation |
| L2 | `LivePilotRead` includes `body_snapshot` | Immutable pilot snapshot for UI; excluded from audit events |
| L3 | APPROVAL_CHALLENGE audit stores safe phrase, not token | Phrase is user-visible confirmation text |

---

## 2. What was fixed in this review pass

- `subject_rendered` / `body_rendered` snapshot bug
- Dry-run DB-level idempotency claim
- Constant-time token verification
- Duplicate approval challenge guard
- Deterministic blocker ordering
- Expanded tests: routes, allowlist edge cases, token failure paths, dry-run provider count idempotency

---

## 3–22. Verification summary

| Check | Result |
|---|---|
| Full pytest (230) | **PASS** |
| Migration tests 0007↔0008 | **PASS** |
| Alembic downgrade/upgrade (live DB) | **PASS** |
| Stage 7A smoke script | **PASS** (`live_sent=0`, `beat={}`) |
| health / readiness / frontend | **200** |
| Worker ping | **OK** |
| `beat_schedule` | `{}` |
| Frontend build | **PASS** |
| `docker compose config` | **PASS** |
| Live-send endpoint | **Absent** under `/api/live-pilots` |
| DisabledLiveEmailProvider network | **None** |
| TestEmailProvider only in dry-run | **Verified** (mock tests) |

---

## 23. git diff --stat HEAD

```
13 files changed, 296 insertions(+), 19 deletions(-)
+ 15 new untracked Stage 7A files
```

---

## 24. git status -sb

```
## feature/stage-7-controlled-live-pilot
 M  (13 tracked)
?? (15 new)
```

No commit / push / merge performed.

---

## 25. Owner decisions for Stage 7B

Provider choice, verified domain, sender email, real allowlist recipient (owner-confirmed), limits > 0, legal basis, footer, API key in env/secrets only, manual `LIVE_OUTREACH_ENABLED` + `LIVE_PILOT_DATABASE_GATE`.

---

## Final status: **READY_FOR_COMMIT**
