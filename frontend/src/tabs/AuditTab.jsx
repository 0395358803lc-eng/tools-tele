import { useCallback, useEffect, useState } from 'react'
import { Endpoints } from '../lib/api'
import { fmtTime } from '../lib/util'
import { auditActionVi, auditKeyVi } from '../lib/vi'
import { useToast } from '../lib/toast.jsx'

function detailText(detail) {
  try {
    const entries = Object.entries(detail || {})
    if (!entries.length) return '—'
    return entries.map(([k, v]) => `${auditKeyVi(k)}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ')
  } catch { return '—' }
}

export default function AuditTab() {
  const toast = useToast()
  const [rows, setRows] = useState([])
  const [action, setAction] = useState('')
  const [accountId, setAccountId] = useState('')

  const load = useCallback(async () => {
    try {
      const data = await Endpoints.audit(200, action.trim() || undefined, accountId ? Number(accountId) : undefined)
      setRows(data || [])
    } catch (e) { toast.error(e.message) }
  }, [action, accountId, toast])

  useEffect(() => { load() }, [load])

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <h2 className="font-extrabold uppercase">Nhật ký hoạt động</h2>
        <span className="text-xs opacity-60">Các trường nhạy cảm được che ở phía máy chủ</span>
        <div className="ml-auto flex gap-2">
          <input className="nb-input !w-44 !py-1 text-xs" placeholder="Lọc hành động" value={action} onChange={(e) => setAction(e.target.value)} />
          <input className="nb-input !w-28 !py-1 text-xs" placeholder="ID tài khoản" inputMode="numeric" value={accountId} onChange={(e) => setAccountId(e.target.value.replace(/\D/g, ''))} />
          <button className="nb-btn !py-1 !px-2 text-xs" onClick={load}>Làm mới</button>
        </div>
      </div>

      <div className="nb-card p-4 overflow-auto">
        {rows.length === 0 ? (
          <div className="text-sm opacity-60">Không có mục nhật ký phù hợp bộ lọc.</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-[10px] uppercase font-extrabold border-b-2 border-black dark:border-white">
              <tr><th className="text-left p-2">Thời gian</th><th className="text-left p-2">Hành động</th><th className="text-left p-2">Tài khoản</th><th className="text-left p-2">Chi tiết</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-zinc-300 dark:border-zinc-700 align-top">
                  <td className="p-2 text-xs whitespace-nowrap">{fmtTime(r.created_at)}</td>
                  <td className="p-2"><span className="nb-badge bg-brand-violet text-black">{auditActionVi(r.action)}</span></td>
                  <td className="p-2 font-mono text-xs">{r.account_id ?? '—'}</td>
                  <td className="p-2 text-xs font-mono break-all opacity-80">{detailText(r.detail)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
