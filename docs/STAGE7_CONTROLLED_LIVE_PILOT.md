# Stage 7 — Controlled Live Pilot

## Boundary: Stage 6 / Stage 7

| Aspect | Stage 6 | Stage 7A | Stage 7B (future) |
|---|---|---|---|
| Email delivery | `TestEmailProvider` only | Dry-run via `TestEmailProvider` only | One owner-chosen provider, manual canary |
| Recipients | `@example.test` | `@example.test` allowlist only | Owner-confirmed allowlist entry |
| Live mode | Disabled | **Always disabled** (`live_delivery_enabled=false`) | Owner enables env + DB gate |
| Provider API | Not called | Not called | Called once, manually |
| Network | None | None | Provider HTTPS only (7B) |
| Scheduler | Empty `beat_schedule` | Unchanged | Unchanged |

Stage 7A prepares **provider-neutral** infrastructure. No real emails, credentials, SMTP, DNS, or external API calls.

## Stage 7A — Provider-neutral controlled pilot infrastructure

### Goals

1. `TestEmailProvider` unchanged for Stages 4–6.
2. Live provider represented by interface + `DisabledLiveEmailProvider` stub.
3. Live mode cannot be enabled via API.
4. Recipients only from explicit allowlist (Stage 7A: `@example.test` exact match).
5. Hard server-side limits (max 5 recipients/pilot, daily/per-minute = 0 on 7A).
6. Multi-gate manual approval with typed confirmation token.
7. Stage 6 compliance + `SYSTEM_STOP_ALL` cannot be bypassed.
8. UNKNOWN delivery never auto-retried (inherited from Stage 4–5).
9. Scheduler does not run live pilot.
10. Readiness report shows exact blockers until real launch.

### Architecture

```
API (live-pilots)
  → live_pilot_service (CRUD, dry-run, approval)
  → live_pilot_validation_service (validate_live_pilot)
  → pilot_allowlist_service (exact email allowlist)
  → compliance_service (Stage 6 gate — not duplicated)
  → provider_registry
       ├── TestEmailProvider (dry-run only on 7A)
       └── DisabledLiveEmailProvider (LIVE_PROVIDER_NOT_CONFIGURED)
```

### Models (migration `0008_controlled_live_pilot`)

- **LivePilot** — campaign-scoped pilot run with immutable message snapshots, limits, approval metadata.
- **LivePilotRecipient** — masked fingerprint only; links `outreach_message_id`.
- **LivePilotApproval** — manual approval + hashed confirmation challenge.
- **LivePilotEvent** — audit trail (no body, no raw tokens, no secrets).
- **LivePilotAllowlistEntry** — exact email allowlist per campaign (Stage 7A: `@example.test` only).

`live_delivery_enabled` is always `false` on Stage 7A (DB default + API rejection).

### Allowlist

- Exact email match after safe normalization.
- No wildcards, domain-wide rules, or fuzzy matching.
- CR/LF, Unicode spoof, display-name syntax rejected.
- Duplicate add is idempotent.
- Cross-campaign isolation (campaign-scoped entries).
- Inactive/expired entries do not permit send.

Stage 7A: real (non-`@example.test`) addresses → HTTP 422.

### Hard limits (server-enforced)

| Limit | Default | Server max |
|---|---|---|
| Recipients per pilot | 1 | 5 |
| Daily live limit | 0 | enforced 0 on 7A |
| Per-minute live limit | 0 | enforced 0 on 7A |
| Live batch size | 1 | 1 |
| Auto retry | 0 | 0 |
| Scheduler auto-send | false | false |

Client cannot raise limits above server maximum.

### Multi-gate approval

Pilot cannot reach live send without **all** of:

