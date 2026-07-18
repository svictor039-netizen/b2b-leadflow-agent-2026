# Security Policy — B2B LeadFlow Agent

## Current posture (Stages 0–8, safe demo)

Система работает в **безопасном demo / production-like** режиме. Реальная холодная рассылка, SMTP/IMAP live credentials, Stage 7B canary и реальный VPS deploy **не активированы** в рамках сдачи. Stage 9 не существует.

Исторически Stage 0 зафиксировал тестовый baseline; ниже — актуальные правила для всего roadmap.

## Secrets

- Файл `.env` **не коммитится** (см. `.gitignore`).
- В репозитории только `.env.example` с dev-значениями-заглушками.
- Секреты **не копируются** в Docker-образы (`.dockerignore`).
- `DATABASE_URL`, `REDIS_URL`, пароли и API-ключи **фильтруются** в логах (`app/logging/setup.py`).

## CORS

Разрешён только origin из переменной `FRONTEND_ORIGIN` (по умолчанию `http://localhost:8080`).

## Emergency stop

```env
SYSTEM_STOP_ALL=true
```

При включении блокируются:

- `TestEmailProvider.send()`
- Celery-задача `simulated_send`

## MVP safety rules

| Правило | Реализация (stage 0) |
|---|---|
| Нет реальной отправки | `TestEmailProvider` — симуляция |
| Нет реального поиска | `TestSourceAdapter` — demo-данные |
| Ручное подтверждение | Будет на этапе 1+ (UI placeholder) |
| LLM не запускает отправку | LLM не подключён |
| Max 30 компаний | Константа в adapter (limit) |
| Max 3 письма | Зафиксировано в spec, enforcement — этап 1+ |

## Reporting vulnerabilities

На этапе 0 проект локальный. Для production-деплоя (будущие этапы) — сообщать ответственному за инфраструктуру напрямую.

## Do not

- Коммитить `.env`, ключи, пароли
- Включать SMTP/IMAP без явного разрешения в ТЗ
- Логировать connection strings и tokens
- Отключать `SYSTEM_STOP_ALL` guard в production без review
