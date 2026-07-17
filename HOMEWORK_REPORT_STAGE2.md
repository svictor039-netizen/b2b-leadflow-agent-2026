# HOMEWORK REPORT — VCd03 Stage 2

**Проект:** B2B LeadFlow Agent 2026
**Этап:** 2 — Safe Research + Provenance + Deduplication
**Ветка:** `feature/stage-2-safe-research-dedup`
**Статус:** `READY_FOR_COMMIT`

## Аудит (кратко)

- Stage 1 уже дал `Company`, `CampaignLead`, `DataSource`, `CompanySourceRecord`.
- Не хватало: `ResearchRun`, связи provenance→run, unique по domain/source_external_id, сервиса research/dedup, API.
- Prisma нет (SQLAlchemy/Alembic). Миграция **нужна**: `0003_research_runs`.

## Что сделано

- Safe research через **только** `TestSourceAdapter`
- Provenance на `company_source_records`
- Нормализация + дедуп (domain / source_id / name+location fallback)
- API `POST/GET /api/research/runs`
- Celery `run_research_task` + уважение `SYSTEM_STOP_ALL`
- Тесты Stage 2; Stage 0/1 сохранены
- Документ `docs/STAGE2_RESEARCH.md`

## Проверки

| Check | Result |
|---|---|
| pytest | **52 passed** |
| frontend build | OK |
| docker compose config | OK |
| alembic current | `0003_research_runs (head)` |
| health/readiness | ok / ready |
| smoke stage2 | SMOKE_STAGE2_OK (повторный run created=0) |

Commit/push/merge не выполнялись.
