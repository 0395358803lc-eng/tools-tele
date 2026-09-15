import { useEffect, useState } from 'react'
import { Endpoints } from '../lib/api'

const TABS = [
  ['overview', 'Tổng quan'], ['users', 'Người dùng'], ['jobs', 'Tác vụ'],
  ['audit', 'Audit'], ['system', 'Hệ thống'],
]
const QUOTA_FIELDS = [
  ['max_accounts', 'Telegram account'], ['max_proxies', 'Proxy'],
  ['max_active_jobs', 'Job đồng thời'], ['max_daily_messages', 'Tin nhắn / 24h'],
  ['max_daily_phone_checks', 'Check số / 24h'],
]

function passwordError(value) {
  if ((value || '').length < 12) return 'Mật khẩu phải có ít nhất 12 ký tự'
  if (!/[a-z]/.test(value) || !/[A-Z]/.test(value)) return 'Mật khẩu phải có chữ hoa và chữ thường'
  if (!/\d/.test(value)) return 'Mật khẩu phải có ít nhất một chữ số'
  if (!/[^A-Za-z0-9]/.test(value)) return 'Mật khẩu phải có ít nhất một ký tự đặc biệt'
  return ''
}

function shortId(value) { return value ? `${String(value).slice(0, 8)}…` : '—' }
function fmt(value) { return value ? new Date(value).toLocaleString('vi-VN') : '—' }
function activeJob(status) { return ['queued', 'running', 'cancelling', 'paused'].includes(status) }
export default function AdminPage({ currentUser, onLogout }) {
  const [tab, setTab] = useState('overview')
  const [dashboard, setDashboard] = useState(null)
  const [users, setUsers] = useState([])
  const [jobs, setJobs] = useState([])
  const [audit, setAudit] = useState([])
  const [health, setHealth] = useState(null)
  const [selected, setSelected] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [form, setForm] = useState({ username: '', password: '', role: 'user' })
  const [jobFilter, setJobFilter] = useState({ user_id: '', status: '', job_type: '' })
  const [auditFilter, setAuditFilter] = useState({ user_id: '', action: '' })
  const [auditOffset, setAuditOffset] = useState(0)

  async function refreshDashboard() {
    const data = await Endpoints.adminDashboard()
    setDashboard(data); setUsers(data.users || []); setHealth(data.health || null)
  }

  async function loadJobs() { setJobs(await Endpoints.adminJobs({ limit: 100, ...jobFilter })) }
  async function loadAudit(offset = auditOffset) {
    setAudit(await Endpoints.adminAudit({ limit: 50, offset, ...auditFilter }))
  }
  async function loadHealth() { setHealth(await Endpoints.adminHealth()) }

  async function guarded(fn) {
    setBusy(true); setErr('')
    try { await fn() } catch (e) { setErr(e.message || 'Có lỗi xảy ra') }
    finally { setBusy(false) }
  }
  useEffect(() => { guarded(refreshDashboard) }, [])
  useEffect(() => {
    if (tab === 'jobs') guarded(loadJobs)
    if (tab === 'audit') guarded(() => loadAudit(0))
    if (tab === 'system') guarded(loadHealth)
  }, [tab])

  async function createUser(e) {
    e?.preventDefault?.()
    const issue = passwordError(form.password)
    if (issue) { setErr(issue); return }
    await guarded(async () => {
      await Endpoints.adminCreateUser(form)
      setForm({ username: '', password: '', role: 'user' })
      await refreshDashboard()
    })
  }

  async function updateUser(user, payload) {
    await guarded(async () => {
      await Endpoints.adminUpdateUser(user.id, payload)
      await refreshDashboard()
      if (selected?.user?.id === user.id) setSelected(await Endpoints.adminUserOverview(user.id))
    })
  }

  async function openUser(user) {
    await guarded(async () => { setSelected(await Endpoints.adminUserOverview(user.id)) })
  }

  async function resetPassword(user) {
    const password = window.prompt(`Mật khẩu mới cho ${user.username} (12+ ký tự, hoa/thường/số/ký tự đặc biệt):`)
    if (!password) return
    const issue = passwordError(password)
    if (issue) { setErr(issue); return }
    await updateUser(user, { password })
  }
  async function forceLogout(user) {
    if (!window.confirm(`Thu hồi toàn bộ phiên cũ của ${user.username}?`)) return
    await guarded(async () => { await Endpoints.adminForceLogout(user.id); await refreshDashboard() })
  }

  async function removeUser(user) {
    if (!window.confirm(`Xóa identity ${user.username}? Dữ liệu nghiệp vụ sẽ được giữ lại.`)) return
    await guarded(async () => {
      await Endpoints.adminDeleteUser(user.id)
      if (selected?.user?.id === user.id) setSelected(null)
      await refreshDashboard()
    })
  }

  async function purgeUser(user) {
    const typed = window.prompt(`XÓA VĨNH VIỄN toàn bộ dữ liệu của ${user.username}. Nhập chính xác username để xác nhận:`)
    if (typed !== user.username) { if (typed) setErr('Tên xác nhận không khớp'); return }
    await guarded(async () => {
      await Endpoints.adminPurgeUser(user.id, typed)
      setSelected(null); await refreshDashboard()
    })
  }

  async function saveQuotas() {
    if (!selected?.user) return
    const quotas = {}
    for (const [key] of QUOTA_FIELDS) quotas[key] = Math.max(0, Number(selected.user.quotas?.[key] || 0))
    await updateUser(selected.user, { quotas })
  }

  async function cancelAdminJob(job) {
    if (!window.confirm(`Hủy tác vụ ${job.id}?`)) return
    await guarded(async () => { await Endpoints.adminCancelJob(job.id); await loadJobs(); await refreshDashboard() })
  }

  async function retryAdminJob(job) {
    if (!window.confirm(`Chạy lại các item lỗi của tác vụ ${job.id}?`)) return
    await guarded(async () => {
      await Endpoints.adminRetryJob(job.id, () => {})
      await loadJobs(); await refreshDashboard()
    })
  }

  const summary = dashboard?.summary || {}
  return (
    <div className="min-h-screen bg-zinc-100 dark:bg-zinc-950 p-4">
      <div className="max-w-[1500px] mx-auto space-y-4">
        <header className="nb-card p-4 flex flex-wrap items-center gap-3">
          <div><h1 className="text-2xl font-extrabold uppercase">ADMIN CONTROL</h1>
            <div className="text-xs opacity-60">{currentUser?.username} · production</div></div>
          <div className="flex-1" />
          <button className="nb-btn" onClick={() => guarded(refreshDashboard)}>Làm mới</button>
          <button className="nb-btn" onClick={onLogout}>Đăng xuất</button>
        </header>
        {err && <div className="nb-card p-3 bg-brand-err text-black font-bold">{err}</div>}
        <div className="flex flex-wrap gap-2">
          {TABS.map(([key, label]) => <button key={key}
            className={tab === key ? 'nb-btn-pri' : 'nb-btn'} onClick={() => setTab(key)}>{label}</button>)}
        </div>

        {tab === 'overview' && <>
          <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
            <Stat label="Users" value={summary.total_users} />
            <Stat label="Active users" value={summary.active_users} />
            <Stat label="TG accounts" value={summary.accounts} />
            <Stat label="Connected" value={summary.connected_accounts} />
            <Stat label="Proxies" value={summary.proxies} />
            <Stat label="Jobs" value={summary.jobs} />
            <Stat label="Active jobs" value={summary.active_jobs} />
            <Stat label="Failed jobs" value={summary.failed_jobs} />
          </div>
          <div className="grid lg:grid-cols-2 gap-4">
            <HealthCard health={health} />
            <div className="nb-card p-4">
              <SectionTitle title="Hoạt động dữ liệu" />
              <div className="grid grid-cols-2 gap-3">
                <Stat label="Message items" value={summary.message_items} />
                <Stat label="Phone checks" value={summary.phone_check_items} />
                <Stat label="Disabled users" value={summary.disabled_users} />
                <Stat label="Unprovisioned" value={summary.unprovisioned_users} />
              </div>
            </div>
          </div>
        </>}
        {tab === 'users' && <div className="space-y-4">
          <form className="nb-card p-4 grid md:grid-cols-4 gap-3" onSubmit={createUser}>
            <input className="nb-input" placeholder="Tên đăng nhập" value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })} />
            <input className="nb-input" type="password" minLength={12} placeholder="Mật khẩu mạnh (12+ ký tự)"
              value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            <select className="nb-input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="user">user</option><option value="admin">admin</option>
            </select>
            <button className="nb-btn-pri" disabled={busy}>Tạo user</button>
          </form>
          <div className="grid xl:grid-cols-[1fr_420px] gap-4">
            <div className="nb-card p-4 overflow-auto">
              <table className="w-full text-sm"><thead><tr className="text-left border-b-2 border-current">
                <th>User</th><th>Role</th><th>Trạng thái</th><th>Đăng nhập cuối</th><th>Thao tác</th>
              </tr></thead><tbody>{users.map((u) => <tr key={u.id} className="border-b border-zinc-300 dark:border-zinc-700">
                <td className="py-3"><button className="font-bold underline" onClick={() => openUser(u)}>{u.username}</button>
                  <div className="text-[10px] opacity-50">{shortId(u.id)}</div></td>
                <td><select className="nb-input !py-1" value={u.role} disabled={busy || u.id === currentUser?.id}
                  onChange={(e) => updateUser(u, { role: e.target.value })}>
                  <option value="unprovisioned" disabled>chưa cấp quyền</option><option value="user">user</option><option value="admin">admin</option>
                </select></td>
                <td><Pill ok={!u.disabled && u.role !== 'unprovisioned'}>{u.disabled ? 'Đã khóa' : u.role === 'unprovisioned' ? 'Chưa cấp quyền' : 'Hoạt động'}</Pill></td>
                <td>{fmt(u.last_sign_in_at)}</td>
                <td className="space-x-1 whitespace-nowrap">
                  <button className="nb-btn !py-1" disabled={busy || u.id === currentUser?.id}
                    onClick={() => updateUser(u, { disabled: !u.disabled })}>{u.disabled ? 'Mở khóa' : 'Khóa'}</button>
                  <button className="nb-btn !py-1" disabled={busy} onClick={() => resetPassword(u)}>Mật khẩu</button>
                  <button className="nb-btn !py-1" disabled={busy || u.id === currentUser?.id} onClick={() => forceLogout(u)}>Force logout</button>
                  <button className="nb-btn !py-1" disabled={busy || u.id === currentUser?.id} onClick={() => removeUser(u)}>Xóa</button>
                </td>
              </tr>)}</tbody></table>
            </div>
            <UserDetail selected={selected} busy={busy} setSelected={setSelected} saveQuotas={saveQuotas} purgeUser={purgeUser} />
          </div>
        </div>}

        {tab === 'jobs' && <div className="nb-card p-4 space-y-3">
          <SectionTitle title="Jobs toàn hệ thống" />
          <div className="grid md:grid-cols-4 gap-2">
            <select className="nb-input" value={jobFilter.user_id} onChange={(e) => setJobFilter({ ...jobFilter, user_id: e.target.value })}>
              <option value="">Tất cả user</option>{users.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
            </select>
            <input className="nb-input" placeholder="status" value={jobFilter.status} onChange={(e) => setJobFilter({ ...jobFilter, status: e.target.value })} />
            <input className="nb-input" placeholder="job type" value={jobFilter.job_type} onChange={(e) => setJobFilter({ ...jobFilter, job_type: e.target.value })} />
            <button className="nb-btn-pri" onClick={() => guarded(loadJobs)}>Lọc</button>
          </div>
          <div className="overflow-auto"><table className="w-full text-sm"><thead><tr className="text-left border-b-2 border-current">
            <th>Job</th><th>User</th><th>Type</th><th>Status</th><th>Tiến độ</th><th>Tạo lúc</th><th></th>
          </tr></thead><tbody>{jobs.map((j) => <tr key={j.id} className="border-b border-zinc-300 dark:border-zinc-700">
            <td className="py-2 font-mono text-xs">{shortId(j.id)}</td><td className="font-mono text-xs">{shortId(j.user_id)}</td>
            <td>{j.type}</td><td><Pill ok={j.status === 'completed'}>{j.status}</Pill></td>
            <td>{j.success || 0}/{j.total || 0} · lỗi {j.failed || 0}</td><td>{fmt(j.created_at)}</td>
            <td className="space-x-1">{activeJob(j.status) && <button className="nb-btn !py-1" disabled={busy} onClick={() => cancelAdminJob(j)}>Hủy</button>}
              {!activeJob(j.status) && j.retry_supported && <button className="nb-btn !py-1" disabled={busy} onClick={() => retryAdminJob(j)}>Retry</button>}</td>
          </tr>)}</tbody></table></div>
        </div>}

        {tab === 'audit' && <div className="nb-card p-4 space-y-3">
          <SectionTitle title="Audit toàn hệ thống" />
          <div className="grid md:grid-cols-4 gap-2">
            <select className="nb-input" value={auditFilter.user_id} onChange={(e) => setAuditFilter({ ...auditFilter, user_id: e.target.value })}>
              <option value="">Tất cả user</option>{users.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
            </select>
            <input className="nb-input" placeholder="action" value={auditFilter.action} onChange={(e) => setAuditFilter({ ...auditFilter, action: e.target.value })} />
            <button className="nb-btn-pri" onClick={() => guarded(async () => { setAuditOffset(0); await loadAudit(0) })}>Lọc</button>
            <div className="flex gap-1"><button className="nb-btn" disabled={auditOffset === 0} onClick={() => guarded(async () => { const n=Math.max(0,auditOffset-50); setAuditOffset(n); await loadAudit(n) })}>←</button>
              <button className="nb-btn" disabled={audit.length < 50} onClick={() => guarded(async () => { const n=auditOffset+50; setAuditOffset(n); await loadAudit(n) })}>→</button></div>
          </div>
          <div className="overflow-auto"><table className="w-full text-sm"><thead><tr className="text-left border-b-2 border-current">
            <th>Thời gian</th><th>Action</th><th>User</th><th>Account</th><th>Chi tiết</th>
          </tr></thead><tbody>{audit.map((row) => <tr key={row.id} className="border-b border-zinc-300 dark:border-zinc-700 align-top">
            <td className="py-2 whitespace-nowrap">{fmt(row.created_at)}</td><td className="font-bold">{row.action}</td>
            <td className="font-mono text-xs">{shortId(row.user_id)}</td><td>{row.account_id || '—'}</td>
            <td className="font-mono text-[11px] max-w-xl break-all">{JSON.stringify(row.detail || {})}</td>
          </tr>)}</tbody></table></div>
        </div>}

        {tab === 'system' && <div className="space-y-4">
          <HealthCard health={health} detailed />
          <div className="flex justify-end"><button className="nb-btn-pri" onClick={() => guarded(loadHealth)}>Kiểm tra lại</button></div>
        </div>}
      </div>
    </div>
  )
}

