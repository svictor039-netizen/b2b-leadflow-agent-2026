# Stage 6 Final Code Review (pre-commit)

**Branch:** `feature/stage-6-compliance-suppression-readiness`  
**Base:** `main @ 7f11f3d`  
**Commit / push / merge:** not performed  
**Status:** READY_FOR_COMMIT

## 1. Findings

| Severity | Issue | Fix |
|---|---|---|
| **HIGH** | TOCTOU: compliance ALLOWED → claim → provider; suppression could commit before provider | Session advisory locks shared by send + create/deactivate/reactivate; STOP → check → claim → re-check → outbox → STOP → check → provider under lock |
| **HIGH** | `apply_message_suppression_block` only from APPROVED — post-claim block left SENDING | Also transitions SENDING → BLOCKED; FAILED SendAttempt (not SUCCESS) if outbox already reserved |
| MEDIUM | Placeholder `PROVIDER_API_KEY=changeme` counted as present | Treat empty + placeholders as missing |
| MEDIUM | Reactivate of expired active history kept past `expires_at` (still non-blocking) | Reactivate clears past `expires_at` |
| LOW | Stage 1 index drift | Known, not fixed in Stage 6 |
| LOW | Smoke `provider_calls=2` | Expected: step1 allowed send + step2 allowed execution item; suppressed recipients never call provider |

No BLOCKER remaining after fixes.

## 2. What was fixed

- Advisory lock helpers + wired into suppression CRUD and Stage 4 send
- Post-claim + pre-provider compliance re-checks
- SENDING→BLOCKED on late suppression
- Readiness secret/placeholder handling
- Reactivate/expiration semantics documented + implemented
- Review tests: TOCTOU inject, concurrent send/suppress, unique race, cross-campaign, decision order, secret leak, expiration boundaries

## 3–18. Design locks (post-fix)

- **Migration:** `0007_compliance_ready`
- **Partial unique:** `uq_suppression_active_global`, `uq_suppression_active_campaign` (+ IntegrityError/savepoint/re-SELECT)
- **Race:** pg_advisory_lock on scope/type/value keys; send holds through TestEmailProvider
- **Reactivate:** lock + conflict 409; expired → clear `expires_at`; idempotent if already active
- **Normalization:** ASCII `@example.test` only; IDN rejected; UUID exact for company/lead
- **Expiration:** `expires_at > now` (UTC); `== now` does not block
- **Order:** email → campaign_lead → company → domain
- **Audit:** idempotency_key hash; masked recipient; no body/secrets
- **Stage 4/5:** STOP > compliance; item-only BLOCKED for suppression; double gate OK
- **Test events / readiness / API / frontend / STOP:** unchanged safety; secrets present/missing only

## 19. No real provider / network

Only `TestEmailProvider`; `REAL_EMAIL_PROVIDER_ENABLED=false`; `LIVE_OUTREACH_ENABLED=false`; `beat_schedule={}`; readiness does no DNS/HTTP.

## 20–24. Verification

| Check | Result |
|---|---|
| pytest | **183 passed**, 1 skipped |
| frontend build | OK |
| docker compose config | OK |
| alembic heads | `0007_compliance_ready` |
| alembic 0006↔0007 | OK (`leadflow_mig_s6`) |
| Docker smoke | run with stack (see session); prior smoke OK with `provider_calls=2` explained above |

### Smoke provider_calls=2 explanation

1. Allowed step-1 message → explicit Stage 4 send → **+1**  
2. Allowed step-2 message in Stage 5 execution → **+1**  
Suppressed recipient messages: provider **0**.

## 25–26. Git

See `git diff --stat HEAD` / `git status -sb` in final review response.

## 27. Status

**READY_FOR_COMMIT**
