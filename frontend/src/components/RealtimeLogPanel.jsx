import { useEffect, useMemo, useRef, useState } from 'react'
import { realtimeConnectionLabels } from '../lib/realtime'
import { useRealtimeEvents } from '../lib/useRealtimeEvents'
import { fmtTime } from '../lib/util'

const FEATURES = [
  ['', 'Tất cả tính năng'],
  ['jobs', 'Tác vụ'],
  ['messaging', 'Gửi tin nhắn'],
  ['phone_check', 'Check số'],
  ['accounts', 'Tài khoản'],
  ['proxy', 'Proxy'],
  ['inbox', 'Tin nhắn đến'],
  ['import', 'Nhập dữ liệu'],
  ['export', 'Xuất dữ liệu'],
  ['system', 'Hệ thống'],
]

const LEVELS = [
  ['', 'Tất cả mức'],
  ['debug', 'DEBUG'],
  ['info', 'INFO'],
  ['success', 'THÀNH CÔNG'],
  ['warning', 'CẢNH BÁO'],
  ['error', 'LỖI'],
]

function levelClass(level) {
  if (level === 'success') return 'bg-brand-ok text-black'
  if (level === 'warning') return 'bg-brand-warn text-black'
  if (level === 'error') return 'bg-brand-err text-black'
  if (level === 'debug') return 'bg-zinc-300 text-black'
  return 'bg-brand-violet text-black'
}

function downloadJson(rows) {
  const blob = new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `realtime-log-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export default function RealtimeLogPanel({
  title = 'Nhật ký realtime',
  initialFilters = {},
  compact = false,
  showFilters = true,
}) {
  const [feature, setFeature] = useState(initialFilters.feature || '')
  const [level, setLevel] = useState(initialFilters.level || '')
  const [accountId, setAccountId] = useState(initialFilters.account_id || '')
  const [jobId, setJobId] = useState(initialFilters.job_id || '')
  const [search, setSearch] = useState('')
  const [autoScroll, setAutoScroll] = useState(true)
  const scrollerRef = useRef(null)

  useEffect(() => {
    setFeature(initialFilters.feature || '')
    setLevel(initialFilters.level || '')
    setAccountId(initialFilters.account_id || '')
    setJobId(initialFilters.job_id || '')
  }, [initialFilters.feature, initialFilters.level, initialFilters.account_id, initialFilters.job_id])

  const filters = useMemo(() => ({
    feature,
    level,
    job_id: jobId,
    account_id: accountId,
  }), [feature, level, jobId, accountId])

  const {
    events,
    connection,
    loading,
    error,
    hasMore,
    lastHeartbeatAt,
    loadOlder,
    reload,
    clearView,
  } = useRealtimeEvents({ filters })

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    if (!needle) return events
    return events.filter((event) => {
      const haystack = [
        event.message, event.phase, event.feature, event.level,
        event.job_id, event.account_id, event.correlation_id,
      ].filter(Boolean).join(' ').toLowerCase()
      return haystack.includes(needle)
    })
  }, [events, search])

  useEffect(() => {
    if (!autoScroll || !scrollerRef.current) return
    scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight
  }, [visible.length, autoScroll])

  async function copyVisible() {
    const text = visible.map((event) => (
      `[${event.created_at || ''}] ${String(event.level || '').toUpperCase()} ${event.feature || '-'}:${event.phase || '-'} ${event.message || ''}`
    )).join('\n')
    try { await navigator.clipboard.writeText(text) } catch {}
  }

  const connectionClass = connection === 'connected'
    ? 'bg-brand-ok text-black'
    : connection === 'offline'
      ? 'bg-brand-err text-black'
      : 'bg-brand-warn text-black'

  return (
    <div className="nb-card p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div>
          <h3 className="font-extrabold uppercase">{title}</h3>
          <div className="text-[10px] opacity-60">
            {visible.length}/{events.length} event đang hiển thị
            {lastHeartbeatAt ? ` · heartbeat ${fmtTime(lastHeartbeatAt)}` : ''}
          </div>
        </div>
        <span className={`nb-badge ml-auto ${connectionClass}`}>
          {realtimeConnectionLabels[connection] || connection}
        </span>
        <button className="nb-btn !py-1 !px-2 text-xs" onClick={() => setAutoScroll((v) => !v)}>
          {autoScroll ? 'Tắt tự cuộn' : 'Bật tự cuộn'}
        </button>
        <button className="nb-btn !py-1 !px-2 text-xs" onClick={reload}>Làm mới</button>
      </div>

      {showFilters && (
        <div className="grid grid-cols-1 md:grid-cols-5 gap-2">
          <select className="nb-input text-xs" value={feature} onChange={(e) => setFeature(e.target.value)}>
            {FEATURES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <select className="nb-input text-xs" value={level} onChange={(e) => setLevel(e.target.value)}>
            {LEVELS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <input className="nb-input text-xs" value={accountId} onChange={(e) => setAccountId(e.target.value.replace(/\D/g, ''))} placeholder="Account ID" />
          <input className="nb-input text-xs" value={jobId} onChange={(e) => setJobId(e.target.value)} placeholder="Job ID" />
          <input className="nb-input text-xs" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Tìm trong log đang tải" />
        </div>
      )}

      <div className="flex flex-wrap gap-2 text-xs">
        {hasMore && <button className="nb-btn !py-1 !px-2" disabled={loading} onClick={loadOlder}>Tải lịch sử cũ hơn</button>}
        <button className="nb-btn !py-1 !px-2" onClick={copyVisible}>Sao chép</button>
        <button className="nb-btn !py-1 !px-2" onClick={() => downloadJson(visible)}>Xuất JSON</button>
        <button className="nb-btn !py-1 !px-2" onClick={clearView}>Xóa màn hình</button>
        {loading && <span className="opacity-60 self-center">Đang tải…</span>}
        {error && <span className="text-red-600 dark:text-red-400 self-center">{error}</span>}
      </div>

      <div
        ref={scrollerRef}
        className={`${compact ? 'max-h-64' : 'max-h-[32rem]'} overflow-auto border-2 border-black dark:border-white bg-white dark:bg-zinc-950`}
      >
        {visible.length === 0 ? (
          <div className="p-4 text-sm opacity-60">Chưa có event phù hợp bộ lọc hiện tại.</div>
        ) : visible.map((event) => (
          <div key={event.id} className="p-2 border-b border-zinc-300 dark:border-zinc-800 text-xs font-mono">
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <span className={`nb-badge ${levelClass(event.level)}`}>{String(event.level || 'info').toUpperCase()}</span>
              <span className="font-bold">{event.feature || 'system'}:{event.phase || 'event'}</span>
              <span className="opacity-50">#{event.id}</span>
              <span className="ml-auto opacity-60">{fmtTime(event.created_at)}</span>
            </div>
            <div className="whitespace-pre-wrap break-words">{event.message}</div>
            <div className="flex flex-wrap gap-2 mt-1 opacity-60 text-[10px]">
              {event.account_id != null && <span>account #{event.account_id}</span>}
              {event.job_id && <span>job {event.job_id}</span>}
              {event.correlation_id && <span>corr {event.correlation_id}</span>}
              {event.progress && <span>progress {JSON.stringify(event.progress)}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
