# B2B LeadFlow Agent 2026

Проект VCd03 «Создание автономного агента» — безопасный B2B leadflow:

- Stage 0–6: foundation → research → qualification → test outreach → orchestration → compliance
- **Stage 7A:** Controlled Live Pilot infrastructure (без реальной отправки)
- **Stage 7B:** Owner-selected provider + one manual canary — **optional / pending**, не выполнен
- **Stage 8:** Production Hardening & Deployment (без обязательного VPS deploy)

**Safe demo mode:** live provider disabled, реальные письма и реальный VPS deploy не выполнялись.

**Stage 9 не существует.**

Итоговый отчёт для сдачи: [HOMEWORK_FINAL_REPORT.md](HOMEWORK_FINAL_REPORT.md)

Чеклист демо: [docs/FINAL_DEMO_CHECKLIST.md](docs/FINAL_DEMO_CHECKLIST.md)

## Стек

| Слой | Технологии |
|------|------------|
| Backend | Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, Celery |
| Frontend | React 18, Vite 6, TypeScript, Tailwind CSS, TanStack Query, React Hook Form |
| Инфра | Docker Compose, PostgreSQL 16, Redis 7, nginx (prod overlay), GitHub Actions |

## Быстрый старт (safe demo)

```bash
cp .env.example .env
docker compose config
docker compose up --build -d

curl http://localhost:8000/api/health
curl http://localhost:8000/api/liveness
curl http://localhost:8000/api/readiness
curl http://localhost:8000/api/campaigns
```

- Frontend: http://localhost:8080
- Swagger: http://localhost:8000/docs

Backend при старте выполняет `alembic upgrade head` (только сервис `backend`).

### Production-like (локально, без реального VPS)

```bash
PRODUCTION_ENV_FILE=.env.production.smoke \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  --env-file .env.production.smoke up -d --build
```

В smoke-окружении: `SYSTEM_STOP_ALL=true`, live flags выключены, credentials пустые.

## Alembic

```bash
docker compose exec backend alembic current
docker compose exec backend alembic heads
docker compose exec backend alembic upgrade head
```

Ревизии: `0001` → `0002` → `0003` → `0004` → `0005` → `0006` → `0007` → `0008_controlled_live_pilot`.

Stage 8 миграций не добавлял.

## Правила безопасности (кратко)

- `SYSTEM_STOP_ALL` имеет высший приоритет
- Outreach: manual approval + TestEmailProvider (тест)
- Compliance / suppression (Stage 6) не обходятся
- Live pilot (7A): allowlist `@example.test`, dry-run only; **нет live-send API**
- Stage 7B (реальный provider / canary) — только после явного решения владельца
- Секреты не коммитятся (`.env`, `.env.production` в `.gitignore`)

## Demo seed

```bash
docker compose exec backend python -m app.scripts.seed_demo_data
```

Идемпотентно; адреса только `@*.example.com`. Не запускается автоматически.

## Тесты и smoke

```bash
# Backend (рекомендуется в контейнере на Windows)
docker compose exec backend sh -c 'export TEST_DATABASE_URL="${DATABASE_URL%/leadflow}/leadflow_test"; pytest -q'

# Frontend
cd frontend && npm run build

# Smoke
docker compose exec backend python scripts/smoke_stage7_testdb.py
docker compose exec backend python scripts/smoke_stage8.py
```

Ожидаемо в smoke: `live_sent=0`.

## Документация

- [HOMEWORK_FINAL_REPORT.md](HOMEWORK_FINAL_REPORT.md) — итоговый отчёт сдачи
- [docs/FINAL_DEMO_CHECKLIST.md](docs/FINAL_DEMO_CHECKLIST.md) — чеклист демонстрации
- [docs/VCd03_SPEC.md](docs/VCd03_SPEC.md) — спецификация этапов
- [docs/STAGE2_RESEARCH.md](docs/STAGE2_RESEARCH.md) … [docs/STAGE8_PRODUCTION_HARDENING_DEPLOYMENT.md](docs/STAGE8_PRODUCTION_HARDENING_DEPLOYMENT.md)
- [docs/STAGE7_PROVIDER_SELECTION.md](docs/STAGE7_PROVIDER_SELECTION.md) — подготовка к 7B (не активация)
- [DEPLOYMENT.md](DEPLOYMENT.md) — runbooks (без фактического VPS в рамках ДЗ)
- [SECURITY.md](SECURITY.md)
- Per-stage: `HOMEWORK_REPORT.md`, `HOMEWORK_REPORT_STAGE2.md` … `HOMEWORK_REPORT_STAGE7A.md`

## Roadmap status

| Stage | Status |
|-------|--------|
| 0–6 | Done |
| 7A Controlled Live Pilot | Done |
| 7B Provider + canary | **Pending / optional (owner)** |
| 8 Production Hardening | Done |
| 9 | **Does not exist** |
