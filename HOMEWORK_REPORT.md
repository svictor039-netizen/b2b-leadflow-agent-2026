# HOMEWORK REPORT — VCd03 Stage 0

**Проект:** B2B LeadFlow Agent 2026  
**Этап:** 0 — каркас  
**Дата:** 2026-07-17  
**Статус:** `READY_FOR_STAGE_1`

---

## 1. Созданные файлы

```
.
├── .env.example
├── .gitignore
├── README.md
├── SECURITY.md
├── DEPLOYMENT.md
├── HOMEWORK_REPORT.md
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/0001_stage0_baseline.py
│   ├── app/
│   │   ├── main.py
│   │   ├── api/ (health, router)
│   │   ├── agents/
│   │   ├── services/
│   │   ├── providers/ (base, email_test, source_test)
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── workers/ (celery_app, tasks)
│   │   ├── security/ (stop_all)
│   │   ├── logging/ (setup, secret filter)
│   │   └── core/ (config, database, redis, exceptions, middleware)
│   └── tests/ (6 test modules)
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── src/ (App, Layout, HealthStatus, TestModeBanner, SettingsPlaceholder, …)
├── deploy/
│   ├── docker-compose.prod.yml
│   ├── nginx.conf
│   └── update-leadflow.sh
└── docs/
    └── VCd03_SPEC.md
```

---

## 2. Архитектура

```
┌─────────────┐     /api/*      ┌─────────────┐
│  Frontend   │ ──────────────► │   Backend   │
│  (React +   │   nginx proxy   │  (FastAPI)  │
│   nginx)    │                 └──────┬──────┘
└─────────────┘                        │
                                       ├── PostgreSQL (SQLAlchemy + Alembic)
                                       ├── Redis (readiness + Celery broker)
                                       │
                    ┌──────────────────┴──────────────────┐
                    │                                     │
              ┌─────▼─────┐                         ┌─────▼─────┐
              │  Worker   │                         │ Scheduler │
              │  (Celery) │                         │(Celery    │
              │  ping     │                         │ beat, ∅)  │
              └───────────┘                         └───────────┘
```

**Слои backend:**

| Слой | Назначение (stage 0) |
|---|---|
| `api/` | HTTP endpoints: health, readiness, version |
| `providers/` | `EmailProvider`, `SourceAdapter` + test-реализации |
| `workers/` | Celery app, ping + simulated_send (с guard) |
| `security/` | `SYSTEM_STOP_ALL` блокировка исходящих операций |
| `logging/` | JSON-логи + redaction секретов |
| `core/` | Settings, DB, Redis, middleware (Request ID), CORS |

**Frontend:** SPA Dashboard с адаптивной боковой навигацией, TanStack Query для health/readiness, React Hook Form в разделе «Настройки».

---

## 3. Версии зависимостей

### Backend (`requirements.txt`)

| Пакет | Версия |
|---|---|
| Python (Docker) | 3.11 |
| fastapi | 0.115.6 |
| uvicorn | 0.34.0 |
| pydantic | 2.10.4 |
| pydantic-settings | 2.7.0 |
| sqlalchemy | 2.0.36 |
| psycopg2-binary | 2.9.10 |
| alembic | 1.14.0 |
| redis | 5.2.1 |
| celery | 5.4.0 |
| httpx | 0.28.1 |
| python-json-logger | 3.2.1 |
| pytest | 8.3.4 |

### Frontend (`package.json`)

| Пакет | Версия |
|---|---|
| react | ^18.3.1 |
| vite | ^6.0.5 |
| typescript | ~5.6.3 |
| tailwindcss | ^3.4.17 |
| @tanstack/react-query | ^5.62.8 |
| react-hook-form | ^7.54.2 |

### Infrastructure

| Сервис | Образ |
|---|---|
| PostgreSQL | postgres:16-alpine |
| Redis | redis:7-alpine |
| Frontend runtime | nginx:1.27-alpine |

---

## 4. Результаты проверок

### Backend unit tests

```
12 passed, 1 skipped in 1.40s
```

| Тест | Результат |
|---|---|
| health | PASSED |
| version | PASSED |
| readiness (integration) | SKIPPED (SKIP_INTEGRATION=1, нет live postgres/redis) |
| secret filter (3 tests) | PASSED |
| TestEmailProvider | PASSED |
| TestSourceAdapter | PASSED |
| SYSTEM_STOP_ALL (email + celery) | PASSED |
| stop_all helpers | PASSED |

### Frontend production build

```
✓ tsc --noEmit
✓ vite build — 81 modules, built in 2.55s
Exit code: 0
```

### docker compose config

```
Exit code: 0
```

Все 6 сервисов (frontend, backend, worker, scheduler, postgres, redis) валидны. Volumes, healthchecks, log rotation (10m × 3 files), `restart: unless-stopped` — на месте.

### docker compose up --build (runtime, 2026-07-17)

После запуска Docker Desktop контейнеры подняты и проверены. Изначально `frontend`, `worker` и `scheduler` были **unhealthy** из‑за неверных healthcheck — исправлено (см. §4.1).

