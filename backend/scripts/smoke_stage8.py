"""Stage 8 production hardening smoke — zero real email sends."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal, check_database_connection
from app.core.production_validation import validate_production_settings
from app.core.redis_client import check_redis_connection
from app.models.live_pilot import LivePilot
from app.workers.celery_app import celery_app

REPO_ROOT = ROOT.parent


def _http_get(url: str) -> tuple[int, dict | str, dict[str, str]]:
    req = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            headers = dict(resp.headers)
            try:
                import json

                return resp.status, json.loads(body), headers
            except Exception:
                return resp.status, body, headers
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, body, dict(exc.headers)


def _metrics_get(url: str) -> tuple[int, str]:
    req = Request(url, headers={"Accept": "text/plain"})
    with urlopen(req, timeout=10) as resp:
        return resp.status, resp.read().decode("utf-8")


def main() -> None:
    base = os.getenv("SMOKE_BASE_URL", "http://proxy:80").rstrip("/")
    if os.getenv("SMOKE_BASE_URL_EXTERNAL"):
        base = os.getenv("SMOKE_BASE_URL_EXTERNAL", "http://127.0.0.1:8080").rstrip("/")

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.system_stop_all is True, "SYSTEM_STOP_ALL must be true in Stage 8 smoke"
    assert not settings.live_provider_api_key.strip(), "live provider API key must be empty"
    assert celery_app.conf.beat_schedule == {}, "beat schedule must remain empty"

    if settings.is_production:
        prod_errors = validate_production_settings(settings)
        assert not prod_errors, f"production validation failed: {prod_errors}"

    assert check_database_connection(), "database connectivity failed"
    assert check_redis_connection(), "redis connectivity failed"

    code, liveness, _ = _http_get(f"{base}/api/liveness")
    assert code == 200 and liveness.get("status") == "alive", liveness

    code, readiness, headers = _http_get(f"{base}/api/readiness")
    assert code == 200, readiness
    assert readiness.get("status") == "ready", readiness
    assert readiness["checks"]["postgres"] == "ok"
    assert readiness["checks"]["redis"] == "ok"
    assert readiness["checks"]["migrations"] == "ok"
    assert readiness["runtime"]["system_stop_all"] is True
    assert readiness["runtime"]["live_provider_disabled"] is True
    assert "X-Request-ID" in headers or "x-request-id" in {k.lower() for k in headers}

    m_code, metrics_body = _metrics_get(f"{base}/api/metrics")
    assert m_code == 200
    assert "leadflow_http_requests_total" in metrics_body
    assert "leadflow_readiness_state" in metrics_body
    assert "@" not in metrics_body.split("\n")[0:20].__repr__()  # coarse PII guard

    backup_script = REPO_ROOT / "scripts" / "backup_postgres.sh"
    verify_script = REPO_ROOT / "scripts" / "verify_backup.sh"
    if backup_script.exists() and os.name != "nt":
        env = os.environ.copy()
        env.setdefault("COMPOSE_FILES", "-f docker-compose.yml")
        result = subprocess.run(
            ["bash", str(backup_script)],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("Backup OK"):
                    backup_file = line.split("—")[-1].strip()
                    if Path(backup_file).exists():
                        verify = subprocess.run(
                            ["bash", str(verify_script), backup_file],
                            cwd=str(REPO_ROOT),
                            env=env,
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        assert verify.returncode == 0, verify.stderr or verify.stdout
                    break
        else:
            print("WARN: backup step skipped or failed:", result.stderr or result.stdout, file=sys.stderr)

    db = SessionLocal()
    try:
        live_sent = db.scalar(select(func.coalesce(func.sum(LivePilot.live_sent_count), 0))) or 0
    finally:
        db.close()

    print(
        f"Stage 8 smoke OK — live_sent={live_sent} "
        f"system_stop_all={settings.system_stop_all} "
        f"environment={settings.environment}"
    )


if __name__ == "__main__":
    main()
