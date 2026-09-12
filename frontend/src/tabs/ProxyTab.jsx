import { useEffect, useMemo, useState } from 'react'
import { Endpoints } from '../lib/api'
import { useToast } from '../lib/toast.jsx'
import { accountStatusVi } from '../lib/vi'

const EMPTY = {
  enabled: true,
  proxy_type: 'socks5',
  host: '',
  port: 1080,
  username: '',
  password: '',
  clear_password: false,
  rdns: true,
}

function statusLabel(status) {
  const map = {
    unknown: 'Chưa kiểm tra', pending: 'Chờ áp dụng', disabled: 'Đang tắt',
    test_ok: 'Kiểm tra đạt', test_failed: 'Kiểm tra lỗi',
    connected: 'Đang kết nối qua proxy', connect_failed: 'Kết nối thất bại',
  }
  return map[status] || status || 'Chưa kiểm tra'
}

function fillForm(proxy) {
  if (!proxy) return { ...EMPTY }
  return {
    enabled: proxy.enabled !== false,
    proxy_type: proxy.proxy_type || 'socks5',
    host: proxy.host || '',
    port: proxy.port || 1080,
    username: proxy.username || '',
    password: '',
    clear_password: false,
    rdns: proxy.rdns !== false,
  }
}

function parseProxyLine(raw) {
  const value = (raw || '').trim()
  if (!value) throw new Error('Hãy nhập proxy')
  if (value.includes('://')) {
    const u = new URL(value)
    const type = u.protocol.replace(':', '').toLowerCase()
    if (!['socks5', 'socks4', 'http'].includes(type)) throw new Error('Chỉ hỗ trợ SOCKS5, SOCKS4 hoặc HTTP')
    if (!u.hostname || !u.port) throw new Error('Proxy URL phải có host và port')
    return {
      proxy_type: type,
      host: u.hostname,
      port: Number(u.port),
      username: decodeURIComponent(u.username || ''),
      password: decodeURIComponent(u.password || ''),
    }
  }
  const parts = value.split(':')
  if (parts.length < 2) throw new Error('Định dạng nhanh: host:port:user:pass')
  const port = Number(parts[1])
  if (!parts[0] || !Number.isInteger(port)) throw new Error('Host hoặc port không hợp lệ')
  return {
    host: parts[0], port,
    username: parts[2] || '',
    password: parts.length > 3 ? parts.slice(3).join(':') : '',
  }
}

