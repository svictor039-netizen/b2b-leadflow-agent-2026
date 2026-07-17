# Stage 2 — Safe Research, Provenance & Deduplication

**Статус:** TestSourceAdapter only. Реальные email и production-источники запрещены.

## Архитектура

```
POST /api/research/runs
        │
        ▼
 research_service.start_research
        │
        ├─ SYSTEM_STOP_ALL? → status=BLOCKED
        │
        ├─ get_source_adapter("test_source")  # only allowed
        │
        ├─ TestSourceAdapter.search(niche, region, limit)
        │
        ├─ for each CompanyRecord:
        │     dedup.resolve_match (domain | source_id | name+location fallback)
        │     merge empty fields only
        │     write CompanySourceRecord (provenance)
        │
        └─ ResearchRun COMPLETED with counts + result_items
```

Опционально `async_mode=true` → Celery `run_research_task` (тот же `execute_research_run`).

Scheduler **не** планирует research автоматически.

## API

### POST /api/research/runs

```json
{
  "query": "SaaS",
  "industry": "B2B SaaS",
  "location": "Northern Europe",
  "limit": 10,
  "adapter": "test_source",
  "campaign_id": null,
  "async_mode": false
}
```

Ответ: `run_id`, `status`, `adapter`, query params, counts (`found/created/matched/updated/skipped/conflict`), `result_items`, `error_message`.

### GET /api/research/runs/{run_id}

Возвращает сохранённый результат запуска.

## Provenance

Для каждой записи `company_source_records`:

| Поле | Смысл |
|---|---|
| `data_source.name` | `test_source` |
| `external_id` | `source_record_id` адаптера |
| `source_url` | URL тестового каталога |
| `query_text` | исходный query |
| `research_run_id` | id запуска |
| `collected_at` | UTC |
| `is_test_data` | всегда `true` |
| `raw_payload` | snapshot без секретов и без сырого email (только `has_contact_email`) |

## Нормализация

- **name**: NFKC, collapse spaces, lowercase (для сравнения; display name не портится)
- **domain**: lowercase, strip protocol/`www`/path/trailing dot
- **website**: trim; хранится как пришло (безопасный http/https)
- **location**: NFKC + lowercase для fallback
- **source_record_id**: trim

## Дедупликация

**Сильные ключи (в порядке):**

1. `(data_source_id, external_id)`
2. нормализованный `domain`

**Fallback** (только если domain отсутствует):

- нормализованное имя + location

**Не** объединять только по похожему имени при разных domain.

**Outcomes:** `created` | `matched_existing` | `updated` | `skipped` | `conflict`

**Conflict:** тот же `source_record_id`, но domain компании уже другой.

**Merge:** пустые новые поля не затирают заполненные старые; provenance дополняется.

## Safety

- Единственный adapter Stage 2: `test_source` (`TestSourceAdapter`)
- Все записи `is_test_data=true`
- Research pipeline **не** вызывает `TestEmailProvider` / SMTP
- `SYSTEM_STOP_ALL=true` → run `BLOCKED`, исследование не выполняется
- limit ≤ 30; пустой query запрещён
- Секреты не логируются; email не кладётся в `raw_payload`

## Alembic

Revision: `0003_research_runs` (после `0002_campaigns_companies`)

- таблица `research_runs`
- поля provenance на `company_source_records`
- unique `(data_source_id, external_id)`
- partial unique на `companies.domain`

## Примеры

```bash
curl -X POST http://localhost:8000/api/research/runs \
  -H "Content-Type: application/json" \
  -d '{"query":"SaaS","industry":"B2B SaaS","location":"Northern Europe","limit":5,"adapter":"test_source"}'

curl http://localhost:8000/api/research/runs/<run_id>
```

Повтор того же запроса не создаёт дубликаты компаний.

## Известные ограничения

- Нет реального поиска / scraping / enrichment
- Нет сбора реальных email для outreach
- Name-fallback срабатывает только без domain
- Frontend research UI на Stage 2 не обязателен (API + docs)
