import { useEffect, useState } from 'react'
import { Endpoints } from '../lib/api'
import { useToast } from '../lib/toast.jsx'

export default function SettingsTab() {
  const toast = useToast()
  const [s, setS] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    Endpoints.getSettings().then(setS).catch((e) => toast.error(e.message))
  }, [])

  if (!s) return <div className="opacity-60">Đang tải cài đặt…</div>

  async function save() {
    setBusy(true)
    try {
      const r = await Endpoints.putSettings(s)
      setS(r)
      window.dispatchEvent(new CustomEvent('mtm-settings-updated', { detail: r }))
      toast.success('Đã lưu cài đặt')
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }

  async function exportJson() {
    try {
      const data = await Endpoints.exportJson()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `accounts-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) { toast.error(e.message) }
  }

  return (
    <div className="max-w-2xl space-y-4">
      <div className="nb-card p-5">
        <h3 className="font-extrabold uppercase mb-4">Khoảng giới hạn tốc độ</h3>
        <p className="text-xs opacity-70 mb-3">
          Khoảng nghỉ tối thiểu/tối đa giữa lúc bắt đầu các thao tác tài khoản trong tác vụ hàng loạt. Mức song song quy định
          bao nhiêu thao tác tài khoản có thể chạy cùng lúc, còn khoảng thời gian này ngăn toàn bộ tài khoản
          khởi chạy đồng thời. Giá trị mặc định lấy từ cấu hình runtime của backend.
        </p>
        <div className="grid grid-cols-2 gap-3">
          <label>
            <div className="text-xs font-bold uppercase mb-1">Số giây tối thiểu giữa các thao tác</div>
            <input type="number" step="0.1" className="nb-input" value={s.rate_min}
              onChange={(e) => setS({ ...s, rate_min: Number(e.target.value) || 0 })} />
          </label>
          <label>
            <div className="text-xs font-bold uppercase mb-1">Số giây tối đa</div>
            <input type="number" step="0.1" className="nb-input" value={s.rate_max}
              onChange={(e) => setS({ ...s, rate_max: Number(e.target.value) || 0 })} />
          </label>
        </div>
        <label className="block mt-3">
          <div className="text-xs font-bold uppercase mb-1">Số tài khoản chạy song song (kích thước lô)</div>
          <input type="number" step="1" min="1" max="50" className="nb-input"
            value={s.concurrency ?? 5}
            onChange={(e) => setS({ ...s, concurrency: Math.max(1, parseInt(e.target.value) || 1) })} />
          <p className="text-xs opacity-70 mt-1">
            Số thao tác tài khoản tối đa được phép chạy đồng thời. Nên đặt ở mức thận trọng;
            Telegram vẫn có thể áp dụng giới hạn cho từng tài khoản hoặc toàn dịch vụ.
          </p>
        </label>
      </div>

      <div className="nb-card p-5">
        <h3 className="font-extrabold uppercase mb-4">Tệp phiên</h3>
        <label className="block">
          <div className="text-xs font-bold uppercase mb-1">Đường dẫn thư mục phiên</div>
          <input className="nb-input" value={s.sessions_dir}
            onChange={(e) => setS({ ...s, sessions_dir: e.target.value })} />
          <p className="text-xs opacity-70 mt-1">Thay đổi có hiệu lực sau lần khởi động backend tiếp theo.</p>
        </label>
      </div>

      <div className="nb-card p-5">
        <h3 className="font-extrabold uppercase mb-4">Hành vi</h3>
        <label className="flex items-center gap-2 mb-2">
          <input type="checkbox" checked={s.auto_reconnect}
            onChange={(e) => setS({ ...s, auto_reconnect: e.target.checked })} />
          <span>Tự động kết nối lại khi mất kết nối</span>
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={s.notification_sound}
            onChange={(e) => setS({ ...s, notification_sound: e.target.checked })} />
          <span>Phát âm báo khi có cảnh báo mới</span>
        </label>
      </div>

      <div className="flex gap-2">
        <button className="nb-btn-pri" disabled={busy} onClick={save}>Lưu cài đặt</button>
        <button className="nb-btn" onClick={exportJson}>Xuất JSON tài khoản</button>
      </div>
    </div>
  )
}
