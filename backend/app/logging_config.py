from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

_URL_SECRET = re.compile(r'((?:postgres(?:ql)?(?:\+\w+)?):\/\/[^:\s]+:)([^@\s]+)(@)', re.I)
_BEARER = re.compile(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+')
_KEY_VALUE = re.compile(r'(?i)\b(password|secret|token|api[_-]?key|authorization)\b(\s*[=:]\s*)([^\s,;]+)')


def redact_text(value: str) -> str:
    text = str(value or '')
    text = _URL_SECRET.sub(r'\1[redacted]\3', text)
    text = _BEARER.sub(r'\1[redacted]', text)
    text = _KEY_VALUE.sub(r'\1\2[redacted]', text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            'ts': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': redact_text(record.getMessage())[:10000],
        }
        try:
            from .audit import current_audit_context
            ctx = current_audit_context()
            if ctx.get('request_id'):
                payload['request_id'] = ctx['request_id']
        except Exception:
            pass
        try:
            from .tenant import current_tenant_id
            tenant_id = current_tenant_id()
            if tenant_id:
                payload['user_id'] = str(tenant_id)
        except Exception:
            pass
        if record.exc_info:
            payload['exception'] = redact_text(self.formatException(record.exc_info))[:20000]
        return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))


def configure_logging() -> None:
    level_name = settings.LOG_LEVEL.upper().strip()
    level = getattr(logging, level_name, logging.INFO)
    production = settings.NODE_ENV.strip().lower() == 'production'
    use_json = settings.LOG_FORMAT.strip().lower() == 'json' or production
    formatter = JsonFormatter() if use_json else logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')

    handlers: list[logging.Handler] = []
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    handlers.append(stream)
    if production or bool(settings.LOG_FILE_ENABLED):
        log_dir = Path(__file__).resolve().parents[2] / 'logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / 'backend.jsonl',
            maxBytes=max(1_000_000, int(settings.LOG_FILE_MAX_BYTES)),
            backupCount=max(1, min(20, int(settings.LOG_FILE_BACKUP_COUNT))),
            encoding='utf-8',
        )
        file_handler.setFormatter(JsonFormatter())
        handlers.append(file_handler)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    for handler in handlers:
        root.addHandler(handler)