1. `SYSTEM_STOP_ALL` off
2. Campaign active / test-compatible
3. Message approved
4. Compliance Stage 6 ALLOWED
5. Recipient on allowlist
6. Provider selected
7. Provider configuration locally valid
8. Sender identity configured
9. Sender domain configured
10. Daily limit > 0
11. Per-minute limit > 0
12. Manual approval recorded
13. Live mode enabled via environment
14. Database pilot gate enabled
15. Final typed confirmation token matches

On Stage 7A, gates 6–14 remain blockers. No API endpoint enables these flags.

### Confirmation challenge

- Server generates one-time challenge with safe display phrase.
- User types exact confirmation; challenge has TTL; stored as hash only.
- Successful confirmation on 7A → `APPROVED` status only — **no live send**.

### Validation / readiness

`validate_live_pilot(...)` returns `ready`, `overall_status`, `blockers[]`, `warnings[]`, `checks[]`, `generated_at`.

Stage 7A expected outcome:

- Test validation may succeed (`TEST_VALIDATED`).
- Live readiness always `false`.
- Status `READY_FOR_PROVIDER_SELECTION` or `LIVE_NOT_READY`.

### Dry-run

- Uses `TestEmailProvider` only.
- Uses `@example.test` recipients only.
- Runs Stage 6 compliance + allowlist + limits.
- Creates audit records; does **not** increment live counters.
- Idempotent; manual start only; respects `SYSTEM_STOP_ALL`.
- Clearly labeled — not masquerading as live SENT.

### Delivery semantics (Stage 7B+ — documented, not implemented on 7A)

- At-most-once delivery.
- Provider idempotency key required.
- SENT only after confirmed provider acceptance.
- UNKNOWN on indeterminate result — **never auto-retried**.
- Delivery event ≠ email open.
- Bounce/complaint/unsubscribe → Stage 6 suppression.
- Provider webhooks require signature verification (future, provider-specific).

Do **not** claim exactly-once.

### SYSTEM_STOP_ALL

| Allowed under STOP | Blocked under STOP |
|---|---|
| View pilots | Dry-run provider call |
| Readiness / validation | Future live send |
| Cancel | Stage 4 send |
| | Stage 5 execution send |

Approval under STOP: challenge generation allowed; dry-run and live send blocked. STOP checked immediately before any provider call.

### API (Stage 7A)

| Method | Path |
|---|---|
| POST | `/api/live-pilots` |
| GET | `/api/live-pilots` |
| GET | `/api/live-pilots/{id}` |
| POST | `/api/live-pilots/{id}/validate` |
| POST | `/api/live-pilots/{id}/approve` |
| POST | `/api/live-pilots/{id}/cancel` |
| POST | `/api/live-pilots/{id}/dry-run` |
| GET | `/api/live-pilots/{id}/readiness` |
| GET | `/api/live-pilots/{id}/recipients` |
| POST | `/api/live-pilots/{id}/recipients` |

**No live-send endpoint on Stage 7A.**

### Configuration (fail-closed defaults)

```env
LIVE_OUTREACH_ENABLED=false
LIVE_PILOT_DATABASE_GATE=false
LIVE_PROVIDER_NAME=
LIVE_PROVIDER_API_KEY=
LIVE_SENDER_EMAIL=
LIVE_SENDER_DOMAIN=
LIVE_DAILY_LIMIT=0
LIVE_RATE_LIMIT_PER_MINUTE=0
LIVE_PILOT_MAX_RECIPIENTS=1
```

Stage 7A does not enable any live flags. Missing live config does not break test mode.

## Stage 7B — Owner-selected provider canary (pending / optional)

**Not executed in this project delivery.** Owner may later provide: provider choice, verified domain, sender email, pilot recipient, limits, legal basis, footer. Secrets stored outside git. One manual canary send only after all gates pass.

## Stage 8 — Production hardening

**Done** (independent of Stage 7B). See [STAGE8_PRODUCTION_HARDENING_DEPLOYMENT.md](STAGE8_PRODUCTION_HARDENING_DEPLOYMENT.md). No Stage 9.
