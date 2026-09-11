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
    ]
    for account_status, count in sorted((status.get('accounts') or {}).items()):
        safe = str(account_status).replace('\\', '_').replace('"', '_').replace('\n', '_')
        lines.append(f'mtm_accounts_by_status{{status="{safe}"}} {int(count)}')
    return '\n'.join(lines) + '\n'
