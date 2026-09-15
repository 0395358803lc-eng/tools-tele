import { useCallback, useEffect, useMemo, useState } from 'react'
import { Endpoints } from '../lib/api'
import { fmtTime } from '../lib/util'
import { jobStatusVi, jobTypeVi } from '../lib/vi'
import RealtimeLogPanel from '../components/RealtimeLogPanel.jsx'

const ACTIVE = new Set(['queued', 'running', 'paused', 'cancelling'])

function Metric({ label, value, hint, tone = 'bg-white' }) {
  return (
    <div className={`nb-card-sm p-3 ${tone}`}>
      <div className="text-[10px] font-extrabold uppercase opacity-60">{label}</div>
      <div className="text-2xl font-black">{value}</div>
      {hint && <div className="text-[10px] opacity-60 mt-1">{hint}</div>}
    </div>
  )
}

export default function ActivityTab({ accounts = [] }) {
  const [jobs, setJobs] = useState([])
  const [recentEvents, setRecentEvents] = useState([])
  const [loadError, setLoadError] = useState('')

  const load = useCallback(async () => {
    try {
      const [jobRows, eventResult] = await Promise.all([
        Endpoints.jobs(100),
        Endpoints.eventHistory({ limit: 100 }),
      ])
      setJobs(jobRows || [])
      setRecentEvents(eventResult?.items || [])
      setLoadError('')
    } catch (e) {
      setLoadError(e.message || 'Không tải được tổng quan hoạt động')
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 10000)
    return () => clearInterval(timer)
  }, [load])

  const activeJobs = useMemo(() => jobs.filter((job) => ACTIVE.has(job.status)), [jobs])
  const connectedAccounts = useMemo(() => accounts.filter((account) => account.status === 'connected').length, [accounts])
  const floodWaitAccounts = useMemo(() => accounts.filter((account) => {
    if (!account.flood_wait_until) return false
    return new Date(account.flood_wait_until).getTime() > Date.now()
  }).length, [accounts])
  const recentWarnings = useMemo(() => recentEvents.filter((event) => ['warning', 'error'].includes(event.level)).length, [recentEvents])

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div>
          <h2 className="font-extrabold uppercase">Hoạt động realtime</h2>
          <div className="text-xs opacity-60">Theo dõi worker, tác vụ, account và cảnh báo theo thời gian thực.</div>
        </div>
        <button className="nb-btn !py-1 !px-2 text-xs ml-auto" onClick={load}>Làm mới tổng quan</button>
      </div>

      {loadError && <div className="nb-card-sm p-3 text-sm text-red-600 dark:text-red-400">{loadError}</div>}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Metric label="Tác vụ đang hoạt động" value={activeJobs.length} hint={`${jobs.length} tác vụ được lưu`} tone="bg-brand-pri" />
        <Metric label="Account đã kết nối" value={connectedAccounts} hint={`${accounts.length} account trong tenant`} tone="bg-brand-ok" />
        <Metric label="Account FloodWait" value={floodWaitAccounts} hint="Không ảnh hưởng account khác" tone={floodWaitAccounts ? 'bg-brand-warn' : 'bg-white'} />
        <Metric label="Cảnh báo gần đây" value={recentWarnings} hint="Trong 100 event gần nhất" tone={recentWarnings ? 'bg-brand-warn' : 'bg-white'} />
      </div>

      <div className="nb-card p-4">
        <div className="font-extrabold uppercase mb-2">Tác vụ đang chạy</div>
        {activeJobs.length === 0 ? (
          <div className="text-sm opacity-60">Không có tác vụ đang hoạt động.</div>
        ) : (
          <div className="space-y-2">
            {activeJobs.slice(0, 12).map((job) => (
              <div key={job.id} className="nb-card-sm p-2 flex flex-wrap items-center gap-2 text-xs">
                <span className="font-bold">{jobTypeVi(job.type)}</span>
                <span className="nb-badge bg-brand-violet text-black">{jobStatusVi(job.status)}</span>
                <span className="font-mono opacity-60">{job.id}</span>
                <span className="ml-auto">{Number(job.total || 0) - Number(job.pending || 0)}/{job.total || 0}</span>
                {job.heartbeat_at && <span className="opacity-60">heartbeat {fmtTime(job.heartbeat_at)}</span>}
              </div>
            ))}
          </div>
        )}
      </div>

      <RealtimeLogPanel title="Luồng hoạt động toàn hệ thống của tài khoản" />
    </div>
  )
}
