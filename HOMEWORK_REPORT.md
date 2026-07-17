# HOMEWORK REPORT вЂ” VCd03 Stage 1

**РџСЂРѕРµРєС‚:** B2B LeadFlow Agent 2026
**Р­С‚Р°Рї:** 1 вЂ” Р±Р°Р·Р° РґР°РЅРЅС‹С…, РєР°РјРїР°РЅРёРё Рё РєРѕРјРїР°РЅРёРё
**Р’РµС‚РєР°:** `feature/stage-1-campaigns-companies`
**Р”Р°С‚Р°:** 2026-07-17
**РЎС‚Р°С‚СѓСЃ:** `READY_FOR_STAGE_1_COMMIT`

---

## 1. РР·РјРµРЅС‘РЅРЅС‹Рµ Рё СЃРѕР·РґР°РЅРЅС‹Рµ С„Р°Р№Р»С‹ (РєР»СЋС‡РµРІС‹Рµ)

**Backend models / migration**

- `backend/app/models/` вЂ” enums, mixins, campaign, company, contact, data_source, campaign_lead
- `backend/alembic/versions/0002_campaigns_companies.py`
- `backend/alembic/env.py` вЂ” import models; URL override only for default placeholder
- `backend/entrypoint.sh` + `backend/Dockerfile` ENTRYPOINT (migrations only on backend)

**Services / API / schemas**

- `backend/app/services/validation.py`, `campaign_service.py`, `company_service.py`
- `backend/app/schemas/campaign.py`, `company.py`
- `backend/app/api/campaigns.py`, `companies.py`
- `backend/app/scripts/seed_demo_data.py`
- `backend/scripts/smoke_stage1.py`

**Tests**

- `tests/test_campaigns.py`, `test_companies.py`, `test_campaign_leads.py`, `test_migrations.py`, `test_seed.py`
- РѕР±РЅРѕРІР»РµРЅС‹ `conftest.py`, `test_health.py`

**Frontend**

- `frontend/src/api/client.ts`
- `frontend/src/pages/CampaignsPage.tsx`, `CompaniesPage.tsx`
- `frontend/src/App.tsx`, `index.css`

**Compose / docs**

- `docker-compose.yml` вЂ” worker/scheduler entrypoint Р±РµР· РјРёРіСЂР°С†РёР№; backend start_period 40s
- `README.md`, `docs/VCd03_SPEC.md`, `HOMEWORK_REPORT.md`

`.env` РЅРµ РёР·РјРµРЅСЏР»СЃСЏ Рё РЅРµ РєРѕРјРјРёС‚РёС‚СЃСЏ.

---

## 2. РўР°Р±Р»РёС†С‹ Рё СЃРІСЏР·Рё

| РўР°Р±Р»РёС†Р° | РЎРІСЏР·Рё |
|---|---|
| `campaigns` | 1в†’N `campaign_leads` (CASCADE) |
| `companies` | 1в†’N locations/contacts/source_records (CASCADE); Nв†ђ`campaign_leads` (RESTRICT delete company) |
| `company_locations` | FK в†’ companies CASCADE |
| `contacts` | FK в†’ companies CASCADE |
| `data_sources` | 1в†’N source_records (RESTRICT) |
| `company_source_records` | FK company CASCADE, data_source RESTRICT; `raw_payload` JSONB |
| `campaign_leads` | UNIQUE(campaign_id, company_id); defaults NEW / approved_for_email=false |

РџСѓР±Р»РёС‡РЅС‹Рµ id: UUID. Timestamps UTC.

---

## 3. Alembic revision

- **Revision:** `0002_campaigns_companies`
- **Down revision:** `0001_stage0_baseline`
- **Runtime:** `alembic current` в†’ `0002_campaigns_companies (head)`
- **Heads:** `0002_campaigns_companies (head)`

---

## 4. API

**Campaigns:** POST/GET/GET{id}/PATCH `/api/campaigns`; GET/POST/DELETE `/api/campaigns/{id}/companies[/{company_id}]`

**Companies:** POST/GET/GET{id}/PATCH `/api/companies`

**Locations:** POST `/api/companies/{id}/locations`; PATCH/DELETE `/api/locations/{id}`

**Contacts:** POST `/api/companies/{id}/contacts`; PATCH/DELETE `/api/contacts/{id}`

DELETE РєРѕРјРїР°РЅРёРё РЅР° СЌС‚Р°РїРµ 1 РЅРµС‚.

---

## 5. Р‘РµР·РѕРїР°СЃРЅРѕСЃС‚СЊ Рё РІР°Р»РёРґР°С†РёСЏ

- SYSTEM_STOP_ALL / TestEmailProvider СЃРѕС…СЂР°РЅРµРЅС‹
- CORS, request ID, secret filter
- Mass assignment: `extra=forbid` РЅР° update-СЃС…РµРјР°С…; РєР»РёРµРЅС‚ РЅРµ Р·Р°РґР°С‘С‚ id/timestamps/approved_for_email
- Email validation; URL С‚РѕР»СЊРєРѕ http/https
- РћРїР°СЃРЅС‹Рµ СЃС‚Р°С‚СѓСЃС‹ РєР°РјРїР°РЅРёРё С‡РµСЂРµР· PATCH Р·Р°РїСЂРµС‰РµРЅС‹
- max_companies РЅРµР»СЊР·СЏ СѓРјРµРЅСЊС€РёС‚СЊ РЅРёР¶Рµ lead_count
- Р›РёРјРёС‚ 30 РєРѕРјРїР°РЅРёР№ РЅР° РєР°РјРїР°РЅРёСЋ
- consent UNKNOWN РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ; РЅРµС‚ Р°РІС‚Рѕ-РѕС‚РїСЂР°РІРєРё
- РћС€РёР±РєРё Р±РµР· traceback РїРѕР»СЊР·РѕРІР°С‚РµР»СЋ

