# VCd03 — B2B LeadFlow Agent 2026

> Краткая спецификация. Полное пользовательское ТЗ — в материалах курса VCd03.

## Назначение

Агент для B2B lead generation: кампании по нише/региону, компании и контакты, дальнейшая воронка писем с ручным подтверждением.

## Зафиксированные ограничения MVP

| Ограничение | Значение |
|---|---|
| Роли | Одна роль администратора |
| Кампания | 1 ниша + 1 регион |
| Компании | Максимум 30 |
| Письма на адресат | Максимум 3 |
| Подтверждение | Ручное, обязательное |
| Холодная рассылка | Запрещена (этап 0–1) |
| Email-провайдер | `TestEmailProvider` |
| Источник компаний | `TestSourceAdapter` (не авто-поиск в API) |
| LLM | Не запускает отправку |
| Секреты | Не в Git и не в логах |
| SYSTEM_STOP_ALL | Блокирует исходящие задачи |

## Этап 0

Docker Compose каркас, health/readiness, тестовые провайдеры, Celery ping.

## Этап 1 — модель данных и UI

Таблицы: `campaigns`, `companies`, `company_locations`, `contacts`, `data_sources`, `company_source_records`, `campaign_leads`.

API кампаний/компаний/локаций/контактов. Frontend разделы «Кампании» и «Компании».

**Не входит:** реальный поиск, scraping, enrichment, скоринг, LLM, SMTP/IMAP, отправка, дедупликация, авторизация, деплой.

## Этап 2 — safe research

- Только `TestSourceAdapter`
- Provenance + дедупликация (domain / source_record_id)
- `POST /api/research/runs`, `GET /api/research/runs/{id}`
- См. [STAGE2_RESEARCH.md](STAGE2_RESEARCH.md)

**Не входит:** реальный поиск, scraping, SMTP/IMAP, outreach, сбор реальных email.

## Stage 3 — Safe Lead Qualification & Deterministic Scoring

**Русское название:** Этап 3 — безопасная квалификация и детерминированная оценка лидов.

### Цель

Связать завершённый `ResearchRun` с `Campaign`, создать/найти `CampaignLead` для каждой подходящей компании из provenance Stage 2 и присвоить детерминированный score 0–100 с объяснимыми reasons — без LLM и без email.

### Входные данные

- `campaign_id` — существующая кампания
- `research_run_id` — `ResearchRun` со статусом `COMPLETED` и `is_test_data=true`
- Компании только из `CompanySourceRecord` данного research run

### Модели

- `QualificationRun` — запуск квалификации (status, counters, scoring_version)
- Расширение `CampaignLead` — score, qualification_status, review_decision, provenance
- `LeadScoreSnapshot` — снимок score/reasons/input на пару run+lead

### API

- `POST /api/qualification/runs`
- `GET /api/qualification/runs/{run_id}`
- `GET /api/campaigns/{campaign_id}/leads`
- `POST /api/campaigns/{campaign_id}/leads/{lead_id}/review`

### Scoring rules (`stage3-v1`)

Детерминированный engine без LLM. Баллы за domain / industry / location / profile completeness / provenance; штрафы за conflict / missing name / invalid domain. Clamp 0–100:

| Score | Status |
|---|---|
| 70–100 | QUALIFIED |
| 40–69 | REVIEW |
| 0–39 | DISQUALIFIED |

Ручное решение отдельно: `PENDING` / `APPROVED` / `REJECTED` (не меняет score, не шлёт email).

### Safety

- Только test data и сохранённый provenance Stage 2
- Атомарный claim `PENDING→RUNNING` (один worker); mid-run failure = all-or-nothing rollback + `FAILED`
- `SYSTEM_STOP_ALL` блокирует автоматический qualification → `BLOCKED` + `finished_at` (ручной review разрешён)
- Нет вызовов TestEmailProvider / SMTP / scraping
- Sanitize snapshots; secrets/PII не в API и логах
- Celery redelivery идемпотентна; scheduler не автозапускает qualification

### Критерии готовности

- Unique `(campaign_id, company_id)` и `(qualification_run_id, campaign_lead_id)`
- Идемпотентный повторный qualification
- Score reasons + snapshots сохранены
- Manual review без email
- Тесты + Docker smoke + docs

### Не входит в Stage 3 (Stage 4)

Шаблоны писем, генерация писем, email sequences, отправка (в т.ч. TestEmailProvider), реальные провайдеры, массовый outreach, scheduler рассылок.

См. [STAGE3_QUALIFICATION.md](STAGE3_QUALIFICATION.md)

## Stage 4 — Safe Outreach Templates, Manual Approval & Test Delivery

**Русское название:** Этап 4 — безопасные шаблоны писем, ручное подтверждение и тестовая отправка.

### Цель

Безопасный **тестовый** outreach для лидов Stage 3 с `review_decision=APPROVED`: шаблоны, sequences ≤ 3 шагов, детерминированные черновики, ручное подтверждение, явная отправка только через `TestEmailProvider`, test outbox — без реальной внешней доставки и без scheduler auto-send.

### Модели

- `OutreachTemplate` — plain-text шаблон (allowlist variables)
- `OutreachSequence` + `OutreachSequenceStep` (1–3, unique step)
- `OutreachMessage` — черновик/сообщение со статусами DRAFT→APPROVED→SENDING→SENT | FAILED | BLOCKED | REJECTED
- `SendAttempt` — история тестовой отправки / outbox (unique idempotency)

### Получатель

Только `lead-<uuid>@example.test`. Другие домены отклоняются. Не из Contact.

### API (минимум)

- Templates / sequences CRUD под `/api/campaigns/{id}/outreach/...`
- `POST .../outreach/drafts`
- Messages list/detail + `approve` / `reject` / `send`

