# Stage 8 — Production Hardening & Deployment

**Русское название:** Производственное усиление и готовность к развёртыванию  
**Версия:** 0.9.0-stage8  
**Статус:** Реализован (без commit/push/PR)

---

## Цель

Подготовить B2B LeadFlow Agent к безопасному production-развёртыванию: строгая конфигурация, operational endpoints, structured logging, метрики, hardened Docker stack, backup/restore, CI и runbooks — **без** подключения реального email-провайдера и **без** реальных отправок.

Stage 8 выполняется независимо от Stage 7B (выбор провайдера и ручной canary).

---

## Scope

| # | Область | Реализация |
|---|---------|------------|
| 1 | Production configuration | `app/core/production_validation.py`, `.env.production.example`, fail-fast при старте |
| 2 | Health / liveness / readiness | `/api/health`, `/api/liveness`, `/api/readiness` с migration check |
| 3 | Structured logging | JSON logs, `X-Request-ID`, redaction секретов/PII |
| 4 | Monitoring metrics | `/api/metrics` (Prometheus), HTTP + operational gauges |
| 5 | Docker production hardening | `docker-compose.prod.yml`, nginx reverse proxy, internal networks |
| 6 | Backup / restore PostgreSQL | `scripts/backup_postgres.sh`, `restore_postgres.sh`, `verify_backup.sh` |
| 7 | Deployment runbooks | `DEPLOYMENT.md` |
| 8 | CI verification | `.github/workflows/ci.yml` |
| 9 | Stage 8 smoke | `backend/scripts/smoke_stage8.py` |

---

## Out of scope

- Stage 7B, выбор реального email-провайдера
- Ввод SMTP/API credentials, реальная отправка писем
- Массовые кампании, покупка домена, выпуск TLS-сертификатов
- Фактический deploy на VPS, Kubernetes, Terraform, cloud autoscaling
- Ослабление approval, allowlist, suppression, compliance, idempotency, audit

---

## Архитектура

```
                    ┌─────────────────────────────────────┐
                    │  Reverse proxy (nginx) — :8080      │
                    │  единственная внешняя точка входа   │
                    └──────────────┬──────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
              ▼                    ▼                    ▼
        /api/* → backend      /docs → backend    / → frontend
        (internal network)    (no public ports)
              │
    ┌─────────┴─────────┬──────────────┐
    ▼                   ▼              ▼
 PostgreSQL          Redis      worker / scheduler
 (internal only)   (internal)   (Celery, no beat tasks)
```

**Production startup flow:**

1. Load settings (`ENVIRONMENT=production`)
2. `validate_production_settings()` — fail-fast при небезопасной конфигурации
3. Alembic migrations (backend entrypoint)
4. Uvicorn + middleware (request ID, metrics, access log)
5. Readiness проверяет PostgreSQL, Redis, Alembic head

**Observability:**

- Logs: JSON → stdout, `request_id` в каждой записи, redaction фильтр
- Metrics: Prometheus scrape `/api/metrics` (internal/monitoring only в prod compose)
- Audit events Stage 0–7: без изменений, не заменяются обычными логами

---

## Safety guarantees

| Гарантия | Механизм |
|----------|----------|
| `SYSTEM_STOP_ALL` высший приоритет | Не ослабляется; `.env.production.example` → `true` |
| Live provider отключён | Validation блокирует enabled flags и credentials |
| Нет реальных отправок в smoke | Smoke использует backup/restore и HTTP checks only |
| Секреты не в logs/health/metrics/errors | Redaction filter + safe response payloads |
| Backup не перезаписывает production | Restore только в явно указанную test DB |
| Stage 0–7 controls сохранены | Без изменений бизнес-логики кампаний |

---

## Acceptance criteria

1. Ветка `feature/stage-8-production-hardening-deployment` от актуального `main`
2. Документ Stage 8 создан
3. Production config validation покрыта тестами
4. Liveness/readiness работают и покрыты тестами
5. Readiness возвращает неуспешный HTTP при недоступности PostgreSQL/Redis/migrations
6. Логи содержат request id и не раскрывают secrets
7. Метрики доступны и не содержат PII/secrets
8. `docker compose config` проходит
9. Production compose config проходит
10. Production-like stack запускается локально
11. Backend suite полностью проходит
12. Frontend build проходит
13. Migration verification проходит
14. Backup создаётся
15. Backup проверяется restore во временную базу
16. Stage 8 smoke проходит
17. `live_sent=0`
18. `SYSTEM_STOP_ALL=true` в production example
19. Code review без BLOCKER/HIGH
20. Working tree содержит только изменения Stage 8

---

## Deployment flow

См. `DEPLOYMENT.md`. Кратко:

1. Pre-deploy checklist (backup, secrets, `SYSTEM_STOP_ALL`)
2. `git pull` + `docker compose -f docker-compose.yml -f docker-compose.prod.yml build`
3. Backup PostgreSQL (`scripts/backup_postgres.sh`)
4. `docker compose ... up -d`
5. Verify `/api/readiness` → 200
6. Run Stage 8 smoke
7. Post-deploy verification (metrics, logs, `live_sent=0`)

---

## Rollback flow

1. `SYSTEM_STOP_ALL=true` (emergency stop)
2. `docker compose ... down` backend/worker/scheduler
3. Deploy previous image tag / git ref
4. Migration rollback **только** если downgrade безопасен (документировано per revision)
5. Database restore — отдельная аварийная процедура (не автоматический rollback)

---

## Backup / restore flow

| Шаг | Команда |
|-----|---------|
| Backup | `./scripts/backup_postgres.sh` |
| Verify | `./scripts/verify_backup.sh <backup-file>` |
| Restore (test only) | `./scripts/restore_postgres.sh --target-db leadflow_restore_test <backup-file>` |

**Retention (документировано):** daily 7d, weekly 4w, monthly 12m — оператор настраивает cron на VPS.

**Защита production:** restore script требует `--target-db` ≠ production DB name и `--i-understand`.

---

## Monitoring flow

1. Prometheus scrape `http://backend:8000/api/metrics` (internal network)
2. Alerts на `leadflow_readiness_state == 0`
3. Dashboards: HTTP latency/errors, live pilot counters (aggregates only)
4. Logs: aggregate by `request_id` для incident triage

---

## Тестовый план

| Тест | Команда |
|------|---------|
| Unit + integration | `cd backend && pytest` |
| Migration | `pytest tests/test_migrations.py` |
| Production config | `pytest tests/test_production_config.py tests/test_stage8_operations.py` |
| Frontend build | `cd frontend && npm run build` |
| Compose dev | `docker compose config` |
| Compose prod | `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` |
| Prod-like up | `docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production.example up -d` |
| Stage 8 smoke | `docker compose exec backend python scripts/smoke_stage8.py` |
| Backup verify | `./scripts/verify_backup.sh backups/latest.dump` |

---

## Миграции

**No database migration required.**

Stage 8 добавляет только operational слой (config, health, metrics, Docker, scripts). Схема БД не меняется.

---

## Связанные файлы

- `.env.production.example` — безопасный production template
- `docker-compose.prod.yml` — production overlay
- `deploy/nginx.prod.conf` — reverse proxy
- `DEPLOYMENT.md` — runbooks
- `.github/workflows/ci.yml` — CI pipeline
