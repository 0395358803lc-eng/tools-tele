import { useCallback, useEffect, useState } from 'react'
import { Endpoints } from '../lib/api'
import { fmtTime } from '../lib/util'
import { jobStatusVi, jobTypeVi } from '../lib/vi'
import { useToast } from '../lib/toast.jsx'

const ACTIVE = new Set(['queued', 'running', 'paused', 'cancelling'])
const RETRY_ITEMS = new Set(['failed', 'pending', 'queued', 'running'])

function waitSeconds(value) {
  if (!value) return 0
  return Math.max(0, Math.ceil((new Date(value).getTime() - Date.now()) / 1000))
}

function processedOf(job) {
  if (job?.resumable) return Math.max(0, Number(job.total || 0) - Number(job.pending || 0))
  return Number(job.success || 0) + Number(job.failed || 0) + Number(job.skipped || 0) + Number(job.pending || 0)
}

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
  const [retryText, setRetryText] = useState('')

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

  async function pause(id) {
    setBusy(true)
    try { await Endpoints.pauseJob(id); toast.info('Đã tạm dừng tác vụ tại checkpoint an toàn'); await load() }
    catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }

  async function resume(id) {
    setBusy(true)
    try { await Endpoints.resumeJob(id); toast.success('Đã đưa tác vụ trở lại hàng đợi để tiếp tục'); await load() }
    catch (e) { toast.error(e.message) } finally { setBusy(false) }
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

  async function retryMessage(id) {
    const text = retryText.trim()
    if (!text) return toast.error('Nhập nội dung để chạy lại các mục chưa gửi')
    setBusy(true)
    let newJobId = null
    try {
      await Endpoints.retryMessageJob(id, text, (event) => { if (event?.job_id) newJobId = event.job_id })
      toast.success('Đã chạy lại các mục FloodWait chưa gửi')
      setRetryText('')
      const list = await Endpoints.jobs(100); setJobs(list || [])
      if (newJobId) setSelected(await Endpoints.job(newJobId))
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }

  async function exportJob(kind) {
    if (!selected?.id) return
    setBusy(true)
    try {
      await Endpoints.downloadJobExport(selected.id, kind)
      toast.success(`Đã tải ${kind.toUpperCase()} của tác vụ`)
    } catch (e) { toast.error(e.message) }
    finally { setBusy(false) }
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
                  <td className="p-2 font-mono text-xs">{processedOf(j)}/{j.total} · ✓{j.success} · ✕{j.failed} · ⧗{j.pending}</td>
                  <td className="p-2 text-xs">{fmtTime(j.created_at)}</td>
                  <td className="p-2 text-right"><div className="flex justify-end gap-1">
                    {j.resumable && ['queued', 'running'].includes(j.status) && <button className="nb-btn !py-1 !px-2 text-xs" disabled={busy} onClick={() => pause(j.id)}>Tạm dừng</button>}
                    {j.resumable && j.status === 'paused' && <button className="nb-btn-pri !py-1 !px-2 text-xs" disabled={busy} onClick={() => resume(j.id)}>Tiếp tục</button>}
                    {ACTIVE.has(j.status) && <button className="nb-btn-err !py-1 !px-2 text-xs" disabled={busy} onClick={() => cancel(j.id)}>Hủy</button>}
                  </div></td>
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
            <button className="nb-btn !py-1 !px-2 text-xs" disabled={busy} onClick={() => exportJob('csv')}>CSV</button>
            <button className="nb-btn !py-1 !px-2 text-xs" disabled={busy} onClick={() => exportJob('xlsx')}>XLSX</button>
            {selected.retry_supported && !ACTIVE.has(selected.status) && (selected.items || []).some((i) => RETRY_ITEMS.has(i.status)) && (
              <button className="nb-btn !py-1 !px-2 text-xs" disabled={busy} onClick={() => retry(selected.id)}>Chạy lại mục lỗi/đang chờ</button>
            )}
            <button className="nb-btn !py-1 !px-2" onClick={() => setSelected(null)}>✕</button>
          </div>
          <div className="flex flex-wrap gap-2 mb-3 text-[11px]">
            {selected.heartbeat_at && <span className="nb-badge bg-white text-black">Heartbeat {fmtTime(selected.heartbeat_at)}</span>}
            <span className="nb-badge bg-white text-black">Checkpoint {processedOf(selected)}/{selected.total}</span>
            {selected.resume_count > 0 && <span className="nb-badge bg-white text-black">Đã tiếp tục {selected.resume_count} lần</span>}
            {selected.paused_at && <span className="nb-badge bg-brand-warn text-black">Tạm dừng từ {fmtTime(selected.paused_at)}</span>}
          </div>
          {selected.delivery && (
            <div className="flex flex-wrap gap-2 mb-3 text-xs">
              <span className="nb-badge bg-brand-ok text-black">Đã gửi {selected.delivery.delivered}</span>
              <span className="nb-badge bg-brand-err text-black">Lỗi {selected.delivery.failed}</span>
              <span className="nb-badge bg-brand-warn text-black">Chờ {selected.delivery.pending}</span>
              <span className="nb-badge bg-brand-violet text-black">Đã thử {selected.delivery.attempted}</span>
              <span className="nb-badge bg-white text-black">Tỷ lệ {selected.delivery.delivery_rate}%</span>
              {selected.delivery.safe_retry > 0 && <span className="nb-badge bg-brand-pri text-black">Retry an toàn {selected.delivery.safe_retry}</span>}
            </div>
          )}
          {selected.type === 'message_multi_send' && (selected.items || []).some((i) => i.status === 'pending' && i.error_code === 'FloodWaitError' && Number(i.attempts || 0) === 0) && (
            <div className="nb-card-sm p-3 mb-3">
              <div className="text-xs font-bold uppercase mb-1">Chạy lại an toàn mục chưa gửi do FloodWait</div>
              <textarea className="nb-input min-h-20 text-sm" value={retryText} onChange={(e) => setRetryText(e.target.value)} placeholder="Nhập lại nội dung tin nhắn. Hệ thống không lưu plaintext nội dung cũ." />
              <div className="text-[10px] opacity-60 mt-1">Chỉ retry item attempts=0; timeout hoặc trạng thái gửi không xác định sẽ không được tự động gửi lại.</div>
              <button className="nb-btn-pri !py-1 !px-2 text-xs mt-2" disabled={busy || !retryText.trim()} onClick={() => retryMessage(selected.id)}>Chạy lại mục an toàn</button>
            </div>
          )}
          <div className="space-y-1 max-h-72 overflow-auto">
            {(selected.items || []).map((item) => (
              <div key={item.id} className="nb-card-sm p-2 flex gap-2 items-center text-xs">
                <span className={'nb-badge text-black ' + statusClass(item.status)}>{jobStatusVi(item.status)}</span>
                <span className="font-mono">Tài khoản #{item.account_id ?? 'đã xóa'}</span>
                {item.target && <span className="font-mono font-bold truncate max-w-[35%]" title={item.target}>→ {item.target}</span>}
                <span className="opacity-60">lần thử {item.attempts}</span>
                {item.status === 'rate_limited' && item.next_retry_at && <span className="nb-badge bg-brand-warn text-black">FloodWait ~{waitSeconds(item.next_retry_at)}s</span>}
                {item.status === 'in_flight_unknown' && <span className="nb-badge bg-brand-warn text-black">Không tự retry để tránh trùng</span>}
                {item.error_detail && <span className="ml-auto opacity-70 truncate max-w-[55%]" title={item.error_detail}>{item.error_detail}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
