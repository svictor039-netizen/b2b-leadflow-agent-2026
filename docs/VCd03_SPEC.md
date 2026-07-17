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
