# Final Demo Checklist — B2B LeadFlow Agent (VCd03)

Safe demo only. **Do not** enable Stage 7B, real providers, or real sends during the presentation.

---

## 1. Start (dev compose)

```bash
cd "d:\ai agents\b2b leadflow agent 2026"
cp .env.example .env          # if .env missing
docker compose config
docker compose up --build -d
docker compose ps
```

Optional seed:

```bash
docker compose exec backend python -m app.scripts.seed_demo_data
```

---

## 2. Pages to open

| URL | What to show |
|-----|----------------|
| http://localhost:8080 | Frontend shell |
| Campaigns page | Campaign CRUD, leads, outreach, execution, live pilot panel |
| Companies page | Companies / locations / contacts |
| http://localhost:8000/docs | OpenAPI (Swagger) |

Prod-like (optional, single entrypoint):

```bash
PRODUCTION_ENV_FILE=.env.production.smoke docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production.smoke up -d
# UI + API via http://localhost:8080 (proxy)
```

---

## 3. API to demonstrate

```bash
curl -s http://localhost:8000/api/health
curl -s http://localhost:8000/api/liveness
curl -s http://localhost:8000/api/readiness
curl -s http://localhost:8000/api/version
curl -s http://localhost:8000/api/metrics | head
curl -s http://localhost:8000/api/campaigns
curl -s http://localhost:8000/api/compliance/provider-readiness
```

Live pilots (readiness / list — no live-send route):

```bash
# After creating a pilot in UI or via API:
curl -s "http://localhost:8000/api/live-pilots?campaign_id=<uuid>"
```

---

## 4. Safety flags to show

From readiness / env / docs:

| Flag / check | Expected for safe demo |
|--------------|------------------------|
| `SYSTEM_STOP_ALL` | Prefer `true` for production-like smoke; may be `false` in local `.env.example` for test sends via TestEmailProvider only |
| `REAL_EMAIL_PROVIDER_ENABLED` | `false` |
| `LIVE_OUTREACH_ENABLED` | `false` |
| `LIVE_PROVIDER_API_KEY` | empty |
| `readiness.checks` | postgres/redis/migrations `ok` |
| `beat_schedule` | empty `{}` |
| Live-send under `/api/live-pilots` | **absent** |

Production smoke confirmation:

```bash
docker compose exec backend python scripts/smoke_stage8.py
# expect: live_sent=0 system_stop_all=True
```

---

## 5. Screenshots (recommended)

1. `docker compose ps` — healthy services  
2. Frontend Campaigns page  
3. Live Pilot panel (dry-run / blocked live)  
4. Swagger `/docs`  
5. `/api/readiness` JSON (no secrets)  
6. `/api/metrics` snippet  
7. Terminal: Stage 8 smoke `live_sent=0`  
8. GitHub Actions green checks on PR #8 (optional)

---

## 6. Confirm `live_sent=0`

```bash
docker compose exec backend python scripts/smoke_stage8.py
# or Stage 7A:
docker compose exec backend python scripts/smoke_stage7_testdb.py
```

Also check readiness runtime / pilot counters — successful live sends must remain **0**.

---

## 7. Stop Docker

```bash
docker compose down
# or prod-like:
PRODUCTION_ENV_FILE=.env.production.smoke docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production.smoke down
```

Volumes persist by default; do not delete production-like data unless intentional.

---

## 8. Do NOT enable during demo

- Stage 7B / real email provider
- Real SMTP/API credentials in `.env`
- `REAL_EMAIL_PROVIDER_ENABLED=true` or `LIVE_OUTREACH_ENABLED=true`
- Non-empty `LIVE_PROVIDER_API_KEY` / `PROVIDER_API_KEY`
- Real recipient emails outside `@example.test` / `@*.example.com` test data
- Real VPS deploy / public DNS / live TLS issuance as part of the homework demo
- Anything called «Stage 9» (does not exist)
- Mass campaign sends to real people

---

## 9. Links

- Final report: [HOMEWORK_FINAL_REPORT.md](../HOMEWORK_FINAL_REPORT.md)
- Spec: [VCd03_SPEC.md](VCd03_SPEC.md)
- Deployment runbook: [DEPLOYMENT.md](../DEPLOYMENT.md)
