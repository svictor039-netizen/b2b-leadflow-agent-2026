# Stage 4 — Safe Outreach Templates, Manual Approval & Test Delivery

> Этап 4 — безопасные шаблоны писем, ручное подтверждение и тестовая отправка.

## Цель

Создать **безопасный тестовый** outreach-процесс для лидов Stage 3:

1. Шаблоны писем (plain text).
2. Последовательности максимум из **3** шагов.
3. Детерминированные черновики для вручную `APPROVED` лидов.
4. Ручное подтверждение каждого черновика.
5. Отправка **только** через существующий `TestEmailProvider`.
6. Тестовый outbox / история попыток (`SendAttempt`).
7. Без реальной внешней отправки.
8. Без scheduler auto-send.

## Аудит (кратко)

| Сущность | Статус |
|---|---|
| Campaign / CampaignLead / QualificationRun / LeadScoreSnapshot | Есть (Stage 1–3) |
| `review_decision` Stage 3 | Есть: PENDING / APPROVED / REJECTED |
| `EmailProvider` interface | Есть (`app/providers/base.py`) |
| `TestEmailProvider` | Есть; **нет** persistent outbox — только in-memory result |
| Template / Sequence / Message | **Нет** → нужны новые модели |
| Celery `beat_schedule` | Пуст |
| `SYSTEM_STOP_ALL` | Есть (`assert_outbound_allowed` / `is_system_stopped`) |
| SendingMode на Campaign | TEST / MANUAL_APPROVAL (контекст, не provider) |

**Вывод:** миграция `0005_safe_outreach` нужна. Outbox-модель отсутствует → добавляем `SendAttempt`. Не дублируем Contact / реальные email.

## Workflow

```
Stage 3 lead (review_decision=APPROVED, is_test_data=true)
        │
        ▼
OutreachTemplate + OutreachSequence (1–3 steps)
        │
        ▼
POST drafts → OutreachMessage (DRAFT, rendered subject/body, recipient @example.test)
        │
        ▼
manual APPROVE / REJECT  (не вызывает provider)
        │
        ▼
explicit SEND → atomic APPROVED→SENDING → TestEmailProvider → SENT + SendAttempt
        │
SYSTEM_STOP_ALL → BLOCKED (provider не вызывается)
```

## Модели

### OutreachTemplate

`id`, `campaign_id` (nullable для reusable), `name`, `subject_template`, `body_template`, `is_active`, `is_test_data`, timestamps.

Ограничения длины: name ≤ 200, subject ≤ 200, body ≤ 5000. Только plain text. Без Jinja/eval.

### OutreachSequence

`id`, `campaign_id`, `name`, `is_active`, `is_test_data`, timestamps.

### OutreachSequenceStep

`id`, `sequence_id`, `template_id`, `step_number` (1–3), `created_at`.

Unique `(sequence_id, step_number)`. Максимум 3 шага. Без delay/scheduler.

### OutreachMessage

Черновик/сообщение: связи на campaign, lead, sequence, step, template; `recipient_email`; rendered subject/body; `status`; `approval_decision`; timestamps approve/reject/send/fail/block; `error_message`; `idempotency_key`; `is_test_data`.

Статусы: `DRAFT` | `APPROVED` | `REJECTED` | `SENDING` | `SENT` | `FAILED` | `BLOCKED`.

Unique `(campaign_lead_id, sequence_step_id)` и unique `idempotency_key`.

### SendAttempt

История тестовой отправки: `message_id`, `provider_name`, `provider_message_id`, `status`, timestamps, `safe_error_message`, `idempotency_key`, `is_test_data`.

Unique `idempotency_key`. Для одного ключа не может быть двух успешных отправок (unique success + claim).

## Тестовый получатель

Только синтетика: `lead-<lead_uuid>@example.test`.

- Любой другой домен → 422.
- Не из Contact, не из внешних источников.
- Пользователь не передаёт произвольный email при draft/send.

## Safe renderer

Модуль `app/services/template_renderer.py`. Allowlist:

| Variable | Источник |
|---|---|
| `{{company_name}}` | Company.name |
| `{{company_domain}}` | Company.domain (или `""`) |
| `{{company_location}}` | primary location city/region/country |
| `{{company_industry}}` | нет колонки → всегда `""` |
| `{{campaign_name}}` | Campaign.name |
| `{{lead_score}}` | CampaignLead.qualification_score |
| `{{qualification_status}}` | CampaignLead.qualification_status |

Правила: неизвестная переменная → ошибка; нет eval/атрибутов/функций; детерминизм; лимиты после рендера.

## API