export default function ProxyTab() {
  const toast = useToast()
  const [rows, setRows] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [form, setForm] = useState({ ...EMPTY })
  const [quick, setQuick] = useState('')
  const [busy, setBusy] = useState('')

  async function refresh(preferredId) {
    try {
      const data = await Endpoints.proxies()
      setRows(data || [])
      const id = preferredId ?? selectedId ?? data?.[0]?.account?.id ?? null
      setSelectedId(id)
      const row = (data || []).find((x) => x.account.id === id)
      if (row) setForm(fillForm(row.proxy))
    } catch (e) { toast.error(e.message) }
  }

  useEffect(() => { refresh() }, [])

  const selected = useMemo(() => rows.find((x) => x.account.id === selectedId) || null, [rows, selectedId])

  function choose(row) {
    setSelectedId(row.account.id)
    setForm(fillForm(row.proxy))
    setQuick('')
  }

  function applyQuick() {
    try {
      const parsed = parseProxyLine(quick)
      setForm((f) => ({ ...f, ...parsed }))
      toast.success('Đã đọc proxy vào biểu mẫu')
    } catch (e) { toast.error(e.message) }
  }

  async function save() {
    if (!selectedId) return null
    if (!form.host.trim()) { toast.error('Host proxy đang trống'); return null }
    setBusy('save')
    try {
      const payload = { ...form, host: form.host.trim(), username: form.username.trim() || null }
      if (!payload.password) payload.password = null
      const saved = await Endpoints.saveProxy(selectedId, payload)
      setForm(fillForm(saved))
      await refresh(selectedId)
      toast.success('Đã lưu proxy cho session')
      return saved
    } catch (e) { toast.error(e.message); return null } finally { setBusy('') }
  }

  async function testProxy() {
    if (!selectedId) return
    setBusy('test')
    try {
      await Endpoints.testProxy(selectedId)
      toast.success('Proxy kết nối được tới Telegram')
      await refresh(selectedId)
    } catch (e) { toast.error(e.message); await refresh(selectedId) } finally { setBusy('') }
  }

  async function applyProxy() {
    if (!selectedId) return
    setBusy('apply')
    try {
      await Endpoints.applyProxy(selectedId)
      toast.success('Đã reconnect session với cấu hình proxy hiện tại')
      await refresh(selectedId)
    } catch (e) { toast.error(e.message); await refresh(selectedId) } finally { setBusy('') }
  }

  async function saveAndApply() {
    const saved = await save()
    if (!saved) return
    setBusy('apply')
    try {
      await Endpoints.applyProxy(selectedId)
      toast.success(saved.enabled ? 'Đã lưu và chuyển session sang proxy' : 'Đã lưu và chuyển session về kết nối trực tiếp')
      await refresh(selectedId)
    } catch (e) { toast.error(e.message); await refresh(selectedId) } finally { setBusy('') }
  }

  async function removeProxy() {
    if (!selectedId) return
    if (!confirm('Xóa cấu hình proxy của session này? Session sẽ dùng kết nối trực tiếp sau khi áp dụng/reconnect.')) return
    setBusy('delete')
    try {
      await Endpoints.deleteProxy(selectedId)
      await Endpoints.applyProxy(selectedId)
      toast.success('Đã xóa proxy và reconnect trực tiếp')
      await refresh(selectedId)
    } catch (e) { toast.error(e.message); await refresh(selectedId) } finally { setBusy('') }
  }

  return (
    <div className="grid lg:grid-cols-[320px_1fr] gap-4 min-h-[70vh]">
      <div className="nb-card overflow-hidden">
        <div className="p-3 border-b-2 border-black dark:border-white">
          <div className="font-extrabold uppercase">Proxy theo session</div>
          <div className="text-xs opacity-60 mt-1">{rows.length} tài khoản</div>
        </div>
        <div className="max-h-[70vh] overflow-auto">
          {rows.map((row) => {
            const p = row.proxy
            return (
              <button key={row.account.id} onClick={() => choose(row)}
                className={'w-full text-left p-3 border-b border-black/20 dark:border-white/20 ' + (selectedId === row.account.id ? 'bg-brand-pri text-black' : 'hover:bg-zinc-100 dark:hover:bg-zinc-800')}>
                <div className="font-bold truncate">{row.account.name}</div>
                <div className="text-xs truncate">{row.account.phone} {row.account.username ? `· @${row.account.username}` : ''}</div>
                <div className="text-[11px] mt-1 opacity-70">
                  {p ? `${p.enabled ? p.proxy_type.toUpperCase() : 'TẮT'} · ${p.host}:${p.port}` : 'Chưa gắn proxy'}
                </div>
                {p && <div className="text-[10px] mt-1">{statusLabel(p.last_status)}</div>}
              </button>
            )
          })}
        </div>
      </div>

      <div className="space-y-4">
        {!selected && <div className="nb-card p-5 opacity-60">Chưa có session để cấu hình proxy.</div>}
        {selected && <>
          <div className="nb-card p-5">
            <div className="flex flex-wrap gap-2 items-start mb-4">
              <div>
                <h3 className="font-extrabold uppercase text-lg">{selected.account.name}</h3>
                <div className="text-sm">{selected.account.phone} · {accountStatusVi(selected.account.status)}</div>
              </div>
              <div className="ml-auto text-right text-xs">
                <div className="font-bold">{statusLabel(selected.proxy?.last_status)}</div>
                {selected.proxy?.has_password && <div className="opacity-60">🔒 Có mật khẩu proxy đã mã hóa</div>}
              </div>
            </div>

            {selected.proxy?.last_error && (
              <div className="mb-4 p-2 border-2 border-black dark:border-white bg-red-100 dark:bg-red-950 text-xs break-words">
                <b>Lỗi gần nhất:</b> {selected.proxy.last_error}
              </div>
            )}

            <div className="mb-4">
              <div className="text-xs font-bold uppercase mb-1">Dán nhanh proxy</div>
              <div className="flex gap-2">
                <input className="nb-input" value={quick} onChange={(e) => setQuick(e.target.value)}
                  placeholder="socks5://user:pass@host:port hoặc host:port:user:pass" />
                <button className="nb-btn shrink-0" onClick={applyQuick}>Đọc</button>
              </div>
            </div>

            <div className="grid sm:grid-cols-3 gap-3">
              <label><div className="text-xs font-bold uppercase mb-1">Loại proxy</div>
                <select className="nb-input" value={form.proxy_type} onChange={(e) => setForm({ ...form, proxy_type: e.target.value })}>
                  <option value="socks5">SOCKS5</option><option value="socks4">SOCKS4</option><option value="http">HTTP CONNECT</option>
                </select>
              </label>
              <label className="sm:col-span-1"><div className="text-xs font-bold uppercase mb-1">Host / IP</div>
                <input className="nb-input" value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} placeholder="127.0.0.1" />
              </label>
              <label><div className="text-xs font-bold uppercase mb-1">Port</div>
                <input type="number" min="1" max="65535" className="nb-input" value={form.port}
                  onChange={(e) => setForm({ ...form, port: Number(e.target.value) || 0 })} />
              </label>
              <label><div className="text-xs font-bold uppercase mb-1">Username</div>
                <input className="nb-input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} autoComplete="off" />
              </label>
              <label className="sm:col-span-2"><div className="text-xs font-bold uppercase mb-1">Mật khẩu {selected.proxy?.has_password ? '(để trống = giữ mật khẩu cũ)' : ''}</div>
                <input type="password" className="nb-input" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value, clear_password: false })} autoComplete="new-password" />
              </label>
            </div>

            <div className="flex flex-wrap gap-4 mt-4 text-sm">
              <label className="flex gap-2 items-center"><input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} /> Bật proxy cho session này</label>
              <label className="flex gap-2 items-center"><input type="checkbox" checked={form.rdns} onChange={(e) => setForm({ ...form, rdns: e.target.checked })} /> DNS qua proxy (khuyến nghị)</label>
              {selected.proxy?.has_password && <label className="flex gap-2 items-center"><input type="checkbox" checked={form.clear_password} onChange={(e) => setForm({ ...form, clear_password: e.target.checked, password: '' })} /> Xóa mật khẩu đã lưu</label>}
            </div>

            <div className="flex flex-wrap gap-2 mt-5">
              <button className="nb-btn" disabled={!!busy} onClick={save}>{busy === 'save' ? 'Đang lưu…' : 'Lưu cấu hình'}</button>
              <button className="nb-btn" disabled={!!busy || !selected.proxy} onClick={testProxy}>{busy === 'test' ? 'Đang kiểm tra…' : 'Kiểm tra proxy'}</button>
              <button className="nb-btn-pri" disabled={!!busy} onClick={saveAndApply}>{busy === 'apply' ? 'Đang reconnect…' : 'Lưu & áp dụng'}</button>
              {selected.proxy && <button className="nb-btn" disabled={!!busy} onClick={removeProxy}>Xóa proxy</button>}
            </div>
          </div>

          <div className="nb-card p-4 text-xs opacity-75 space-y-1">
            <div><b>Cách hoạt động:</b> proxy chỉ gắn với session đang chọn, không ảnh hưởng session khác.</div>
            <div>Khi bật proxy, lần kết nối/reconnect tiếp theo của Telethon bắt buộc đi qua proxy. Nếu proxy lỗi, hệ thống không tự chuyển sang IP máy chủ.</div>
            <div>SOCKS5 được khuyến nghị. HTTP phải hỗ trợ phương thức CONNECT; HTTP proxy chỉ hỗ trợ web thông thường có thể không dùng được với Telegram.</div>
          </div>
        </>}
      </div>
    </div>
  )
}
