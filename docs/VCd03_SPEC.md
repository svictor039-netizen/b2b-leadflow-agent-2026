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
