import logging
import re
from typing import Any

SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(postgresql(?:\+[\w]+)?://)[^\s\"']+", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(redis://)[^\s\"']+", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(password\s*[=:]\s*)[^\s,\"']+", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(secret[_-]?key\s*[=:]\s*)[^\s,\"']+", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(api[_-]?key\s*[=:]\s*)[^\s,\"']+", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(token\s*[=:]\s*)[^\s,\"']+", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(DATABASE_URL\s*[=:]\s*)[^\s,\"']+", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(REDIS_URL\s*[=:]\s*)[^\s,\"']+", re.IGNORECASE), r"\1***REDACTED***"),
    (re.compile(r"(CELERY_BROKER_URL\s*[=:]\s*)[^\s,\"']+", re.IGNORECASE), r"\1***REDACTED***"),
]


def redact_secrets(text: str) -> str:
    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            record.args = tuple(
                redact_secrets(arg) if isinstance(arg, str) else arg for arg in record.args
            )
        for key in ("database_url", "redis_url", "password", "secret", "token", "api_key"):
            if hasattr(record, key):
                setattr(record, key, "***REDACTED***")
        return True


def setup_logging(level: str = "INFO") -> None:
    from pythonjsonlogger import jsonlogger

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
    )
    handler.setFormatter(formatter)
    handler.addFilter(SecretRedactionFilter())
    root.addHandler(handler)


class RequestIdLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True
