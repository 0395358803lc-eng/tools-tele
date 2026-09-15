from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / 'logs'
STATE_FILE = LOG_DIR / 'alerts-state.json'
ALERT_FILE = LOG_DIR / 'alerts.jsonl'
_LOCK = Lock()


def _load_state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    tmp.replace(STATE_FILE)


def _append_event(event: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger('ops_alert_events')
    if not log.handlers:
        log.setLevel(logging.INFO)
        h = RotatingFileHandler(ALERT_FILE, maxBytes=2_000_000, backupCount=5, encoding='utf-8')
        h.setFormatter(logging.Formatter('%(message)s'))
        log.addHandler(h)
        log.propagate = False
    log.info(json.dumps(event, ensure_ascii=False, separators=(',', ':')))


def set_alert(code: str, active: bool, *, level: str = 'warning',
              message: str = '', source: str = 'runtime') -> bool:
    key = f'{source}:{code}'
    with _LOCK:
        state = _load_state()
        previous = bool((state.get(key) or {}).get('active'))
        if previous == bool(active):
            return False
        now = datetime.now(timezone.utc).isoformat()
        state[key] = {'active': bool(active), 'level': level, 'message': message[:500],
                      'source': source, 'code': code, 'updated_at': now}
        _save_state(state)
        _append_event({'ts': now, 'source': source, 'code': code, 'level': level,
                       'status': 'opened' if active else 'resolved', 'message': message[:500]})
        return True


def current_alerts() -> list[dict]:
    with _LOCK:
        state = _load_state()
    rows = []
    for item in state.values():
        if isinstance(item, dict) and item.get('active'):
            rows.append(dict(item))
    rows.sort(key=lambda x: str(x.get('updated_at') or ''), reverse=True)
    return rows


def recent_alerts(limit: int = 50) -> list[dict]:
    limit = max(1, min(200, int(limit)))
    if not ALERT_FILE.exists():
        return []
    rows = []
    try:
        lines = ALERT_FILE.read_text(encoding='utf-8', errors='ignore').splitlines()[-limit:]
        for line in reversed(lines):
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
            except Exception:
                continue
    except Exception:
        return []
    return rows


def reconcile(alerts: list[dict], *, source: str = 'health') -> None:
    active_codes = {str(a.get('code')) for a in alerts if a.get('code')}
    with _LOCK:
        state = _load_state()
        old_codes = {str(v.get('code')) for v in state.values()
                     if isinstance(v, dict) and v.get('source') == source and v.get('active')}
    for alert in alerts:
        code = str(alert.get('code') or '')
        if code:
            set_alert(code, True, level=str(alert.get('level') or 'warning'),
                      message=str(alert.get('message') or ''), source=source)
    for code in old_codes - active_codes:
        set_alert(code, False, level='info', message='Condition recovered', source=source)
