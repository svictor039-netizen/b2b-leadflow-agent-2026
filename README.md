# B2B LeadFlow Agent 2026

Каркас проекта VCd03 — этап 0. Агент для B2B lead generation с тестовыми провайдерами, без реальной отправки писем и без реального поиска компаний.

## Стек

| Слой | Технологии |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic, SQLAlchemy, Alembic, Celery |
| Frontend | React 18, Vite 6, TypeScript, Tailwind CSS, TanStack Query, React Hook Form |
| Инфра | Docker Compose, PostgreSQL 16, Redis 7 |

## Быстрый старт

```bash
# 1. Скопировать переменные окружения
cp .env.example .env

# 2. Проверить конфигурацию Compose
docker compose config

# 3. Собрать и запустить все сервисы
docker compose up --build -d

# 4. Проверить health
curl http://localhost:8000/api/health
curl http://localhost:8000/api/readiness
```

Frontend: http://localhost:8080  
Swagger UI: http://localhost:8000/docs

## Локальная разработка (без Docker)

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
SKIP_INTEGRATION=1 pytest
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
npm run build
```

## Сервисы Docker Compose

| Сервис | Порт | Назначение |
|---|---|---|
| frontend | 8080 | React dashboard (nginx) |
| backend | 8000 | FastAPI API |
| worker | — | Celery worker (ping) |
| scheduler | — | Celery beat (пустой schedule) |
| postgres | 5432 | БД |
| redis | 6379 | Брокер Celery / кэш |

## API (этап 0)

- `GET /api/health` — liveness
- `GET /api/readiness` — postgres + redis
- `GET /api/version` — версия и stage
- `GET /docs` — Swagger UI

## MVP-ограничения

См. [docs/VCd03_SPEC.md](docs/VCd03_SPEC.md) и [SECURITY.md](SECURITY.md).

## Документация

- [SECURITY.md](SECURITY.md) — политика безопасности
- [DEPLOYMENT.md](DEPLOYMENT.md) — деплой (placeholder)
- [HOMEWORK_REPORT.md](HOMEWORK_REPORT.md) — отчёт этапа 0

## Тесты

```bash
# Backend (unit, без интеграции)
cd backend && SKIP_INTEGRATION=1 pytest -v

# Backend (с postgres/redis — в Docker или локально)
cd backend && pytest -v

# Frontend build
cd frontend && npm run build
```

## Аварийная остановка

```env
SYSTEM_STOP_ALL=true
```

Блокирует исходящие email-операции в `TestEmailProvider` и Celery-задаче `simulated_send`.
