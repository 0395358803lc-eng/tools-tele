import { useState } from 'react'
import { Endpoints } from '../lib/api'
import { signInIdentity, signOutIdentity } from '../lib/supabase'

export default function LoginScreen({ onAuthed }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function submit(e) {
    e?.preventDefault?.()
    if (!username || !password) return
    setBusy(true); setErr('')
    try {
      await signInIdentity(username, password, 'user')
      const r = await Endpoints.me()
      if (!r?.authed) throw new Error('Đăng nhập thất bại')
      onAuthed?.(r.user)
    } catch (e) {
      try { await signOutIdentity('user') } catch {}
      setErr(e.message || 'Đăng nhập thất bại')
      setPassword('')
    } finally { setBusy(false) }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-zinc-100 dark:bg-zinc-950">
      <form className="nb-card p-6 w-full max-w-sm" onSubmit={submit}>
        <div className="mb-1 text-xs font-extrabold uppercase tracking-tight text-brand-pri inline-block bg-black px-2 py-0.5">USER PORTAL</div>
        <h1 className="font-extrabold uppercase tracking-tighter text-2xl mb-1">Quản Lý Telegram Đa Tài Khoản</h1>
        <p className="text-sm opacity-70 mb-4">Đăng nhập bằng tài khoản người dùng được quản trị viên cấp.</p>
        <label className="block mb-3"><div className="text-xs font-bold uppercase mb-1">Tên đăng nhập</div>
          <input className="nb-input" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" />
        </label>
        <label className="block mb-3"><div className="text-xs font-bold uppercase mb-1">Mật khẩu</div>
          <input type="password" className="nb-input" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
        {err && <div className="mt-3 nb-card-sm bg-brand-err text-black px-3 py-2 text-sm font-bold">{err}</div>}
        <button className="nb-btn-pri w-full mt-4" disabled={busy || !username || !password} type="submit">
          {busy ? 'Đang đăng nhập…' : 'Đăng nhập'}
        </button>
      </form>
    </div>
  )
}