| Method | Path |
|---|---|
| POST/GET | `/api/campaigns/{id}/outreach/templates` |
| PATCH | `/api/campaigns/{id}/outreach/templates/{template_id}` |
| POST/GET | `/api/campaigns/{id}/outreach/sequences` |
| PATCH | `/api/campaigns/{id}/outreach/sequences/{sequence_id}` |
| POST | `/api/campaigns/{id}/outreach/drafts` |
| GET | `/api/campaigns/{id}/outreach/messages` |
| GET | `/api/campaigns/{id}/outreach/messages/{message_id}` |
| POST | `.../messages/{message_id}/approve` |
| POST | `.../messages/{message_id}/reject` |
| POST | `.../messages/{message_id}/send` |

Фильтры messages: status, approval_decision, sequence_id, lead_id, limit, offset.

## Manual approval

- Approve / Reject меняют только approval/status + timestamps.
- **Не** вызывают `TestEmailProvider` и Celery.
- Идемпотентны.
- Разрешены при `SYSTEM_STOP_ALL` (локальные операции).
- Reset to draft — только из `REJECTED` / `APPROVED` (не из SENT/SENDING/FAILED/BLOCKED).

## State machine (OutreachMessage)

```
DRAFT ──approve──► APPROVED ──send claim──► SENDING ──provider ok + DB──► SENT
  │                  │                         │
  │                  │ reject                  ├─provider error──► FAILED
  │                  ▼                         ├─stale PENDING──► FAILED (DELIVERY_OUTCOME_UNKNOWN)
  └────reject──► REJECTED                      └─STOP (pre-claim)──► BLOCKED
```

- Approve: только `DRAFT → APPROVED` (идемпотентно на уже APPROVED).
- Reject: `DRAFT|APPROVED → REJECTED`.
- Reset to draft: только `APPROVED|REJECTED → DRAFT` (не SENT/SENDING/FAILED/BLOCKED).
- `FAILED` / `BLOCKED` не approve/reject/send без отдельного recovery (Stage 4: нет auto-retry).
- После снятия STOP `BLOCKED` сам не отправляется.
- **SENT** означает только подтверждённый provider success **и** успешную фиксацию в БД.

## Explicit send / delivery guarantee

`APPROVED → SENDING → SENT` (или `FAILED` / pre-claim `BLOCKED`).

**Гарантия Stage 4: at-most-once** для `TestEmailProvider` на стабильном `idempotency_key = outreach:send:{message_id}`:

1. STOP check → atomic claim `APPROVED→SENDING` (rowcount).
2. Reserve `SendAttempt` `PENDING` с unique key (savepoint + IntegrityError).
3. `provider.send(metadata.idempotency_key=…)`.
4. Update attempt → `SUCCESS`, message → `SENT`.

**Exactly-once не обещается.**

Crash / redelivery:

- `SENT` / SUCCESS attempt → no-op, provider не вызывается.
- `SENDING` + fresh `PENDING` (<30s) → `409 sending` (другой worker ещё в provider).
- `SENDING` + **stale PENDING** → message/`SendAttempt` → **FAILED** с кодом `DELIVERY_OUTCOME_UNKNOWN` (не SENT); provider **не** вызывается повторно; обычный send остаётся заблокирован.
- Возможна потеря тестовой отправки при неопределённом исходе; **ложный SENT недопустим**; **автоматический resend недопустим**.

UI: при `DELIVERY_OUTCOME_UNKNOWN` — «Результат тестовой отправки не подтверждён. Автоматический повтор заблокирован.»

- Provider выбирает сервер (`test_email` only); пользователь не передаёт key/provider.
- Message `idempotency_key` = `outreach:lead:{lead}:step:{step}` (draft); send key отдельно.

## Celery

`send_test_outreach_message_task(message_id)` — `max_retries=0`, идемпотентна.

`beat_schedule` остаётся пустым. Нет batch auto-send.

Draft generation — синхронно.

## SYSTEM_STOP_ALL

Проверка **непосредственно перед** atomic claim отправки.

При stop: provider не вызывается; status=`BLOCKED`; `blocked_at` заполнен; success outbox не создаётся.

Шаблоны / sequences / drafts / approve / reject при STOP **разрешены**.

## Safety

- Только `@example.test`
- Только `TestEmailProvider`
- Нет Contact / SMTP / HTTP / LLM / scheduler send
- Все сущности `is_test_data=true`
- Логи без полного subject/body, email, секретов
- API без traceback / raw provider payload

## Критерии готовности

- Миграция 0005 + unique/indexes
- Draft только для Stage 3 APPROVED test leads
- Approve ≠ send; explicit send один раз
- Тесты (в т.ч. mock provider) + Docker smoke + docs

## Не входит в Stage 4

SMTP, Gmail API, SendGrid/Mailgun/Resend, реальные email, массовая авторассылка, поиск email, enrichment контактов, LLM-генерация, auto follow-up, production credentials, scheduler отправки, обход `SYSTEM_STOP_ALL`.
