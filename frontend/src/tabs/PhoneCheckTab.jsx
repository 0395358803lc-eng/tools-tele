import { useCallback, useEffect, useMemo, useState } from 'react'
import { Endpoints } from '../lib/api'
import { fmtTime } from '../lib/util'
import { useToast } from '../lib/toast.jsx'

const ACTIVE = new Set(['queued', 'running', 'cancelling'])
const ITEM_VI = {
  queued: 'Đang chờ', processing: 'Đang kiểm tra', in_flight_unknown: 'Chờ phục hồi',
  retry_required: 'Sẽ thử lại', temporary_error: 'Lỗi tạm thời', rate_limited: 'FloodWait',
  found: 'Tìm thấy', not_discoverable: 'Không thể phát hiện', invalid: 'Số không hợp lệ',
  permanent_error: 'Lỗi', cancelled: 'Đã hủy',
}

function tone(status) {
  if (status === 'found' || status === 'completed') return 'bg-brand-ok'
  if (['invalid','permanent_error','failed','completed_with_errors'].includes(status)) return 'bg-brand-err'
  if (['not_discoverable','rate_limited','paused','cancelled','interrupted'].includes(status)) return 'bg-brand-warn'
  return 'bg-brand-violet'
}

export default function PhoneCheckTab({ accounts }) {
  const toast = useToast()
  const connected = useMemo(() => (accounts || []).filter((a) => a.status === 'connected'), [accounts])
  const [selected, setSelected] = useState([])
  const [phones, setPhones] = useState('')
  const [region, setRegion] = useState('VN')
  const [interval, setIntervalValue] = useState(1.2)
  const [attempts, setAttempts] = useState(3)
  const [name, setName] = useState('Kiểm tra số Telegram')
  const [summary, setSummary] = useState(null)
  const [jobs, setJobs] = useState([])
  const [detail, setDetail] = useState(null)
  const [busy, setBusy] = useState(false)
  const [fileBusy, setFileBusy] = useState(false)

  useEffect(() => {
    setSelected((old) => old.filter((id) => connected.some((a) => a.id === id)))
  }, [connected])

  const loadJobs = useCallback(async () => {
    try {
      const rows = await Endpoints.phoneCheckJobs(50)
      setJobs(rows || [])
      if (detail?.id) setDetail(await Endpoints.phoneCheckJob(detail.id))
    } catch (e) { if (e.status !== 401) toast.error(e.message) }
  }, [detail?.id, toast])

  useEffect(() => {
    loadJobs()
    const timer = window.setInterval(loadJobs, 4000)
    return () => window.clearInterval(timer)
  }, [loadJobs])

  function toggleAccount(id) {
    setSelected((old) => old.includes(id) ? old.filter((x) => x !== id) : [...old, id])
  }

  async function preview() {
    const values = phones.split(/\r?\n/).map((v) => v.trim()).filter(Boolean)
    if (!values.length) return toast.error('Nhập ít nhất một số điện thoại')
    setBusy(true)
    try {
      const r = await Endpoints.previewPhoneChecks(values, region)
      setSummary(r.summary)
      setPhones((r.phones || []).join('\n'))
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }

  async function importFile(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setFileBusy(true)
    try {
      const r = await Endpoints.importPhoneChecks(file, region)
      setPhones((r.phones || []).join('\n'))
      setSummary(r.summary)
      toast.info(`Đã đọc ${r.summary?.unique || 0} số duy nhất từ ${file.name}`)
    } catch (e) { toast.error(e.message) } finally { setFileBusy(false) }
  }

  async function createJob() {
    if (!selected.length) return toast.error('Chọn ít nhất một tài khoản đang kết nối')
    const values = phones.split(/\r?\n/).map((v) => v.trim()).filter(Boolean)
    if (!values.length) return toast.error('Chưa có số điện thoại')
    setBusy(true)
    try {
      const r = await Endpoints.createPhoneCheckJob({
        account_ids: selected,
        name: name.trim() || 'Kiểm tra số Telegram',
        phones: values,
        phone_region: region,
        max_attempts: Number(attempts),
        min_request_interval: Number(interval),
      })
      toast.info(`Đã tạo tác vụ ${r.job_id}`)
      setSummary(r.summary)
      await loadJobs()
      setDetail(await Endpoints.phoneCheckJob(r.job_id))
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }

  async function action(kind) {
    if (!detail?.id) return
    setBusy(true)
    try {
      if (kind === 'pause') await Endpoints.pausePhoneCheckJob(detail.id)
      if (kind === 'resume') await Endpoints.resumePhoneCheckJob(detail.id)
      if (kind === 'cancel') await Endpoints.cancelPhoneCheckJob(detail.id)
      await loadJobs()
      setDetail(await Endpoints.phoneCheckJob(detail.id))
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      <div className="nb-card p-4">
        <div className="font-extrabold uppercase">Check số Telegram</div>
        <p className="text-sm opacity-70 mt-1">Dùng chính các session đã đăng nhập trong ứng dụng. Nếu tài khoản đã gắn proxy, việc kiểm tra tự động đi qua proxy đó.</p>
        <div className="mt-4 grid grid-cols-1 xl:grid-cols-[1fr_1.25fr] gap-4">
          <div>
            <div className="text-xs font-extrabold uppercase mb-2">1. Chọn tài khoản</div>
            <div className="space-y-2 max-h-64 overflow-auto">
              {connected.length ? connected.map((a) => (
                <label key={a.id} className="nb-card-sm p-2 flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={selected.includes(a.id)} onChange={() => toggleAccount(a.id)} />
                  <span className="font-bold">{`${a.first_name || ''} ${a.last_name || ''}`.trim() || a.phone}</span>
                  <span className="font-mono text-xs opacity-60 ml-auto">{a.phone}</span>
                </label>
              )) : <div className="text-sm opacity-60">Chưa có tài khoản Telegram đang kết nối.</div>}
            </div>
            <div className="flex gap-2 mt-2">
              <button className="nb-btn !py-1 !px-2 text-xs" onClick={() => setSelected(connected.map((a) => a.id))}>Chọn tất cả</button>
              <button className="nb-btn !py-1 !px-2 text-xs" onClick={() => setSelected([])}>Bỏ chọn</button>
            </div>
          </div>
          <div>
            <div className="text-xs font-extrabold uppercase mb-2">2. Danh sách số</div>
            <textarea className="nb-input min-h-48 font-mono text-xs" value={phones} onChange={(e) => { setPhones(e.target.value); setSummary(null) }} placeholder={'+84901234567\n0901234567\n...'} />
            <div className="flex gap-2 flex-wrap mt-2">
              <label className="nb-btn !py-1 !px-2 text-xs cursor-pointer">{fileBusy ? 'Đang đọc...' : 'Nhập TXT / CSV / Excel'}<input className="hidden" type="file" accept=".txt,.csv,.xls,.xlsx" disabled={fileBusy} onChange={importFile} /></label>
              <button className="nb-btn !py-1 !px-2 text-xs" disabled={busy} onClick={preview}>Chuẩn hóa & kiểm tra</button>
              <button className="nb-btn !py-1 !px-2 text-xs" onClick={() => { setPhones(''); setSummary(null) }}>Xóa danh sách</button>
            </div>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
          <label className="text-xs font-bold">Tên tác vụ<input className="nb-input mt-1" value={name} onChange={(e) => setName(e.target.value)} /></label>
          <label className="text-xs font-bold">Vùng số<input className="nb-input mt-1 uppercase" maxLength={3} value={region} onChange={(e) => setRegion(e.target.value.toUpperCase())} /></label>
          <label className="text-xs font-bold">Giãn cách / tài khoản (giây)<input className="nb-input mt-1" type="number" min="0.1" max="60" step="0.1" value={interval} onChange={(e) => setIntervalValue(e.target.value)} /></label>
          <label className="text-xs font-bold">Số lần thử tối đa<input className="nb-input mt-1" type="number" min="1" max="10" value={attempts} onChange={(e) => setAttempts(e.target.value)} /></label>
        </div>
        {summary && <div className="flex flex-wrap gap-2 mt-3 text-xs"><span className="nb-badge bg-brand-violet text-black">Đầu vào {summary.input}</span><span className="nb-badge bg-brand-ok text-black">Hợp lệ {summary.valid}</span><span className="nb-badge bg-brand-warn text-black">Trùng {summary.duplicates}</span><span className="nb-badge bg-brand-err text-black">Không hợp lệ {summary.invalid}</span></div>}
        <button className="nb-btn-pri mt-4" disabled={busy || !selected.length} onClick={createJob}>{busy ? 'Đang xử lý...' : 'Tạo tác vụ check số'}</button>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[0.8fr_1.2fr] gap-4">
        <div className="nb-card p-4">
          <div className="flex items-center gap-2 mb-3"><div className="font-extrabold uppercase">Lịch sử tác vụ</div><button className="nb-btn !py-1 !px-2 text-xs ml-auto" onClick={loadJobs}>Làm mới</button></div>
          <div className="space-y-2 max-h-[620px] overflow-auto">
            {jobs.map((j) => <button key={j.id} className="nb-card-sm p-3 w-full text-left" onClick={async () => setDetail(await Endpoints.phoneCheckJob(j.id))}><div className="flex gap-2 items-center"><span className="font-bold truncate">{j.name}</span><span className={'nb-badge text-black ml-auto ' + tone(j.status)}>{j.status}</span></div><div className="text-xs font-mono opacity-60 mt-1">{j.found}/{j.total} tìm thấy · còn {j.pending} · {fmtTime(j.created_at)}</div></button>)}
            {!jobs.length && <div className="text-sm opacity-60">Chưa có tác vụ check số.</div>}
          </div>
        </div>

        <div className="nb-card p-4">
          {!detail ? <div className="text-sm opacity-60">Chọn một tác vụ để xem tiến độ và kết quả.</div> : <>
            <div className="flex gap-2 items-start flex-wrap"><div><div className="font-extrabold uppercase">{detail.name}</div><div className="font-mono text-[10px] opacity-60">{detail.id}</div></div><span className={'nb-badge text-black ' + tone(detail.status)}>{detail.status}</span><div className="ml-auto flex gap-2 flex-wrap">{detail.status === 'running' || detail.status === 'queued' ? <button className="nb-btn !py-1 !px-2 text-xs" disabled={busy} onClick={() => action('pause')}>Tạm dừng</button> : null}{detail.status === 'paused' || detail.status === 'interrupted' ? <button className="nb-btn-pri !py-1 !px-2 text-xs" disabled={busy} onClick={() => action('resume')}>Tiếp tục</button> : null}{ACTIVE.has(detail.status) || detail.status === 'paused' ? <button className="nb-btn-err !py-1 !px-2 text-xs" disabled={busy} onClick={() => action('cancel')}>Hủy</button> : null}<a className="nb-btn !py-1 !px-2 text-xs" href={`/api/phone-checks/jobs/${detail.id}/export.csv`}>CSV</a><a className="nb-btn !py-1 !px-2 text-xs" href={`/api/phone-checks/jobs/${detail.id}/export.json`}>JSON</a></div></div>
            <div className="flex gap-2 flex-wrap mt-3 text-xs"><span className="nb-badge bg-brand-ok text-black">Tìm thấy {detail.counts?.found || 0}</span><span className="nb-badge bg-brand-warn text-black">Không thể phát hiện {detail.counts?.not_discoverable || 0}</span><span className="nb-badge bg-brand-violet text-black">Đang chờ {(detail.pending || 0)}</span><span className="nb-badge bg-brand-err text-black">Lỗi {(detail.counts?.permanent_error || 0) + (detail.counts?.invalid || 0)}</span></div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-3">{(detail.accounts || []).map((a) => <div key={a.account_id} className="nb-card-sm p-2 text-xs"><div className="font-bold">{a.name}</div><div className="font-mono opacity-60">{a.processed}/{a.assigned_total} · {a.status} · tìm thấy {a.found}</div></div>)}</div>
            <div className="overflow-auto max-h-[430px] mt-4"><table className="w-full text-xs"><thead className="text-[10px] uppercase font-extrabold border-b-2 border-black dark:border-white sticky top-0 bg-white dark:bg-zinc-900"><tr><th className="text-left p-2">Số</th><th className="text-left p-2">Kết quả</th><th className="text-left p-2">Tài khoản</th><th className="text-left p-2">Telegram</th><th className="text-left p-2">Hoạt động</th></tr></thead><tbody>{(detail.items || []).map((item) => <tr key={item.id} className="border-b border-zinc-300 dark:border-zinc-700"><td className="p-2 font-mono"><div>{item.original_phone}</div>{item.normalized_phone && item.normalized_phone !== item.original_phone && <div className="opacity-50">→ {item.normalized_phone}</div>}</td><td className="p-2"><span className={'nb-badge text-black ' + tone(item.status)}>{ITEM_VI[item.status] || item.status}</span>{item.error_detail && <div className="mt-1 opacity-60 max-w-56 truncate" title={item.error_detail}>{item.error_detail}</div>}</td><td className="p-2 font-mono">#{item.account_id ?? '—'}</td><td className="p-2">{item.status === 'found' ? <><div className="font-bold">{`${item.first_name || ''} ${item.last_name || ''}`.trim() || 'Không có tên'}</div><div className="font-mono opacity-60">{item.username ? '@' + item.username : '—'} · ID {item.telegram_user_id}</div></> : '—'}</td><td className="p-2">{item.presence || '—'}{item.last_online_at && <div className="opacity-60">{fmtTime(item.last_online_at)}</div>}</td></tr>)}</tbody></table></div>
          </>}
        </div>
      </div>
    </div>
  )
}
