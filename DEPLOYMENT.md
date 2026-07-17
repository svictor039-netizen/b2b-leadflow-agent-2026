# Deployment Guide — Stage 0

> **Этап 0 не включает деплой.** Этот документ описывает placeholder-артефакты и план для будущих этапов.

## Текущее состояние

- Локальный запуск через `docker compose up --build`
- Файлы в `deploy/` — заглушки:
  - `docker-compose.prod.yml` — overlay для production env
  - `nginx.conf` — reverse proxy backend + frontend
  - `update-leadflow.sh` — скрипт обновления (exit 0, no-op)

## Локальный Docker Compose

```bash
cp .env.example .env
docker compose config
docker compose up --build -d
docker compose ps
docker compose logs -f backend
```

## Production checklist (future stages)

1. Сгенерировать сильные пароли для PostgreSQL
2. Установить `ENVIRONMENT=production`, `DEBUG=false`
3. Настроить TLS (Let's Encrypt / reverse proxy)
4. Ограничить `FRONTEND_ORIGIN` production-доменом
5. Убедиться, что `SYSTEM_STOP_ALL=false` только после review
6. Настроить backup PostgreSQL volume
7. Настроить мониторинг health/readiness

## Volumes

| Volume | Данные |
|---|---|
| `postgres_data` | PostgreSQL |
| `redis_data` | Redis AOF |

## Порты по умолчанию

| Сервис | Порт |
|---|---|
| Frontend | 8080 |
| Backend | 8000 |
| PostgreSQL | 5432 |
| Redis | 6379 |

## Не выполнять на этапе 0

- Push Docker-образов в registry
- Деплой на VPS
- GitHub Actions CI/CD
- Публикация секретов
