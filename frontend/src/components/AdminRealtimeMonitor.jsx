import { useEffect, useMemo, useState } from 'react'
import { Endpoints } from '../lib/api'

function fmt(value) { return value ? new Date(value).toLocaleString('vi-VN') : '—' }
function shortId(value) { return value ? `${String(value).slice(0, 8)}…` : '—' }
function Stat({ label, value }) {
  return <div className="nb-card p-3"><div className="text-[10px] font-bold uppercase opacity-60">{label}</div>
    <div className="text-2xl font-extrabold">{value ?? '—'}</div></div>
}
function Pill({ bad, children }) {
  return <span className={`inline-block px-2 py-1 text-xs font-bold border border-current ${bad ? 'bg-brand-err text-black' : ''}`}>{children}</span>
}

export default function AdminRealtimeMonitor({ users = [] }) {
  const [snapshot, setSnapshot] = useState(null)
  const [selectedUser, setSelectedUser] = useState('')
  const [detail, setDetail] = useState(null)
  const [events, setEvents] = useState([])
  const [filters, setFilters] = useState({ user_id: '', feature: '', level: '', account_id: '', job_id: '' })
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  const userNames = useMemo(() => Object.fromEntries(users.map((u) => [u.id, u.username])), [users])

  async function refreshSnapshot() {
    try { setSnapshot(await Endpoints.adminRealtimeSummary()) }
    catch (e) { setErr(e.message || 'Không tải được realtime monitor') }
  }

  useEffect(() => {
    refreshSnapshot()
    const id = setInterval(refreshSnapshot, 5000)
    return () => clearInterval(id)
  }, [])

  async function openUser(uid) {
    if (!uid) { setSelectedUser(''); setDetail(null); return }
    setLoading(true); setErr(''); setSelectedUser(uid)
    try {
      const data = await Endpoints.adminRealtimeUser(uid)
      setDetail(data)
      const next = { ...filters, user_id: uid, account_id: '', job_id: '' }
      setFilters(next)
      setEvents(await Endpoints.adminRealtimeEvents({ limit: 200, ...next }))
    } catch (e) { setErr(e.message || 'Không tải được dữ liệu user') }
    finally { setLoading(false) }
  }

  async function loadTimeline(next = filters) {
    setLoading(true); setErr('')
    try { setEvents(await Endpoints.adminRealtimeEvents({ limit: 200, ...next })) }
    catch (e) { setErr(e.message || 'Không tải được timeline') }
    finally { setLoading(false) }
  }

  async function loadOlderTimeline() {
    if (!events.length) return
    setLoading(true); setErr('')
    try {
      const older = await Endpoints.adminRealtimeEvents({ limit: 200, ...filters, before_id: Math.min(...events.map((e) => Number(e.id))) })
      const seen = new Set(events.map((e) => e.id))
      setEvents([...events, ...older.filter((e) => !seen.has(e.id))])
    } catch (e) { setErr(e.message || 'Không tải được lịch sử cũ hơn') }
    finally { setLoading(false) }
  }

  function focusAccount(id) {
    const next = { ...filters, user_id: selectedUser || filters.user_id, account_id: String(id), job_id: '' }
    setFilters(next); loadTimeline(next)
  }

  function focusJob(id) {
    const next = { ...filters, user_id: selectedUser || filters.user_id, job_id: String(id), account_id: '' }
    setFilters(next); loadTimeline(next)
  }

  const s = snapshot || {}
  return <div className="space-y-4">
    {err && <div className="nb-card p-3 bg-brand-err text-black font-bold">{err}</div>}
    <div className="grid grid-cols-2 md:grid-cols-5 xl:grid-cols-9 gap-3">
      <Stat label="Active users" value={s.active_users} />
      <Stat label="Connected" value={s.connected_accounts} />
      <Stat label="FloodWait" value={s.flood_wait} />
      <Stat label="Proxy fail" value={s.proxy_failures} />
      <Stat label="Active jobs" value={s.active_jobs} />
      <Stat label="Failed jobs" value={s.failed_jobs} />
      <Stat label="Queue depth" value={s.queue_depth} />
      <Stat label="Events/min" value={s.event_rate_per_min} />
      <Stat label="Message/Phone Q" value={`${s.message_queue_depth ?? 0}/${s.phone_queue_depth ?? 0}`} />
    </div>

    <div className="grid xl:grid-cols-[1.2fr_1fr] gap-4">
      <div className="nb-card p-4 overflow-auto">
        <div className="flex items-center gap-2 mb-3"><h2 className="font-extrabold uppercase text-sm">User đang hoạt động</h2>
          <div className="flex-1" /><span className="text-xs opacity-60">Cập nhật mỗi 5 giây · {fmt(s.generated_at)}</span></div>
        <table className="w-full text-sm"><thead><tr className="text-left border-b-2 border-current">
          <th>User</th><th>Connected</th><th>FloodWait</th><th>Jobs</th><th>Failed</th><th>Proxy fail</th>
        </tr></thead><tbody>{(s.users || []).map((row) => <tr key={row.user_id} className="border-b border-current/20">
          <td className="py-2"><button className="font-bold underline" onClick={() => openUser(row.user_id)}>{userNames[row.user_id] || shortId(row.user_id)}</button></td>
          <td>{row.connected_accounts}</td><td>{row.flood_wait}</td><td>{row.active_jobs}</td><td>{row.failed_jobs}</td><td>{row.proxy_failures}</td>
        </tr>)}</tbody></table>
      </div>
      <div className="nb-card p-4">
        <h2 className="font-extrabold uppercase text-sm mb-3">Recent errors</h2>
        <div className="space-y-2 max-h-80 overflow-auto">{(s.recent_errors || []).map((e) => <button key={e.id}
          className="w-full text-left border border-current/30 p-2 text-xs" onClick={() => {
            const next = { ...filters, user_id: e.user_id || '', feature: e.feature || '', level: e.level || '', account_id: e.account_id ? String(e.account_id) : '', job_id: e.job_id || '' }
            setFilters(next); if (e.user_id) setSelectedUser(e.user_id); loadTimeline(next)
          }}>
          <div className="flex gap-2"><Pill bad={e.level === 'error'}>{e.level}</Pill><b>{e.feature}:{e.phase}</b><span className="ml-auto opacity-60">{fmt(e.created_at)}</span></div>
          <div className="mt-1 break-words">{e.message}</div>
          <div className="opacity-50">{userNames[e.user_id] || shortId(e.user_id)} · account {e.account_id || '—'} · job {shortId(e.job_id)}</div>
        </button>)}</div>
      </div>
    </div>

    {detail && <div className="grid xl:grid-cols-2 gap-4">
      <div className="nb-card p-4 overflow-auto"><h2 className="font-extrabold uppercase text-sm mb-3">Accounts · {userNames[detail.user_id] || shortId(detail.user_id)}</h2>
        <table className="w-full text-sm"><thead><tr className="text-left border-b-2 border-current"><th>ID</th><th>Tài khoản</th><th>Status</th><th>FloodWait</th><th>Proxy</th></tr></thead>
        <tbody>{(detail.accounts || []).map((a) => <tr key={a.id} className="border-b border-current/20 cursor-pointer" onClick={() => focusAccount(a.id)}>
          <td className="py-2">{a.id}</td><td>{a.username ? `@${a.username}` : a.phone}</td><td>{a.status}</td><td>{a.in_flood_wait ? fmt(a.flood_wait_until) : '—'}</td><td>{a.proxy ? `${a.proxy.active_slot}/${a.proxy.last_status}` : '—'}</td>
        </tr>)}</tbody></table>
      </div>
      <div className="nb-card p-4 overflow-auto"><h2 className="font-extrabold uppercase text-sm mb-3">Jobs gần đây</h2>
        <table className="w-full text-sm"><thead><tr className="text-left border-b-2 border-current"><th>Job</th><th>Type</th><th>Status</th><th>Tiến độ</th><th>Heartbeat</th></tr></thead>
        <tbody>{(detail.jobs || []).map((j) => <tr key={j.id} className="border-b border-current/20 cursor-pointer" onClick={() => focusJob(j.id)}>
          <td className="py-2 font-mono text-xs">{shortId(j.id)}</td><td>{j.type}</td><td>{j.status}</td><td>{j.success || 0}/{j.total || 0} · lỗi {j.failed || 0}</td><td>{fmt(j.heartbeat_at)}</td>
        </tr>)}</tbody></table>
      </div>
    </div>}

    <div className="nb-card p-4 space-y-3">
      <div className="flex items-center gap-2"><h2 className="font-extrabold uppercase text-sm">Timeline vận hành</h2><div className="flex-1" />
        <button className="nb-btn" disabled={loading} onClick={() => loadTimeline()}>{loading ? 'Đang tải…' : 'Làm mới timeline'}</button></div>
      <div className="grid md:grid-cols-5 gap-2">
        <select className="nb-input" value={filters.user_id} onChange={(e) => {
          const uid = e.target.value; setFilters({ ...filters, user_id: uid, account_id: '', job_id: '' }); if (uid) openUser(uid)
        }}><option value="">Tất cả tenant</option>{users.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}</select>
        <input className="nb-input" placeholder="feature: proxy, messaging..." value={filters.feature} onChange={(e) => setFilters({ ...filters, feature: e.target.value })} />
        <select className="nb-input" value={filters.level} onChange={(e) => setFilters({ ...filters, level: e.target.value })}>
          <option value="">Mọi severity</option><option value="debug">debug</option><option value="info">info</option><option value="success">success</option><option value="warning">warning</option><option value="error">error</option>
        </select>
        <input className="nb-input" placeholder="account ID" value={filters.account_id} onChange={(e) => setFilters({ ...filters, account_id: e.target.value })} />
        <input className="nb-input" placeholder="job ID" value={filters.job_id} onChange={(e) => setFilters({ ...filters, job_id: e.target.value })} />
      </div>
      <div className="flex justify-end"><button className="nb-btn-pri" disabled={loading} onClick={() => loadTimeline()}>Áp dụng bộ lọc</button></div>
      <div className="overflow-auto max-h-[560px]"><table className="w-full text-sm"><thead><tr className="text-left border-b-2 border-current">
        <th>Thời gian</th><th>User</th><th>Level</th><th>Feature</th><th>Phase</th><th>Account/Job</th><th>Nội dung</th>
      </tr></thead><tbody>{events.map((e) => <tr key={e.id} className="border-b border-current/20 align-top">
        <td className="py-2 whitespace-nowrap text-xs">{fmt(e.created_at)}</td>
        <td className="text-xs">{userNames[e.user_id] || shortId(e.user_id)}</td>
        <td><Pill bad={e.level === 'error'}>{e.level}</Pill></td><td>{e.feature}</td><td>{e.phase}</td>
        <td className="font-mono text-[11px]">A:{e.account_id || '—'}<br />J:{shortId(e.job_id)}</td>
        <td className="text-xs max-w-xl break-words">{e.message}<div className="opacity-50 font-mono mt-1">corr: {shortId(e.correlation_id)}</div></td>
      </tr>)}</tbody></table></div>
      <div className="flex justify-center"><button className="nb-btn" disabled={loading || events.length < 200} onClick={loadOlderTimeline}>Tải 200 sự kiện cũ hơn</button></div>
      <div className="text-xs opacity-60">Timeline chỉ hiển thị dữ liệu vận hành đã được redaction. Session, API hash, password, OTP, proxy password và plaintext message không được trả về.</div>
    </div>
  </div>
}
