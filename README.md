# B2B LeadFlow Agent 2026

Проект VCd03 — этапы 0–6. B2B lead generation: Docker, кампании/компании, safe research (Stage 2),
квалификация (Stage 3), TestEmailProvider outreach (Stage 4), тестовый orchestration (Stage 5),
compliance / suppression / provider readiness (Stage 6). Реальная рассылка **не реализована**.

## РЎС‚РµРє

| РЎР»РѕР№ | РўРµС…РЅРѕР»РѕРіРёРё |
|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, Celery |
| Frontend | React 18, Vite 6, TypeScript, Tailwind CSS, TanStack Query, React Hook Form |
| РРЅС„СЂР° | Docker Compose, PostgreSQL 16, Redis 7 |

## Р‘С‹СЃС‚СЂС‹Р№ СЃС‚Р°СЂС‚

```bash
cp .env.example .env
docker compose config
docker compose up --build -d

curl http://localhost:8000/api/health
curl http://localhost:8000/api/readiness
curl http://localhost:8000/api/campaigns
curl http://localhost:8000/api/companies
```

Frontend: http://localhost:8080 В· Swagger: http://localhost:8000/docs

Backend РїСЂРё СЃС‚Р°СЂС‚Рµ РІС‹РїРѕР»РЅСЏРµС‚ `alembic upgrade head` (С‚РѕР»СЊРєРѕ СЃРµСЂРІРёСЃ `backend`, РЅРµ worker/scheduler).

## Alembic

```bash
docker compose exec backend alembic current
docker compose exec backend alembic heads
docker compose exec backend alembic upgrade head
```

Ревизии: `0001` → `0002` → `0003_research_runs` → `0004_qualification` → `0005_safe_outreach` → `0006_test_campaign_execution` → `0007_compliance_ready`.

Документы: [docs/VCd03_SPEC.md](docs/VCd03_SPEC.md), [STAGE2](docs/STAGE2_RESEARCH.md), [STAGE3](docs/STAGE3_QUALIFICATION.md), [STAGE4](docs/STAGE4_SAFE_OUTREACH.md), [STAGE5](docs/STAGE5_TEST_ORCHESTRATION.md), [STAGE6](docs/STAGE6_COMPLIANCE_READINESS.md).

## РџСЂР°РІРёР»Р° РєР°РјРїР°РЅРёР№ (СЌС‚Р°Рї 1)

- `max_companies`: 1вЂ“30
- `max_emails_per_lead`: 1вЂ“3
- `sending_mode`: С‚РѕР»СЊРєРѕ `TEST` РёР»Рё `MANUAL_APPROVAL` (РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ `MANUAL_APPROVAL`)
- РЎРѕР·РґР°РЅРёРµ РІСЃРµРіРґР° РІ СЃС‚Р°С‚СѓСЃРµ `DRAFT`
- РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ С‡РµСЂРµР· PATCH РјРѕР¶РµС‚ РІС‹СЃС‚Р°РІР»СЏС‚СЊ С‚РѕР»СЊРєРѕ `DRAFT` / `PAUSED` / `CANCELLED`
- РџСЂРёРІСЏР·РєР° РєРѕРјРїР°РЅРёРё: `approved_for_email=false`; РґСѓР±Р»РёРєР°С‚ в†’ 409; Р»РёРјРёС‚ в†’ 400
- РЈРґР°Р»РµРЅРёРµ СЃРІСЏР·Рё РЅРµ СѓРґР°Р»СЏРµС‚ РєРѕРјРїР°РЅРёСЋ

## РЎРѕРіР»Р°СЃРёРµ РЅР° РєРѕРЅС‚Р°РєС‚

- `consent_status` РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ `UNKNOWN`
- РџСѓР±Р»РёС‡РЅРѕ РЅР°Р№РґРµРЅРЅС‹Р№ email **РЅРµ** СЃС‡РёС‚Р°РµС‚СЃСЏ СЃРѕРіР»Р°СЃРёРµРј
- UI РїРѕРєР°Р·С‹РІР°РµС‚: В«РЎРѕРіР»Р°СЃРёРµ РЅР° СЂР°СЃСЃС‹Р»РєСѓ РЅРµ РїРѕРґС‚РІРµСЂР¶РґРµРЅРѕВ»
- `do_not_contact` РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ `false`, РѕС‚РѕР±СЂР°Р¶Р°РµС‚СЃСЏ Р·Р°РјРµС‚РЅРѕ
- РћС‚РїСЂР°РІРєР° РїРёСЃРµРј РЅР° СЌС‚Р°РїРµ 1 РЅРµРІРѕР·РјРѕР¶РЅР°

## Demo seed (РІСЂСѓС‡РЅСѓСЋ)

```bash
docker compose exec backend python -m app.scripts.seed_demo_data
```

РРґРµРјРїРѕС‚РµРЅС‚РЅРѕ; Р°РґСЂРµСЃР° С‚РѕР»СЊРєРѕ `@*.example.com`. РќРµ Р·Р°РїСѓСЃРєР°РµС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё.

## РўРµСЃС‚С‹

```bash
# Р’ РєРѕРЅС‚РµР№РЅРµСЂРµ (СЂРµРєРѕРјРµРЅРґСѓРµС‚СЃСЏ РЅР° Windows)
docker compose exec backend sh -c 'export TEST_DATABASE_URL="${DATABASE_URL%/leadflow}/leadflow_test"; pytest -v'

# Frontend
cd frontend && npm run build
```

## Smoke

```bash
python backend/scripts/smoke_stage1.py
```

## Р”РѕРєСѓРјРµРЅС‚Р°С†РёСЏ

- [docs/VCd03_SPEC.md](docs/VCd03_SPEC.md)
- [SECURITY.md](SECURITY.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [HOMEWORK_REPORT.md](HOMEWORK_REPORT.md)