function SectionTitle({ title }) {
  return <h2 className="text-sm font-extrabold uppercase tracking-wide mb-3">{title}</h2>
}

function Stat({ label, value }) {
  return <div className="nb-card p-3"><div className="text-[10px] font-bold uppercase opacity-60">{label}</div>
    <div className="text-2xl font-extrabold">{value ?? '—'}</div></div>
}

function Pill({ ok, children }) {
  return <span className={`inline-block px-2 py-1 text-xs font-bold border border-current ${ok ? 'opacity-90' : 'bg-brand-err text-black'}`}>{children}</span>
}
function UserDetail({ selected, busy, setSelected, saveQuotas, purgeUser }) {
  if (!selected?.user) return <div className="nb-card p-4 text-sm opacity-60">Chọn một user để xem usage và quota.</div>
  const user = selected.user
  const usage = selected.usage || {}
  function setQuota(key, value) {
    setSelected({ ...selected, user: { ...user, quotas: { ...(user.quotas || {}), [key]: value } } })
  }
  return <div className="nb-card p-4 space-y-4">
    <div><div className="text-xl font-extrabold">{user.username}</div>
      <div className="text-xs opacity-60 break-all">{user.id}</div></div>
    <div className="grid grid-cols-2 gap-2">
      <Stat label="Accounts" value={usage.accounts} /><Stat label="Connected" value={usage.connected_accounts} />
      <Stat label="Proxy" value={usage.proxies} /><Stat label="Active jobs" value={usage.active_jobs} />
      <Stat label="Messages" value={usage.message_items} /><Stat label="Phone checks" value={usage.phone_check_items} />
    </div>
    <div><SectionTitle title="Quota" />
      <div className="space-y-2">{QUOTA_FIELDS.map(([key, label]) => <label key={key} className="grid grid-cols-[1fr_130px] gap-2 items-center text-sm">
        <span>{label}</span><input type="number" min="0" className="nb-input !py-1" value={user.quotas?.[key] ?? 0}
          onChange={(e) => setQuota(key, e.target.value)} />
      </label>)}</div>
    </div>
    <button className="nb-btn-pri w-full" disabled={busy} onClick={saveQuotas}>Lưu quota</button>
    <button className="nb-btn w-full bg-brand-err text-black" disabled={busy} onClick={() => purgeUser(user)}>Xóa vĩnh viễn tenant</button>
    <div className="text-xs opacity-60">Tạo: {fmt(user.created_at)} · Đăng nhập cuối: {fmt(user.last_sign_in_at)}</div>
  </div>
}
function HealthCard({ health, detailed = false }) {
  const ready = health?.readiness || {}
  const runtime = health?.runtime || {}
  const tunnel = health?.tunnel || {}
  const alerts = health?.alerts || []
  return <div className="nb-card p-4 space-y-3">
    <div className="flex items-center gap-2"><SectionTitle title="System Health" />
      <div className="flex-1" /><Pill ok={ready.ok && tunnel.ok}>{ready.ok && tunnel.ok ? 'HEALTHY' : 'ATTENTION'}</Pill></div>
    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
      <Stat label="Database" value={ready.database || '—'} />
      <Stat label="Tunnel" value={tunnel.ok ? 'online' : 'offline'} />
      <Stat label="CPU" value={runtime.system_cpu_percent != null ? `${runtime.system_cpu_percent}%` : '—'} />
      <Stat label="RAM" value={runtime.system_memory_percent != null ? `${runtime.system_memory_percent}%` : '—'} />
      <Stat label="Loop lag" value={runtime.event_loop_lag_ms != null ? `${runtime.event_loop_lag_ms} ms` : '—'} />
      <Stat label="Stale jobs" value={runtime.stale_jobs} />
      <Stat label="Requests" value={runtime.requests_total} />
      <Stat label="HTTP 5xx" value={runtime.requests_5xx} />
      <Stat label="P95 latency" value={runtime.request_duration_p95_ms != null ? `${runtime.request_duration_p95_ms} ms` : '—'} />
      <Stat label="Uptime" value={runtime.uptime_seconds != null ? `${Math.floor(runtime.uptime_seconds / 60)}m` : '—'} />
      <Stat label="Backup age" value={health?.latest_backup?.age_hours != null ? `${health.latest_backup.age_hours}h` : '—'} />
    </div>
    {alerts.length > 0 && <div className="space-y-1">{alerts.map((a, i) => <div key={`${a.code}-${i}`} className="p-2 border border-current text-sm font-bold">{a.level.toUpperCase()}: {a.message}</div>)}</div>}
    {detailed && (health?.recent_alerts || []).length > 0 && <div className="space-y-1">
      <div className="text-[10px] uppercase font-extrabold opacity-60">Lịch sử cảnh báo gần đây</div>
      {(health.recent_alerts || []).slice(0, 10).map((a, i) => <div key={`${a.ts}-${a.code}-${i}`} className="text-xs border-b border-current/20 py-1 flex gap-2">
        <span className="font-mono opacity-60">{a.ts ? fmt(a.ts) : '—'}</span><b>{a.source}:{a.code}</b><span>{a.status}</span><span className="opacity-70 truncate">{a.message}</span>
      </div>)}
    </div>}
    {detailed && <div className="text-xs opacity-70 space-y-1">
      <div>PID: {runtime.pid ?? '—'} · DB revision: {runtime.db_revision || '—'}</div>
      <div>Version: {ready.release?.version || runtime.release?.version || '—'} · SHA: {ready.release?.git_sha || runtime.release?.git_sha || '—'}</div>
      <div>Process RAM: {runtime.process_memory_bytes ? `${Math.round(runtime.process_memory_bytes / 1048576)} MB` : '—'}</div>
      <div>Backup: {health?.latest_backup?.name || '—'}</div>
      <div>Maintenance: {health?.maintenance?.ok === true ? 'OK' : health?.maintenance?.ok === false ? 'Lỗi' : 'Chưa chạy'} · {health?.maintenance?.at ? fmt(health.maintenance.at) : '—'}</div>
      <div>Public HTTP: {tunnel.status_code || '—'}</div>
    </div>}
  </div>
}
