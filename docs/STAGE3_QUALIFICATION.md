# Stage 3 — Safe Lead Qualification & Deterministic Scoring

> Этап 3 — безопасная квалификация и детерминированная оценка лидов.

## Цель

Преобразовать компании из завершённого Stage 2 `ResearchRun` в `CampaignLead` конкретной кампании, безопасно дополнить их только уже сохранёнными тестовыми данными и присвоить каждому лиду объяснимый score **0–100** без LLM и без email.

## Архитектура

```
COMPLETED ResearchRun (test)
        │ provenance via CompanySourceRecord.research_run_id
        ▼
QualificationRun ──► create/find CampaignLead (unique campaign+company)
        │
        ▼
scoring engine stage3-v1 ──► LeadScoreSnapshot + lead.score_reasons
        │
        ▼
manual review PENDING / APPROVED / REJECTED  (no email)
```

## Модели

### QualificationRun

`id`, `campaign_id`, `research_run_id`, `status`, `scoring_version`, counters, `started_at`, `finished_at`, `error_message`, `is_test_data`, timestamps.

Statuses: `PENDING` → `RUNNING` → `COMPLETED` | `FAILED` | `BLOCKED`.

### CampaignLead (расширение Stage 1)

Уже было: unique `(campaign_id, company_id)`.

Добавлено: `qualification_score`, `qualification_status`, `review_decision`, `score_version`, `scored_at`, `score_reasons`, `source_research_run_id`, `is_test_data`, `reviewed_at`, `review_note`.

### LeadScoreSnapshot

Unique `(qualification_run_id, campaign_lead_id)`. Хранит score, status, reasons, sanitized `input_snapshot`.

## Scoring rubric (`stage3-v1`)

| Правило | Баллы |
|---|---|
| DOMAIN_PRESENT | +20 |
| DOMAIN_SUSPICIOUS | −10 |
| INDUSTRY_MATCH / PARTIAL | +25 / +12 |
| LOCATION_MATCH | +20 |
| PROFILE_COMPLETENESS | до +15 |
| PROVENANCE_CONFIRMED | +10 |
| MULTI_SOURCE | +10 |
| DOMAIN_CONFLICT | −20 |
| NAME_MISSING | −25 |
| PROVENANCE_MISSING | −15 |

Итог clamp **0–100**:

- 70–100 → QUALIFIED
- 40–69 → REVIEW
- 0–39 → DISQUALIFIED

Одинаковые входы + version → одинаковый score. Reasons всегда сохраняются.

## API

| Method | Path |
|---|---|
| POST | `/api/qualification/runs` |
| GET | `/api/qualification/runs/{run_id}` |
| GET | `/api/campaigns/{campaign_id}/leads` |
| POST | `/api/campaigns/{campaign_id}/leads/{lead_id}/review` |
| GET | `/api/research/runs` (список для UI) |

## Celery

`run_qualification_task(run_id)` — `max_retries=0`, идемпотентна для terminal runs. Scheduler `beat_schedule` пуст.

## Frontend

В карточке кампании: `QualificationPanel` — выбор COMPLETED research, запуск qualification, таблица лидов, фильтры, Approve/Reject/Reset. Без кнопок email.

## Safety / SYSTEM_STOP_ALL

- Только test data / provenance Stage 2
- Kill switch читается перед execute → `BLOCKED` + `finished_at`, scoring не вызывается
- TestEmailProvider не вызывается на qualify/review
- Snapshots через `sanitize_payload`
- Нет Contact / personal email из Stage 3

## Идемпотентность и конкуренция

- Атомарный claim: `UPDATE qualification_runs SET status=RUNNING WHERE id=? AND status=PENDING` (только один worker)
- RUNNING не перезапускается без recovery; terminal (COMPLETED/FAILED/BLOCKED) → no-op
- Unique campaign+company + IntegrityError/savepoint
- Unique run+lead snapshot
- Повторный **новый** QualificationRun: `created_leads_count=0`, matched leads

## Mid-run failure (all-or-nothing)

Семантика **A**: обработка после claim идёт в одной транзакции. При ошибке:

1. `rollback` снимает незакоммиченные leads/snapshots этого run;
2. отдельной транзакцией run → `FAILED` + `finished_at`;
3. повтор = **новый** QualificationRun (FAILED terminal no-op).

## Counters

```
found_count = created_leads_count + matched_leads_count + skipped_count
scored_count = qualified_count + review_count + disqualified_count
conflict_count ≤ scored_count   # флаг domain conflict среди scored, не отдельный bucket
```

## Manual review vs SYSTEM_STOP_ALL

Ручной review (`APPROVED`/`REJECTED`/`PENDING`) **разрешён** при `SYSTEM_STOP_ALL=true`: это локальная классификация без outbound. Автоматический qualification при STOP → `BLOCKED`.

## Alembic

Revision: `0004_qualification` (после `0003_research_runs`).

## Smoke

```bash
docker compose up -d --build
docker compose exec backend python /app/scripts/smoke_stage3.py
# или test DB:
docker compose exec -e DATABASE_URL=.../leadflow_test -e PYTHONPATH=/app \
  backend python /app/scripts/smoke_stage3_testdb.py
docker compose stop
```

## Ограничения (не Stage 3)

Шаблоны писем, генерация, sequences, любая отправка (в т.ч. TestEmailProvider), реальные провайдеры, outreach, scheduler рассылок → **Stage 4**.
