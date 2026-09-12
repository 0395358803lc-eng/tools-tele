import { useCallback, useEffect, useState } from 'react'
import { Endpoints } from '../lib/api'
import { fmtTime } from '../lib/util'
import { jobStatusVi, jobTypeVi } from '../lib/vi'
import { useToast } from '../lib/toast.jsx'

const ACTIVE = new Set(['queued', 'running', 'cancelling'])
const RETRY_ITEMS = new Set(['failed', 'pending', 'queued', 'running'])

function statusClass(status) {
  if (status === 'completed') return 'bg-brand-ok'
  if (status === 'failed' || status === 'completed_with_errors') return 'bg-brand-err'
  if (status === 'cancelled' || status === 'interrupted') return 'bg-brand-warn'
  return 'bg-brand-violet'
}

export default function JobsTab() {
  const toast = useToast()
  const [jobs, setJobs] = useState([])
  const [selected, setSelected] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      const list = await Endpoints.jobs(100)
      setJobs(list || [])
      if (selected?.id) {
        const detail = await Endpoints.job(selected.id)
        setSelected(detail)
      }
    } catch (e) { toast.error(e.message) }
  }, [selected?.id, toast])

  useEffect(() => {
    load()
    const timer = setInterval(load, 5000)
    return () => clearInterval(timer)
  }, [load])

  async function openJob(id) {
    try { setSelected(await Endpoints.job(id)) } catch (e) { toast.error(e.message) }
  }

  async function cancel(id) {
    setBusy(true)
    try {
      const r = await Endpoints.cancelJob(id)
      toast.info(r.ok ? 'Đã yêu cầu hủy tác vụ' : 'Tác vụ không còn có thể hủy')
      await load()
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }

  async function retry(id) {
    setBusy(true)
    let retryJobId = null
    try {
      await Endpoints.retryJob(id, (event) => {
        if (event?.job_id) retryJobId = event.job_id
      })
      toast.info('Đã chạy lại tác vụ hoàn tất')
      const list = await Endpoints.jobs(100)
      setJobs(list || [])
      if (retryJobId) setSelected(await Endpoints.job(retryJobId))
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <h2 className="font-extrabold uppercase">Tác vụ hàng loạt</h2>
        <span className="text-xs opacity-60">Được lưu trong SQL</span>
        <button className="nb-btn !py-1 !px-2 text-xs ml-auto" onClick={load}>Làm mới</button>
      </div>

      <div className="nb-card p-4 overflow-auto">
        {jobs.length === 0 ? (
          <div className="text-sm opacity-60">Chưa có tác vụ hàng loạt.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-[10px] uppercase font-extrabold border-b-2 border-black dark:border-white">
              <tr><th className="text-left p-2">Loại</th><th className="text-left p-2">Trạng thái</th><th className="text-left p-2">Tiến độ</th><th className="text-left p-2">Đã tạo</th><th className="p-2" /></tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id} className="border-b border-zinc-300 dark:border-zinc-700">
                  <td className="p-2"><button className="font-bold hover:underline" onClick={() => openJob(j.id)}>{jobTypeVi(j.type)}</button><div className="font-mono text-[9px] opacity-50">{j.id}</div></td>
                  <td className="p-2"><span className={'nb-badge text-black ' + statusClass(j.status)}>{jobStatusVi(j.status)}</span></td>
                  <td className="p-2 font-mono text-xs">{j.success + j.failed + j.skipped + j.pending}/{j.total} · ✓{j.success} · ✕{j.failed} · ⧗{j.pending}</td>
                  <td className="p-2 text-xs">{fmtTime(j.created_at)}</td>
                  <td className="p-2 text-right">{ACTIVE.has(j.status) && <button className="nb-btn-err !py-1 !px-2 text-xs" disabled={busy} onClick={() => cancel(j.id)}>Hủy</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {selected && (
        <div className="nb-card p-4">
          <div className="flex items-center gap-2 mb-3">
            <div><div className="font-extrabold uppercase">{jobTypeVi(selected.type)}</div><div className="text-[10px] font-mono opacity-60">{selected.id}</div></div>
            <span className={'nb-badge text-black ml-auto ' + statusClass(selected.status)}>{jobStatusVi(selected.status)}</span>
            {selected.retry_supported && !ACTIVE.has(selected.status) && (selected.items || []).some((i) => RETRY_ITEMS.has(i.status)) && (
              <button className="nb-btn !py-1 !px-2 text-xs" disabled={busy} onClick={() => retry(selected.id)}>Chạy lại mục lỗi/đang chờ</button>
            )}
            <button className="nb-btn !py-1 !px-2" onClick={() => setSelected(null)}>✕</button>
          </div>
          <div className="space-y-1 max-h-72 overflow-auto">
            {(selected.items || []).map((item) => (
              <div key={item.id} className="nb-card-sm p-2 flex gap-2 items-center text-xs">
                <span className={'nb-badge text-black ' + statusClass(item.status)}>{jobStatusVi(item.status)}</span>
                <span className="font-mono">Tài khoản #{item.account_id ?? 'đã xóa'}</span>
                {item.target && <span className="font-mono font-bold truncate max-w-[35%]" title={item.target}>→ {item.target}</span>}
                <span className="opacity-60">lần thử {item.attempts}</span>
                {item.error_detail && <span className="ml-auto opacity-70 truncate max-w-[55%]" title={item.error_detail}>{item.error_detail}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
