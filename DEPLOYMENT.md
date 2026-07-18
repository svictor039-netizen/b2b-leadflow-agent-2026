# Deployment Guide — Stage 8

Production hardening runbooks for Linux VPS + Docker Compose. **Stage 8 does not perform real deploy or real email sends.**

---

## Architecture (production)

```
Internet → nginx proxy (:443/:80) → frontend / backend (internal)
                                      ↓
                              postgres, redis (internal only)
                              worker, scheduler (internal)
```

Compose invocation:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production up -d
```

Set `PRODUCTION_ENV_FILE=.env.production` so backend/worker/scheduler load the same secrets file inside containers.

Local production-like smoke (no TLS):

```bash
PRODUCTION_ENV_FILE=.env.production.smoke docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production.smoke up -d --build
```

---

## Pre-deploy checklist

- [ ] `main` tested; release tag chosen
- [ ] `.env.production` created from `.env.production.example` with strong secrets
- [ ] `SYSTEM_STOP_ALL=true` confirmed for initial deploy
- [ ] `REAL_EMAIL_PROVIDER_ENABLED=false`, `LIVE_OUTREACH_ENABLED=false`
- [ ] `LIVE_PROVIDER_API_KEY` empty; live provider not configured (Stage 7B pending)
- [ ] `FRONTEND_ORIGIN` set to production HTTPS domain
- [ ] TLS certificates mounted (see `deploy/tls.conf.template`)
- [ ] Backup directory configured on VPS
- [ ] Monitoring scrape target configured (internal `/api/metrics`)

---

## Backup before deploy

```bash
export COMPOSE_FILES="-f docker-compose.yml -f docker-compose.prod.yml"
./scripts/backup_postgres.sh
./scripts/verify_backup.sh backups/leadflow_leadflow_<timestamp>.dump
```

**Retention policy (operator cron):**

| Tier | Retention |
|------|-----------|
| Daily | 7 days |
| Weekly | 4 weeks |
| Monthly | 12 months |

---

## Deploy procedure

```bash
git pull origin main
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production build
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production up -d
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Migrations run automatically via backend `entrypoint.sh` (`alembic upgrade head`).

---

## Readiness verification

```bash
curl -sf http://127.0.0.1:8080/api/readiness | jq .
curl -sf http://127.0.0.1:8080/api/liveness | jq .
curl -sf http://127.0.0.1:8080/api/metrics | head
```

Expect readiness HTTP **200** with:

- `checks.postgres`: `ok`
- `checks.redis`: `ok`
- `checks.migrations`: `ok`
- `runtime.system_stop_all`: `true` (initial deploy)

---

## Post-deploy smoke

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend \
  env SMOKE_BASE_URL=http://proxy:80 python scripts/smoke_stage8.py
```

Confirm output includes `live_sent=0`.

---

## Rollback (application)

1. Set emergency stop: `SYSTEM_STOP_ALL=true` in `.env.production`, recreate backend/worker/scheduler
2. Stop stack: `docker compose ... down`
3. Checkout previous release: `git checkout <previous-tag>`
4. Rebuild and start: `docker compose ... up -d --build`
5. Verify readiness and smoke

**Migration rollback:** only when Alembic downgrade is safe for the target revision. Stage 8 adds no migrations. For future revisions, consult `docs/STAGE8_PRODUCTION_HARDENING_DEPLOYMENT.md` and migration notes before `alembic downgrade -1`.

---

## Database restore (emergency only)

**Never restore over production by default.**

```bash
./scripts/restore_postgres.sh --target-db leadflow_restore_test --i-understand yes backups/<file>.dump
```

Production restore requires explicit operator procedure outside automated rollback:

1. Stop application containers
2. Restore to a **new** database name first; validate
3. Only then plan cutover with downtime window

---

## SYSTEM_STOP_ALL emergency procedure

1. Set `SYSTEM_STOP_ALL=true` in `.env.production`
2. `docker compose ... up -d backend worker scheduler`
3. Verify `/api/readiness` → `runtime.system_stop_all: true`
4. Confirm no outbound send tasks execute (audit logs, `live_sent=0`)

---

## Secret rotation

1. Generate new PostgreSQL password / API placeholders (Stage 7B only after review)
2. Update `.env.production` on VPS (never commit)
3. `docker compose ... up -d --force-recreate backend worker scheduler`
4. Verify readiness; rotate reverse proxy TLS certs independently if needed

---

## Incident response

1. **Stop blast radius:** `SYSTEM_STOP_ALL=true`
2. **Collect correlation IDs** from logs (`request_id` field)
3. **Check readiness/metrics** — component failures, error rate
4. **Backup current state** before remediation
5. **Rollback or restore** per sections above
6. Post-incident: verify smoke, document in audit trail

---

## CI (reference)

GitHub Actions workflow `.github/workflows/ci.yml` validates tests, builds, compose configs, and secret file guards on every push/PR.

---

## Local development (unchanged)

```bash
cp .env.example .env
docker compose up --build -d
```

---

## Ports (production overlay)

| Service | External |
|---------|----------|
| proxy | `${PROXY_HTTP_PORT:-8080}` |
| postgres | internal only |
| redis | internal only |
| backend | internal only |
| frontend | internal only |

---

## Volumes

| Volume | Data |
|--------|------|
| `postgres_data` | PostgreSQL |
| `redis_data` | Redis AOF |
| `backups/` | Operator-managed dump files (gitignored) |