### Health / Readiness (runtime)

| Endpoint | Результат |
|---|---|
| `GET http://localhost:8080/` | HTTP **200** |
| `GET /api/health` | `{"status":"ok","service":"B2B LeadFlow Agent"}` |
| `GET /api/readiness` | `{"status":"ready","checks":{"postgres":"ok","redis":"ok"}}` |

### docker compose ps (после фикса healthcheck)

| SERVICE | STATUS |
|---|---|
| backend | Up (healthy) |
| frontend | Up (healthy) |
| postgres | Up (healthy) |
| redis | Up (healthy) |
| worker | Up (без healthcheck) |
| scheduler | Up (без healthcheck) |

Ни один контейнер не имеет статус `unhealthy`.

### Worker / scheduler logs (фрагмент)

- worker: `Connected to redis://redis:6379/0` → `celery@… ready.`
- scheduler: `beat: Starting...` (пустой schedule, как задумано на этапе 0)
- frontend healthcheck: `GET / HTTP/1.1" 200` от `127.0.0.1` (Wget)

---

## 4.1. Исправление Docker healthcheck (follow-up)

### Причины unhealthy

| Сервис | Причина |
|---|---|
| **frontend** | Healthcheck ходил на `http://localhost/` (часто IPv6 `::1`); nginx слушает IPv4 на порту **80** внутри контейнера. Хостовый порт **8080** внутри контейнера не слушается → `wget: can't connect … Connection refused`. |
| **worker** | Наследовал `HEALTHCHECK` из `backend/Dockerfile` (`curl :8000/api/health`), хотя FastAPI в worker не запускается. |
| **scheduler** | Та же унаследованная HTTP-проверка порта 8000. |

### Изменённые файлы

- `frontend/Dockerfile` — probe `http://127.0.0.1:80/`
- `docker-compose.yml` — frontend healthcheck на `127.0.0.1:80`; у worker/scheduler `healthcheck: disable: true`
- `HOMEWORK_REPORT.md` — фактические runtime-результаты

### Новая конфигурация

```yaml
# frontend (compose + Dockerfile)
healthcheck:
  test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:80/"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 10s

# worker / scheduler
healthcheck:
  disable: true
```

Обязательные healthcheck по ТЗ этапа 0 остаются у **backend**, **postgres**, **redis** (и корректный у **frontend**).

---

## 5. Реализованные требования этапа 0

- [x] FastAPI: health, readiness, version, Swagger UI
- [x] Pydantic Settings, PostgreSQL, Redis check
- [x] Request ID middleware, structured JSON logging, secret filter
- [x] CORS через `FRONTEND_ORIGIN`
- [x] Frontend Dashboard + health indicators + empty sections
- [x] TestEmailProvider, TestSourceAdapter (5 demo companies)
- [x] Celery worker (ping), scheduler (empty beat_schedule)
- [x] SYSTEM_STOP_ALL guard
- [x] docker-compose.yml с 6 сервисами
- [x] .env.example, .gitignore, SECURITY.md, DEPLOYMENT.md, docs/VCd03_SPEC.md
- [x] Backend tests + frontend build
- [x] Docker runtime verification (healthy backend/postgres/redis/frontend; worker/scheduler Up без ложного HTTP-healthcheck)

---

## 6. Известные ограничения

1. **Worker/scheduler** — без Docker healthcheck (намеренно; HTTP-probe к FastAPI был ложным).
2. **Integration test readiness** — при локальном `SKIP_INTEGRATION=1` пропускается; в Docker readiness = ready.
3. **Alembic migration** — baseline без таблиц (stage 0).
4. **Авторизация** — не реализована (этап 1+).
5. **Реальная отправка / поиск** — намеренно отсутствуют.
6. **Локальные тесты** выполнены на Python 3.13 (Windows); Docker использует Python 3.11.
7. Celery worker warning о запуске от root — типично для stage 0, не блокирует.

---

## 7. Git status

```
On branch main
No commits yet

Untracked files:
  .env.example
  .gitignore
  DEPLOYMENT.md
  HOMEWORK_REPORT.md
  README.md
  SECURITY.md
  backend/
  deploy/
  docker-compose.yml
  docs/
  frontend/
```

- `.env` — **не** в списке (корректно игнорируется)
- Commit / push — **не выполнялись** (по заданию)

---

## 8. Команды проверки

```bash
docker compose config
docker compose up --build -d frontend worker scheduler
docker compose ps
docker compose logs --tail=80 frontend worker scheduler
curl http://localhost:8080
curl http://localhost:8000/api/health
curl http://localhost:8000/api/readiness
```

Frontend: http://localhost:8080  
Swagger: http://localhost:8000/docs

---

## 9. Вердикт

**`READY_FOR_STAGE_1`**

Каркас этапа 0 работает в Docker: backend/postgres/redis/frontend — healthy; worker connected/ready; scheduler beat запущен; API health/readiness и frontend HTTP 200 подтверждены. Ложные healthcheck у worker/scheduler отключены; frontend probe исправлен на внутренний `127.0.0.1:80`.
