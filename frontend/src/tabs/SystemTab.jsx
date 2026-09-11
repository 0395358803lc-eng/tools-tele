import { useCallback, useEffect, useState } from 'react'
import { Endpoints } from '../lib/api'
import { useToast } from '../lib/toast.jsx'
import { accountStatusVi, healthCheckVi } from '../lib/vi'

function Badge({ ok, children }) {
  return <span className={'nb-badge text-black ' + (ok ? 'bg-brand-ok' : 'bg-brand-warn')}>{children}</span>
}

export default function SystemTab() {
  const toast = useToast()
  const [status, setStatus] = useState(null)
  const [health, setHealth] = useState(null)

  const load = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([Endpoints.systemStatus(), Endpoints.health()])
      setStatus(s); setHealth(h)
    } catch (e) { toast.error(e.message) }
  }, [toast])

  useEffect(() => {
    load()
    const timer = setInterval(load, 10000)
    return () => clearInterval(timer)
  }, [load])

  if (!status || !health) return <div className="nb-card p-4 text-sm">Đang tải trạng thái hệ thống…</div>

  const accountEntries = Object.entries(status.accounts || {})
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <h2 className="font-extrabold uppercase">Trạng thái hệ thống</h2>
        <Badge ok={health.ok}>{health.ok ? 'Sẵn sàng' : 'Chưa sẵn sàng'}</Badge>
        <button className="nb-btn !py-1 !px-2 text-xs ml-auto" onClick={load}>Làm mới</button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3">
        <div className="nb-card p-4"><div className="text-[10px] uppercase font-bold opacity-60">Cơ sở dữ liệu</div><div className="text-lg font-extrabold">{status.database_kind === 'postgresql' ? 'PostgreSQL' : status.database_kind === 'sqlite' ? 'SQLite' : status.database_kind}</div><div className="text-xs mt-1"><Badge ok={status.persistent_database}>{status.persistent_database ? 'Lưu bền vững' : 'Chỉ cục bộ'}</Badge></div></div>
        <div className="nb-card p-4"><div className="text-[10px] uppercase font-bold opacity-60">Lược đồ</div><div className="font-mono text-xs mt-1 break-all">{status.db_revision || 'không rõ'}</div><div className="text-[10px] opacity-60 mt-1">bản chuẩn {status.expected_revision || 'không rõ'}</div></div>
        <div className="nb-card p-4"><div className="text-[10px] uppercase font-bold opacity-60">Tác vụ</div><div className="text-lg font-extrabold">{status.active_jobs} đang chạy</div><div className="text-xs">{status.stale_jobs} quá hạn · {status.failed_jobs_24h || 0} lỗi/24 giờ</div></div>
        <div className="nb-card p-4"><div className="text-[10px] uppercase font-bold opacity-60">Thời gian chạy</div><div className="text-lg font-extrabold">{Math.floor((status.uptime_seconds || 0) / 60)} phút</div><div className="text-xs font-mono">PID {status.pid}</div></div>
      </div>

      <div className="nb-card p-4">
        <div className="font-extrabold uppercase mb-3">Mức sẵn sàng</div>
        <div className="flex gap-2 flex-wrap text-xs">
          <Badge ok={health.database === 'ok'}>CSDL {health.database === 'ok' ? 'tốt' : 'lỗi'}</Badge>
          <Badge ok={health.schema === 'ok'}>Lược đồ {health.schema === 'ok' ? 'đúng phiên bản' : 'chưa cập nhật'}</Badge>
          <Badge ok={health.telegram_configured}>Telegram {health.telegram_configured ? 'đã cấu hình' : 'chưa cấu hình'}</Badge>
          <Badge ok={health.encrypted_session_store}>Phiên mã hóa {health.encrypted_session_store ? 'đã bật' : 'thiếu khóa'}</Badge>
          <Badge ok={health.app_auth_configured}>Đăng nhập ứng dụng {health.app_auth_configured ? 'đã cấu hình' : 'thiếu/yếu'}</Badge>
          <Badge ok={health.persistent_storage}>Lưu trữ {health.persistent_storage ? 'đạt yêu cầu' : 'không bền vững'}</Badge>
        </div>
        {health.failed_checks?.length > 0 && <div className="text-xs mt-3 text-brand-err font-bold">Chưa đạt: {health.failed_checks.map(healthCheckVi).join(', ')}</div>}
      </div>

      <div className="nb-card p-4">
        <div className="font-extrabold uppercase mb-3">Tài khoản</div>
        <div className="flex gap-2 flex-wrap">
          <span className="nb-badge bg-white dark:bg-zinc-800">Tổng {status.account_total}</span>
          {accountEntries.length ? accountEntries.map(([name, count]) => <span key={name} className="nb-badge bg-brand-violet text-black">{accountStatusVi(name)}: {count}</span>) : <span className="text-sm opacity-60">Không có tài khoản</span>}
        </div>
      </div>
    </div>
  )
}
