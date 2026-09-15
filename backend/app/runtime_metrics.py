from __future__ import annotations

from collections import deque
from threading import Lock

_LOCK = Lock()
_DURATIONS = deque(maxlen=2000)
_TOTAL = 0
_CLIENT_ERRORS = 0
_SERVER_ERRORS = 0


def observe_request(status_code: int, duration_ms: float) -> None:
    global _TOTAL, _CLIENT_ERRORS, _SERVER_ERRORS
    with _LOCK:
        _TOTAL += 1
        _DURATIONS.append(max(0.0, float(duration_ms)))
        if 400 <= int(status_code) < 500:
            _CLIENT_ERRORS += 1
        elif int(status_code) >= 500:
            _SERVER_ERRORS += 1


def snapshot() -> dict:
    with _LOCK:
        vals = sorted(_DURATIONS)
        total = _TOTAL
        client = _CLIENT_ERRORS
        server = _SERVER_ERRORS
    if vals:
        avg = sum(vals) / len(vals)
        p95 = vals[min(len(vals) - 1, max(0, int(len(vals) * 0.95) - 1))]
    else:
        avg = p95 = 0.0
    return {
        'requests_total': int(total),
        'requests_4xx': int(client),
        'requests_5xx': int(server),
        'request_duration_avg_ms': round(avg, 2),
        'request_duration_p95_ms': round(p95, 2),
        'request_duration_samples': len(vals),
    }
