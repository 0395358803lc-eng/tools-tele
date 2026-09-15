import { useEffect, useState } from 'react'
import { Endpoints } from '../lib/api'
import { signInIdentity, signOutIdentity } from '../lib/supabase'

function passwordError(value) {
  if ((value || '').length < 12) return 'Mật khẩu phải có ít nhất 12 ký tự'
  if (!/[a-z]/.test(value) || !/[A-Z]/.test(value)) return 'Mật khẩu phải có chữ hoa và chữ thường'
  if (!/\d/.test(value)) return 'Mật khẩu phải có ít nhất một chữ số'
  if (!/[^A-Za-z0-9]/.test(value)) return 'Mật khẩu phải có ít nhất một ký tự đặc biệt'
  return ''
}

export default function AdminLoginScreen({ onAuthed }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [mode, setMode] = useState('checking')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    Endpoints.bootstrapStatus().then((r) => {
      if (!r?.configured) setErr('Supabase Identity chưa được cấu hình trên máy chủ.')
      setMode(r?.needs_admin ? 'bootstrap' : 'login')
    }).catch((e) => { setErr(e.message); setMode('login') })
  }, [])

  async function submit(e) {
    e?.preventDefault?.()
    if (!username || !password) return
    setBusy(true); setErr('')
    try {
      if (mode === 'bootstrap') {
        const issue = passwordError(password)
        if (issue) throw new Error(issue)
        if (password !== confirm) throw new Error('Mật khẩu xác nhận không khớp')
        await Endpoints.bootstrapAdmin(username, password)
      }
      await signInIdentity(username, password, 'admin')
      const r = await Endpoints.me()
      if (!r?.authed || r?.user?.role !== 'admin') {
        await signOutIdentity('admin')
        throw new Error('Tài khoản không có quyền ADMIN')
      }
      onAuthed?.(r.user)
    } catch (e) {
      try { await signOutIdentity('admin') } catch {}
      setErr(e.message || 'Đăng nhập ADMIN thất bại')
      setPassword(''); setConfirm('')
    } finally { setBusy(false) }
  }

  if (mode === 'checking') return <div className="min-h-screen flex items-center justify-center">Đang kiểm tra cổng ADMIN…</div>
  const bootstrap = mode === 'bootstrap'
  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-zinc-100 dark:bg-zinc-950">
      <form className="nb-card p-6 w-full max-w-sm" onSubmit={submit}>
        <div className="mb-1 text-xs font-extrabold uppercase tracking-tight text-brand-pri inline-block bg-black px-2 py-0.5">ADMIN PORTAL</div>
        <h1 className="font-extrabold uppercase tracking-tighter text-2xl mb-1">Đăng nhập quản trị</h1>
        <p className="text-sm opacity-70 mb-4">{bootstrap ? 'Tạo tài khoản ADMIN đầu tiên.' : 'Cổng quản trị độc lập của hệ thống.'}</p>
        <label className="block mb-3"><div className="text-xs font-bold uppercase mb-1">Tên ADMIN</div>
          <input className="nb-input" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" />
        </label>
        <label className="block mb-3"><div className="text-xs font-bold uppercase mb-1">Mật khẩu</div>
          <input type="password" className="nb-input" minLength={bootstrap ? 12 : undefined} value={password}
            onChange={(e) => setPassword(e.target.value)} autoComplete={bootstrap ? 'new-password' : 'current-password'} />
        </label>
        {bootstrap && <label className="block mb-3"><div className="text-xs font-bold uppercase mb-1">Xác nhận mật khẩu</div>
          <input type="password" className="nb-input" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoComplete="new-password" />
        </label>}
        {err && <div className="mt-3 nb-card-sm bg-brand-err text-black px-3 py-2 text-sm font-bold">{err}</div>}
        <button className="nb-btn-pri w-full mt-4" disabled={busy || !username || !password || (bootstrap && !confirm)} type="submit">
          {busy ? 'Đang xử lý…' : bootstrap ? 'Tạo ADMIN và đăng nhập' : 'Đăng nhập ADMIN'}
        </button>
        <p className="text-[10px] opacity-50 mt-4">Phiên ADMIN được lưu riêng và không dùng chung phiên đăng nhập của USER PORTAL.</p>
      </form>
    </div>
  )
}
