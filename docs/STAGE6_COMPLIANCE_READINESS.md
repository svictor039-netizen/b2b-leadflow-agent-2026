# Stage 6 — Compliance, Suppression & Provider Readiness

> Этап 6 — compliance-контур, стоп-листы и подготовка к подключению email-провайдера.

## Цель

Обязательный защитный слой перед будущим Stage 7 Controlled Live Pilot:

1. Глобальные и campaign suppression-записи.
2. Блокировка запрещённых recipient / domain / company / lead.
3. Единый compliance gate перед Stage 4 send и перед Stage 5 item.
4. Audit log решений.
5. Provider Readiness Report (локально, без реального provider).
6. Только `TestEmailProvider` и `@example.test`.

## Аудит (кратко)

| Область | Вывод |
|---|---|
| Suppression entities | Не существовали — нужна `0007_compliance_ready` |
| Contact.do_not_contact | Не используется в send |
| Gate insertion | `_send_claimed_message` до APPROVED→SENDING |
| Stage 5 | Pre-claim check + Stage 4 gate |
| beat_schedule | Пуст — не добавлять jobs |

## Suppression model (`SuppressionEntry`)

Scopes: `GLOBAL` | `CAMPAIGN`  
Types: `EMAIL` | `DOMAIN` | `COMPANY` | `CAMPAIGN_LEAD`  
Reasons: `DO_NOT_CONTACT` | `UNSUBSCRIBE` | `COMPLAINT` | `HARD_BOUNCE` | `LEGAL_BLOCK` | `MANUAL_BLOCK` | `INVALID_RECIPIENT`  
Sources: `MANUAL` | `TEST_EVENT` | `SYSTEM`

Partial uniques (active only):

- GLOBAL: `(suppression_type, normalized_value) WHERE is_active AND scope=GLOBAL`
- CAMPAIGN: `(campaign_id, suppression_type, normalized_value) WHERE is_active AND scope=CAMPAIGN`

Inactive history allowed. Expired / inactive do not block.

## Normalization

- EMAIL: ASCII, trim, lowercase domain, one `@`, **only** `@example.test`
- DOMAIN: lowercase, strip protocol/`www`/path, no auto parent-domain match
- COMPANY / CAMPAIGN_LEAD: exact UUID ids

## Compliance gate

`check_outreach_compliance(...)` order:

1. Campaign / test mode  
2. CampaignLead  
3. Company  
4. Recipient email  
5. Global suppressions  
6. Campaign suppressions  
7. expiration / is_active  
8. Audit log  
9. ALLOWED | BLOCKED  

Priority: exact email → campaign lead → company → exact domain.

## Race protection (send ↔ suppression)

PostgreSQL session advisory locks shared by:

- suppression create / deactivate / reactivate (key = scope+type+normalized[+campaign]);
- Stage 4 send (keys for email/domain/company/lead GLOBAL+CAMPAIGN).

Send path under lock: STOP → compliance → APPROVED→SENDING → compliance re-check → outbox → STOP → compliance → TestEmailProvider.  
Suppression cannot commit between ALLOWED and provider without waiting for the same lock.

## Stage 4 integration

Under advisory locks: STOP → compliance → atomic `APPROVED→SENDING` → re-check → provider.  
BLOCKED → no provider, message `BLOCKED` (from APPROVED or SENDING), audit log, no SUCCESS SendAttempt.

State machine (terminal): `SENT` | `FAILED` | `BLOCKED` | `UNKNOWN` (via delivery-unknown recovery).  
Suppression after `SENT` does not rewrite history.

## Stage 5 integration

Before item claim: compliance check.  
Message suppression → **item BLOCKED only** (run continues).  
`SYSTEM_STOP_ALL` → whole run BLOCKED (unchanged Stage 5 policy).

## Test events

`POST /api/campaigns/{id}/compliance/test-events`  
Types: UNSUBSCRIBE | COMPLAINT | HARD_BOUNCE — local only, `@example.test`, idempotent.

## Provider Readiness

Local checks only. Expected Stage 6:

- `TEST_READY`
- `LIVE_NOT_READY`

Secrets: `present` / `missing` only. No DNS/HTTP/provider calls.

## Reactivate semantics

`reactivate` sets `is_active=true` under lock. If `expires_at` is already past, it is cleared so the entry becomes effective. Idempotent when already active. Conflict with another active key → 409.

## Expiration

`expires_at` is timezone-aware UTC. Gate uses `expires_at > now` (equal → not blocking). `null` = no expiry.

## Audit log idempotency

`ComplianceDecisionLog.idempotency_key` = hash(context, message_id, decision, matched_entry, reason_code).  
Celery/API repeats with the same decision do not duplicate rows. ALLOWED then BLOCKED (re-check) are distinct keys.

## SYSTEM_STOP_ALL

CRUD / readiness / test events / manual check allowed under STOP.  
Send / execution remain blocked by Stage 4/5. STOP is checked with cache clear and has priority over compliance ALLOWED.

## Roadmap boundary

- **Stage 6** — this document (no live provider)
- **Stage 7** — Controlled Live Pilot (not implemented)
- **Stage 8** — Production Hardening (not implemented)

## Что не входит в Stage 6

SMTP, Gmail/Graph/SendGrid/Mailgun/Resend/SES, реальные recipient/sender, DNS, внешние webhooks, auto bounce/complaint из провайдера, production credentials, mass send, scheduler auto-send, live mode, отключение SYSTEM_STOP_ALL.

## Критерии готовности

Migration `0007_compliance_ready`, gate in Stage 4/5, suppression API, test events, readiness report (`TEST_READY` / `LIVE_NOT_READY`), tests, smoke, docs.