---

## 6. Frontend

- Р Р°Р±РѕС‡РёРµ СЃС‚СЂР°РЅРёС†С‹ В«РљР°РјРїР°РЅРёРёВ» Рё В«РљРѕРјРїР°РЅРёРёВ»
- Р¤РѕСЂРјС‹ СЃРѕР·РґР°РЅРёСЏ/СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёСЏ, РІР°Р»РёРґР°С†РёСЏ Р»РёРјРёС‚РѕРІ
- Р”РµС‚Р°Р»Рё РєР°РјРїР°РЅРёРё: lead_count, free_slots, attach/detach СЃ confirm
- РљР°СЂС‚РѕС‡РєР° РєРѕРјРїР°РЅРёРё: Р°РґСЂРµСЃР°, РєРѕРЅС‚Р°РєС‚С‹, Р±Р°РЅРЅРµСЂ СЃРѕРіР»Р°СЃРёСЏ, do_not_contact
- РќРµС‚ РєРЅРѕРїРєРё СЂРµР°Р»СЊРЅРѕР№ РѕС‚РїСЂР°РІРєРё; СЂСѓСЃСЃРєРёРµ РїРѕРґРїРёСЃРё enum

---

## 7. РўРµСЃС‚С‹

```
36 passed in ~3.8s
```

(РІ Docker backend СЃ `TEST_DATABASE_URL=вЂ¦/leadflow_test`)

Р’РєР»СЋС‡Р°СЏ stage 0: health, providers, secret filter, stop_all, readiness.

---

## 8. Frontend build

```
tsc --noEmit && vite build вЂ” OK (84 modules)
```

---

## 9вЂ“11. Docker / health

- `docker compose config` вЂ” OK
- `docker compose ps`: backend/frontend/postgres/redis **healthy**; worker/scheduler **Up** (healthcheck disabled)
- `/api/health` в†’ ok
- `/api/readiness` в†’ ready (postgres/redis ok)
- Frontend `localhost:8080` в†’ HTTP 200

---

## 12. Runtime smoke

`python backend/scripts/smoke_stage1.py` в†’ **SMOKE_OK**

1. РЎРѕР·РґР°РЅР° РєР°РјРїР°РЅРёСЏ
2. РЎРѕР·РґР°РЅР° РєРѕРјРїР°РЅРёСЏ
3. Email СЃ consent=UNKNOWN
4. РџСЂРёРІСЏР·РєР°, `approved_for_email=false`
5. Р”Р°РЅРЅС‹Рµ С‡РёС‚Р°СЋС‚СЃСЏ РїРѕСЃР»Рµ РѕР¶РёРґР°РЅРёСЏ
6. Detach СЃРІСЏР·Рё; РєРѕРјРїР°РЅРёСЏ РѕСЃС‚Р°С‘С‚СЃСЏ
7. РљРѕРЅС‚Р°РєС‚ СѓРґР°Р»С‘РЅ

РњР°СЂРєРµСЂРЅС‹Рµ Р·Р°РїРёСЃРё `ZZ-SMOKE*` РјРѕРіСѓС‚ РѕСЃС‚Р°С‚СЊСЃСЏ РІ Р‘Р” (СѓРґР°Р»РµРЅРёРµ РєРѕРјРїР°РЅРёРё РЅРµ СЂРµР°Р»РёР·РѕРІР°РЅРѕ).

---

## 13. alembic current / heads

РћР±Р°: `0002_campaigns_companies (head)`.

---

## 14. Git status

Р’РµС‚РєР° `feature/stage-1-campaigns-companies`. РњРЅРѕРіРѕ modified/untracked С„Р°Р№Р»РѕРІ СЌС‚Р°РїР° 1.
**Commit / push / merge РЅРµ РІС‹РїРѕР»РЅСЏР»РёСЃСЊ.**

---

## 15. РР·РІРµСЃС‚РЅС‹Рµ РѕРіСЂР°РЅРёС‡РµРЅРёСЏ

- Р РµР°Р»СЊРЅС‹Р№ РїРѕРёСЃРє/email/LLM/SMTP вЂ” РЅРµС‚
- DELETE РєРѕРјРїР°РЅРёРё вЂ” РЅРµС‚
- РђРІС‚РѕСЂРёР·Р°С†РёСЏ вЂ” РЅРµС‚
- Host Windows pytest Рє Postgres РјРѕР¶РµС‚ РїР°РґР°С‚СЊ РЅР° Р»РѕРєР°Р»Рё/РїР°СЂРѕР»Рµ; С‚РµСЃС‚С‹ РіРѕРЅСЏСЋС‚СЃСЏ РІ РєРѕРЅС‚РµР№РЅРµСЂРµ
- Worker/scheduler Р±РµР· Docker healthcheck (РЅР°РјРµСЂРµРЅРЅРѕ)
- Demo seed С‚РѕР»СЊРєРѕ РІСЂСѓС‡РЅСѓСЋ

---

## 16. Р’РµСЂРґРёРєС‚

**`READY_FOR_STAGE_1_COMMIT`**
