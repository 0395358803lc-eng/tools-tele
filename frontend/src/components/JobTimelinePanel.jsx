import { useEffect, useMemo, useState } from 'react'
import { fmtTime } from '../lib/util'
import { jobStatusVi } from '../lib/vi'

const STAGES = [
  ['created', 'Created'], ['queued', 'Queued'], ['running', 'Running'],
  ['flood_wait', 'FloodWait'], ['retry', 'Retry'], ['paused', 'Pause'],
  ['resume', 'Resume'], ['recovery', 'Recovery'], ['completed', 'Completed'],
]

function secondsUntil(value) {
  if (!value) return null
  return Math.max(0, Math.ceil((new Date(value).getTime() - Date.now()) / 1000))
}

function ageSeconds(value, fallback) {
  if (!value) return fallback ?? null
  return Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000))
}

function duration(value) {
  if (value == null) return '—'
  const s = Math.max(0, Number(value) || 0)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}m ${r}s`
}

function statusTone(status) {
  if (['completed', 'ok', 'found'].includes(status)) return 'bg-brand-ok'
  if (['failed', 'permanent_error', 'in_flight_unknown'].includes(status)) return 'bg-brand-err'
  if (['flood_wait', 'rate_limited', 'retry', 'waiting_retry', 'paused'].includes(status)) return 'bg-brand-warn'
  return 'bg-brand-violet'
}

function Stat({ label, value, hint }) {
  return <div className="nb-card-sm p-3 min-w-0">
    <div className="text-[10px] font-extrabold uppercase opacity-60">{label}</div>
    <div className="text-lg font-extrabold truncate">{value ?? '—'}</div>
    {hint && <div className="text-[10px] opacity-50 truncate">{hint}</div>}
  </div>
}

export default function JobTimelinePanel({ job }) {
  const [, setTick] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setTick((x) => x + 1), 1000)
    return () => clearInterval(timer)
  }, [])

  const timeline = job?.timeline || []
  const lanes = job?.account_lanes || []
  const stats = job?.item_statistics || {}
  const worker = job?.worker || {}
  const retry = job?.retry || {}
  const seen = useMemo(() => new Set(timeline.map((e) => e.kind)), [timeline])
  const terminalFailed = ['failed', 'interrupted', 'completed_with_errors', 'cancelled'].includes(job?.status)
  const terminalSeen = seen.has('completed') || seen.has('failed') || Boolean(job?.finished_at)
  const heartbeatAge = ageSeconds(worker.heartbeat_at, worker.heartbeat_age_seconds)
  const retryCountdown = secondsUntil(retry.next_retry_at)

  return <div className="space-y-4">
    <div className="nb-card p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div><div className="font-extrabold uppercase">Job Timeline</div>
          <div className="text-[10px] opacity-60">Lifecycle trực quan thay cho việc đọc raw log</div></div>
        <div className="flex-1" />
        <span className={'nb-badge text-black ' + statusTone(job?.status)}>{jobStatusVi(job?.status)}</span>
      </div>
      <div className="grid grid-cols-3 md:grid-cols-5 xl:grid-cols-9 gap-2">
        {STAGES.map(([key, label]) => {
          const active = key === 'completed' ? terminalSeen : seen.has(key)
          const failed = key === 'completed' && terminalSeen && terminalFailed
          return <div key={key} className={`border-2 border-current p-2 text-center min-h-16 flex flex-col justify-center ${active ? (failed ? 'bg-brand-err text-black' : 'bg-brand-ok text-black') : 'opacity-35'}`}>
            <div className="text-[9px] font-extrabold uppercase">{label}</div>
            <div className="text-lg font-black">{active ? '✓' : '·'}</div>
          </div>
        })}
      </div>
    </div>

    <div className="grid md:grid-cols-2 xl:grid-cols-5 gap-3">
      <Stat label="Current worker" value={worker.runner_id ? `${String(worker.runner_id).slice(0, 10)}…` : 'Không có'} hint={worker.active ? 'Đang sở hữu job' : 'Không active'} />
      <Stat label="Heartbeat age" value={duration(heartbeatAge)} hint={worker.stale ? 'Heartbeat stale' : worker.heartbeat_at ? fmtTime(worker.heartbeat_at) : 'Chưa có heartbeat'} />
      <Stat label="Items" value={stats.total ?? 0} hint={`Tổng lần thử: ${stats.attempts ?? 0}`} />
      <Stat label="Retry waiting" value={retry.waiting_items ?? 0} hint={retry.next_retry_at ? `Mốc kế: ${fmtTime(retry.next_retry_at)}` : 'Không có retry đang chờ'} />
      <Stat label="Retry countdown" value={retryCountdown == null ? '—' : duration(retryCountdown)} hint={retryCountdown === 0 && retry.next_retry_at ? 'Đã tới thời điểm retry' : ''} />
    </div>

    <div className="nb-card p-4 space-y-3">
      <div className="font-extrabold uppercase text-sm">Item statistics</div>
      <div className="flex flex-wrap gap-2">
        {Object.entries(stats.status_counts || {}).sort((a, b) => b[1] - a[1]).map(([status, count]) =>
          <span key={status} className={'nb-badge text-black ' + statusTone(status)}>{status}: {count}</span>
        )}
        {Object.keys(stats.status_counts || {}).length === 0 && <span className="text-xs opacity-60">Chưa có item.</span>}
      </div>
    </div>

    <div className="nb-card p-4 space-y-3">
      <div className="flex items-center gap-2"><div className="font-extrabold uppercase text-sm">Account lanes</div>
        <span className="text-xs opacity-60">{lanes.length} lane</span></div>
      <div className="space-y-2 max-h-[520px] overflow-auto">
        {lanes.map((lane) => {
          const laneRetry = secondsUntil(lane.next_retry_at)
          const pct = lane.total > 0 ? Math.min(100, Math.round((Number(lane.processed || 0) / lane.total) * 100)) : 0
          return <div key={lane.account_id ?? 'none'} className="nb-card-sm p-3 space-y-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <b className="font-mono">Account #{lane.account_id ?? 'đã xóa'}</b>
              <span className={'nb-badge text-black ' + statusTone(lane.status)}>{lane.status}</span>
              <span>{lane.processed}/{lane.total} item · {lane.attempts} lần thử</span>
              {laneRetry != null && <span className="nb-badge bg-brand-warn text-black">Retry {duration(laneRetry)}</span>}
              {lane.heartbeat_at && <span className="ml-auto opacity-60">HB {duration(ageSeconds(lane.heartbeat_at, lane.heartbeat_age_seconds))}</span>}
            </div>
            <div className="h-2 border border-current"><div className="h-full bg-brand-ok" style={{ width: `${pct}%` }} /></div>
            {lane.current_item && <div className="text-[11px] font-mono opacity-70 truncate">
              Đang xử lý #{lane.current_item.id} · {lane.current_item.target || '—'} · attempt {lane.current_item.attempts || 0}
            </div>}
            <div className="flex flex-wrap gap-1">
              {Object.entries(lane.status_counts || {}).map(([status, count]) =>
                <span key={status} className="border border-current px-1.5 py-0.5 text-[10px]">{status}:{count}</span>
              )}
            </div>
            {(lane.events || []).length > 0 && <div className="flex gap-1 overflow-x-auto pb-1">
              {(lane.events || []).map((event) => <div key={event.id || `${event.kind}-${event.created_at}`}
                className={`shrink-0 border border-current px-2 py-1 text-[10px] ${event.kind === 'flood_wait' || event.kind === 'retry' ? 'bg-brand-warn text-black' : ''}`}>
                <b>{event.kind}</b><div className="opacity-60">{fmtTime(event.created_at)}</div>
              </div>)}
            </div>}
          </div>
        })}
        {lanes.length === 0 && <div className="text-xs opacity-60">Tác vụ này chưa có account lane.</div>}
      </div>
    </div>

    <div className="nb-card p-4 space-y-3">
      <div className="font-extrabold uppercase text-sm">Lifecycle events</div>
      <div className="space-y-2 max-h-[520px] overflow-auto">
        {timeline.slice(-120).map((event, index) => <div key={event.id || `${event.kind}-${event.created_at}-${index}`}
          className="grid grid-cols-[110px_95px_1fr] gap-2 items-start border-b border-current/20 pb-2 text-xs">
          <div className="opacity-60 whitespace-nowrap">{fmtTime(event.created_at)}</div>
          <span className={'nb-badge text-black text-center ' + statusTone(event.kind)}>{event.kind}</span>
          <div><b>{event.feature}:{event.phase}</b>
            {event.account_id != null && <span className="ml-2 opacity-60">Account #{event.account_id}</span>}
            <div className="mt-0.5 break-words">{event.message}</div>
          </div>
        </div>)}
        {timeline.length === 0 && <div className="text-xs opacity-60">Chưa có lifecycle event.</div>}
      </div>
    </div>
  </div>
}
