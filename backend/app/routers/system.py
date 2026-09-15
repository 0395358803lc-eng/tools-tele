from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from ..system_status import operational_status

router = APIRouter(prefix='/api/system', tags=['system'])


@router.get('/status')
async def system_status():
    return await operational_status()


@router.get('/metrics', response_class=PlainTextResponse)
async def system_metrics():
    status = await operational_status()
    lines = [
        '# TYPE mtm_uptime_seconds gauge',
        f"mtm_uptime_seconds {status['uptime_seconds']}",
        '# TYPE mtm_accounts_total gauge',
        f"mtm_accounts_total {status['account_total']}",
        '# TYPE mtm_jobs_active gauge',
        f"mtm_jobs_active {status['active_jobs']}",
        '# TYPE mtm_jobs_stale gauge',
        f"mtm_jobs_stale {status['stale_jobs']}",
        '# TYPE mtm_jobs_failed_24h gauge',
        f"mtm_jobs_failed_24h {status['failed_jobs_24h']}",
        '# TYPE mtm_system_cpu_percent gauge',
        f"mtm_system_cpu_percent {status['system_cpu_percent']}",
        '# TYPE mtm_system_memory_percent gauge',
        f"mtm_system_memory_percent {status['system_memory_percent']}",
        '# TYPE mtm_process_memory_bytes gauge',
        f"mtm_process_memory_bytes {status['process_memory_bytes']}",
        '# TYPE mtm_event_loop_lag_ms gauge',
        f"mtm_event_loop_lag_ms {status['event_loop_lag_ms']}",
        '# TYPE mtm_requests_total counter',
        f"mtm_requests_total {status['requests_total']}",
        f"mtm_requests_4xx_total {status['requests_4xx']}",
        f"mtm_requests_5xx_total {status['requests_5xx']}",
        f"mtm_request_duration_avg_ms {status['request_duration_avg_ms']}",
        f"mtm_request_duration_p95_ms {status['request_duration_p95_ms']}",
    ]
    for account_status, count in sorted((status.get('accounts') or {}).items()):
        safe = str(account_status).replace('\\', '_').replace('"', '_').replace('\n', '_')
        lines.append(f'mtm_accounts_by_status{{status="{safe}"}} {int(count)}')
    return '\n'.join(lines) + '\n'
