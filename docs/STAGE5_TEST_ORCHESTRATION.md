# Stage 5 — Safe Test Campaign Orchestration & Analytics

> Этап 5 — безопасный тестовый запуск кампаний и аналитика.

## Цель

Управляемый **тестовый** запуск группы уже созданных и вручную одобренных сообщений Stage 4:

1. Создать `CampaignExecutionRun` (snapshot списка сообщений).
2. Обрабатывать только `APPROVED` test messages с recipient `@example.test`.
3. Отправлять **только** через существующий Stage 4 `send_message` → `TestEmailProvider`.
4. Ручные Start / Pause / Resume / Cancel.
5. Соблюдать `SYSTEM_STOP_ALL`.
6. At-most-once: не вызывать provider повторно для SENT / FAILED / BLOCKED / UNKNOWN.
7. Тестовая аналитика кампании.
8. Без реальной рассылки и без scheduler auto-start.

## Аудит (кратко)

| Область | Вывод |
|---|---|
| OutreachMessage / SendAttempt / Stage 4 send | Переиспользовать; оркестратор **не** дублирует provider |
| At-most-once Stage 4 | Claim + PENDING outbox + unique `outreach:send:{id}` |
| `DELIVERY_OUTCOME_UNKNOWN` | Stale PENDING → message FAILED + код; item → UNKNOWN |
| beat_schedule | Пуст — не добавлять execution |
| Миграция | Нужна `0006_test_campaign_execution` |

## Workflow

```
APPROVED OutreachMessages (sequence, @example.test)
        │
        ▼
POST execution-runs  → snapshot items (PENDING), run DRAFT/PENDING
        │  (provider count = 0)
        ▼
POST start → claim PENDING→RUNNING → Celery batch
        │
        ├─ per item: claim PENDING→PROCESSING → Stage 4 send_message
        ├─ Pause / Resume / Cancel (manual)
        └─ STOP → BLOCKED (no provider)
```

## Модели

### CampaignExecutionRun

`id`, `campaign_id`, `sequence_id`, `status`, `execution_mode=TEST_MANUAL_ONLY`,
`max_messages`, `batch_size`, timestamps, counters, `idempotency_key`, `is_test_data`, `error_message`.

Statuses: `DRAFT` | `PENDING` | `RUNNING` | `PAUSED` | `COMPLETED` | `FAILED` | `BLOCKED` | `CANCELLED`.

### CampaignExecutionItem

`id`, `execution_run_id`, `outreach_message_id`, `position`, `status`, timestamps, `error_message`, `is_test_data`.

Statuses: `PENDING` | `PROCESSING` | `SENT` | `FAILED` | `BLOCKED` | `SKIPPED` | `UNKNOWN` | `CANCELLED`.

Uniques: `(run_id, message_id)`, `(run_id, position)`.

## Run state machine

```
DRAFT → PENDING → RUNNING ⇄ PAUSED
                 ↓           ↓
              BLOCKED    CANCELLED
                 ↓
             COMPLETED / FAILED
```

- Atomic claim: `PENDING→RUNNING`, `PAUSED→RUNNING` (rowcount).
- Terminal: no-op. STOP before/during → `BLOCKED` (no auto-resume).

## Item processing

1. Check run status (PAUSED/CANCELLED/BLOCKED stop).
2. STOP check (`is_system_stopped` clears settings cache).
3. Claim item `PENDING→PROCESSING` (atomic `UPDATE … WHERE status='PENDING'`).
4. Call Stage 4 `send_message` only (never `TestEmailProvider` directly).
5. Map:
   - OutreachMessage SENT → item SENT
   - FAILED → FAILED (or UNKNOWN if `DELIVERY_OUTCOME_UNKNOWN`)
   - BLOCKED → BLOCKED
   - **already SENT before claim → item SKIPPED** (`skipped_count`, no provider call)
6. Stale PROCESSING recovery (no provider):
   - message SENT/FAILED/BLOCKED/UNKNOWN → mirror
   - fresh PENDING SendAttempt → leave PROCESSING
   - stale PENDING attempt → item UNKNOWN
   - APPROVED + no SendAttempt → reset item PENDING
   - doubt → UNKNOWN
7. Counters rebuilt from item statuses (`_recompute_counters`); not trusted increments.
8. Next Celery batch enqueued only after batch commit when PENDING remain; `max_retries=0`.
9. Concurrent RUNNING workers OK: item claims prevent double send.
10. One active run per `(campaign_id, sequence_id)` via partial unique index.

## Limits

- `max_messages`: 1–100
- `batch_size`: 1–10
- One active (non-terminal) run per `(campaign_id, sequence_id)`
- Next batch via explicit Celery enqueue (idempotent), never beat

## Analytics

DB-derived TEST metrics: approved leads/messages, sent/failed/blocked/unknown/rejected, run counters, rates. UNKNOWN ≠ SENT. No body/recipient/provider payload.

## API

| Method | Path |
|---|---|
| POST/GET | `/api/campaigns/{id}/execution-runs` |
| GET | `.../execution-runs/{run_id}` |
| POST | `.../start` `.../pause` `.../resume` `.../cancel` |
| GET | `.../items` |
| GET | `/api/campaigns/{id}/analytics` |

## Celery

`process_test_campaign_execution_task(run_id)` — `max_retries=0`, claim run, process batch, enqueue next if needed. `beat_schedule` empty.

## SYSTEM_STOP_ALL

- Checked before run claim (start/resume) and before each item / batch.
- STOP before start → run `BLOCKED`, `finished_at` set, provider not called.
- STOP mid-run → run `BLOCKED`; current unsent item does not call provider; remaining items stay `PENDING` (or item claimed after STOP → `BLOCKED`).
- Clearing STOP does **not** auto-resume; create a new run or document a manual reset (Stage 5 has no auto-retry of `BLOCKED`).

## Recovery (stale PROCESSING)

1. Inspect `OutreachMessage` status.
2. SENT / FAILED / BLOCKED / UNKNOWN → mirror on item without provider call.
3. Message still `APPROVED` and no `SendAttempt` → reset item to `PENDING` (provider never reserved).
4. Message `APPROVED` but attempt exists → item `UNKNOWN`, no provider retry.
5. Counters rebuilt from items (`_recompute_counters`) — no double-count on redelivery.

## Safety

- Only TestEmailProvider / `@example.test` via Stage 4 `send_message`
- Manual create + manual start
- No auto-retry UNKNOWN
- `SYSTEM_STOP_ALL`
- `is_test_data=true`
- Logs: no body, recipient, tokens, or secrets
- `beat_schedule` empty — no periodic auto-start

## Roadmap (not implemented)

- **Stage 6** — Compliance, Suppression & Provider Readiness
- **Stage 7** — Controlled Live Pilot
- **Stage 8** — Production Hardening & Deployment

## Критерии готовности

Миграция 0006, atomic claims, Stage 4 send reuse, Pause/Resume/Cancel, analytics, tests, Docker smoke, docs.