### Safety

- Provider только `TestEmailProvider` (сервер выбирает; пользователь не выбирает SMTP)
- Approve не шлёт; send явный и идемпотентный (atomic claim)
- `SYSTEM_STOP_ALL` перед claim → `BLOCKED`, provider не вызывается
- Шаблоны/approve при STOP разрешены
- Нет LLM, HTTP/SMTP, Contact, scheduler send

### Критерии готовности

Миграция `0005_safe_outreach`, unique constraints, mock-доказательство отсутствия send на draft/approve, тесты, Docker smoke, docs.

См. [STAGE4_SAFE_OUTREACH.md](STAGE4_SAFE_OUTREACH.md)

## Stage 5 — Safe Test Campaign Orchestration & Analytics

**Русское название:** Этап 5 — безопасный тестовый запуск кампаний и аналитика.

### Цель

Управляемый тестовый запуск группы Stage 4 `APPROVED` сообщений: snapshot run, ручные Start/Pause/Resume/Cancel, batch через Celery, только `TestEmailProvider`, тестовая аналитика — без реальной рассылки и без scheduler auto-start.

### Модели

- `CampaignExecutionRun` — запуск (`TEST_MANUAL_ONLY`), counters, timestamps
- `CampaignExecutionItem` — неизменяемый snapshot ссылок на `OutreachMessage`

### API

- `POST/GET /api/campaigns/{id}/execution-runs`
- Start / Pause / Resume / Cancel
- Items + `GET /api/campaigns/{id}/analytics`

### Safety

- Оркестратор вызывает Stage 4 send service (не дублирует provider)
- Recipient только `@example.test`
- `SYSTEM_STOP_ALL` → BLOCKED; no auto-retry UNKNOWN
- `beat_schedule` пуст

См. [STAGE5_TEST_ORCHESTRATION.md](STAGE5_TEST_ORCHESTRATION.md)

## Stage 6 — Compliance, Suppression & Provider Readiness

**Русское название:** Этап 6 — compliance-контур, стоп-листы и подготовка к подключению email-провайдера.

### Цель

Защитный слой перед ограниченным живым пилотом: suppression (global/campaign), compliance gate перед Stage 4 send и Stage 5 items, audit log, Provider Readiness Report — **без** реального provider и без live mode.

### Модели

- `SuppressionEntry` — GLOBAL/CAMPAIGN блокировки EMAIL/DOMAIN/COMPANY/CAMPAIGN_LEAD
- `ComplianceDecisionLog` — ALLOWED/BLOCKED/ERROR с безопасными details

### API

- `/api/compliance/suppressions` (+ deactivate/reactivate)
- `/api/campaigns/{id}/compliance/check`
- `/api/campaigns/{id}/compliance/test-events`
- `/api/compliance/provider-readiness` (+ validate)

### Safety

- Только `@example.test` и `TestEmailProvider`
- Suppression одного message блокирует item, не весь execution run
- `SYSTEM_STOP_ALL` по-прежнему блокирует весь run / send
- Secrets: present/missing; LIVE_NOT_READY
- `beat_schedule` пуст

См. [STAGE6_COMPLIANCE_READINESS.md](STAGE6_COMPLIANCE_READINESS.md)

## Stage 7A — Controlled Live Pilot Infrastructure (provider-neutral)

**Русское название:** Этап 7A — инфраструктура управляемого живого пилота (без реальной отправки).

### Цель

Подготовить систему к ограниченному live pilot: модели `LivePilot*`, allowlist, multi-gate approval, typed confirmation, dry-run через `TestEmailProvider`, `DisabledLiveEmailProvider` — **без** реальной отправки, credentials, network и выбора provider.

### Модели (migration `0008`)

- `LivePilot`, `LivePilotRecipient`, `LivePilotApproval`, `LivePilotEvent`, `LivePilotAllowlistEntry`

### API

- `/api/live-pilots` (+ validate, approve, cancel, dry-run, readiness, recipients)

### Safety

- `live_delivery_enabled` всегда `false` на 7A
- Daily/per-minute live limits = 0 на 7A
- Только `@example.test` allowlist
- Stage 6 compliance + `SYSTEM_STOP_ALL` не обходятся
- Нет live-send endpoint; `beat_schedule` пуст

См. [STAGE7_CONTROLLED_LIVE_PILOT.md](STAGE7_CONTROLLED_LIVE_PILOT.md), [STAGE7_PROVIDER_SELECTION.md](STAGE7_PROVIDER_SELECTION.md)

## Stage 8 — Production Hardening & Deployment

**Русское название:** Производственное усиление и готовность к развёртыванию.

Строгая production-конфигурация, liveness/readiness/metrics, structured logging, hardened Docker Compose + reverse proxy, backup/restore, CI, deployment runbooks — **без** обязательного VPS deploy и **без** реального email-провайдера.

См. [STAGE8_PRODUCTION_HARDENING_DEPLOYMENT.md](STAGE8_PRODUCTION_HARDENING_DEPLOYMENT.md), [DEPLOYMENT.md](../DEPLOYMENT.md).

## Статус roadmap (закрытие проекта)

| Stage | Название | Статус |
|---|---|---|
| 0–6 | Foundation → Compliance | **Done** |
| 7A | Controlled Live Pilot (provider-neutral) | **Done** |
| 7B | Owner-selected provider + one manual canary | **Pending / optional** — намеренно не выполнен |
| 8 | Production Hardening & Deployment | **Done** |
| 9 | — | **Не существует** |

Итоговый отчёт: [HOMEWORK_FINAL_REPORT.md](../HOMEWORK_FINAL_REPORT.md).
