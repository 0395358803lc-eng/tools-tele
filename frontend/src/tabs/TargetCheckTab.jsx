import { useCallback, useEffect, useState } from 'react'
import { Endpoints } from '../lib/api'
import { fmtTime } from '../lib/util'
import { peerKindVi } from '../lib/vi'
import { useToast } from '../lib/toast.jsx'

const STATUSES = ['present', 'absent', 'skipped', 'failed']

function ItemList({ title, items, tone }) {
  if (!items.length) return null
  return (
    <div className="nb-card-sm p-3">
      <div className="flex items-center gap-2 mb-2">
        <span className={'nb-badge text-black ' + tone}>{title}</span>
        <span className="text-xs opacity-60">{items.length}</span>
      </div>
      <div className="space-y-2 max-h-72 overflow-auto">
        {items.map((r, index) => (
          <div key={r.id ?? r.account_id ?? `${r.status}-${index}`} className="border-2 border-black dark:border-white p-2 text-sm">
            <div className="flex items-center gap-2">
              <span className="font-bold truncate">{r.name || `Tài khoản ${r.account_id ?? 'đã xóa'}`}</span>
              <span className="text-xs opacity-60 ml-auto font-mono">{r.phone || '—'}</span>
            </div>
            <div className="text-xs opacity-70 mt-1">{r.detail || '—'}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function normalizeHistory(detail) {
  const out = {
    check_id: detail.id,
    target: detail.target,
    peer: detail.peer,
    total: detail.total,
    created_at: detail.created_at,
    results: detail.results || [],
  }
  for (const status of STATUSES) out[status] = out.results.filter((r) => r.status === status)
  return out
}

function CountBadge({ label, value, cls }) {
  return <span className={'nb-badge text-black ' + cls}>{label} {value || 0}</span>
}

export default function TargetCheckTab() {
  const toast = useToast()
  const [target, setTarget] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [history, setHistory] = useState([])
  const [historyBusy, setHistoryBusy] = useState(false)

  const loadHistory = useCallback(async () => {
    try {
      const rows = await Endpoints.targetChecks(30)
      setHistory(rows || [])
    } catch (e) {
      if (e.status !== 401) toast.error('Tải lịch sử kiểm tra: ' + e.message)
    }
  }, [toast])

  useEffect(() => { loadHistory() }, [loadHistory])

  async function search() {
    const t = target.trim()
    if (!t) {
      toast.error('Nhập tên người dùng hoặc liên kết')
      return
    }
    setBusy(true)
    setResult(null)
    try {
      const r = await Endpoints.targetCheck(t)
      setResult(r)
      await loadHistory()
    } catch (e) {
      toast.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function openHistory(id) {
    setHistoryBusy(true)
    try {
      const detail = await Endpoints.targetCheckDetail(id)
      setResult(normalizeHistory(detail))
      setTarget(detail.target || '')
    } catch (e) {
      toast.error(e.message)
    } finally {
      setHistoryBusy(false)
    }
  }

  const totals = result
    ? {
        present: result.present?.length || 0,
        absent: result.absent?.length || 0,
        skipped: result.skipped?.length || 0,
        failed: result.failed?.length || 0,
      }
    : null

  return (
    <div className="space-y-4">
      <div className="nb-card p-4">
        <div className="font-extrabold uppercase">Kiểm tra mục tiêu</div>
        <div className="text-sm opacity-70 mt-1">
          Kiểm tra một bot, kênh, nhóm hoặc tên người dùng trên mọi tài khoản đang kết nối. Kết quả được lưu lại để có thể xem lại mà không cần liên hệ Telegram lần nữa.
        </div>
        <div className="flex gap-2 mt-3">
          <input
            className="nb-input"
            placeholder="@username hoặc liên kết t.me"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') search() }}
          />
          <button className="nb-btn-pri" disabled={busy} onClick={search}>
            {busy ? 'Đang kiểm tra...' : 'Tìm trên tất cả tài khoản'}
          </button>
        </div>
      </div>

      {totals && (
        <div className="nb-card p-3">
          <div className="flex flex-wrap gap-2 items-center">
            <CountBadge label="tìm thấy" value={totals.present} cls="bg-brand-ok" />
            <CountBadge label="không tìm thấy" value={totals.absent} cls="bg-brand-warn" />
            <CountBadge label="bỏ qua" value={totals.skipped} cls="bg-brand-violet" />
            <CountBadge label="lỗi" value={totals.failed} cls="bg-brand-err" />
            {result.check_id && <span className="ml-auto text-[10px] font-mono opacity-60">lượt kiểm tra {result.check_id}</span>}
          </div>
        </div>
      )}

      {result && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <ItemList
            title={result.peer?.kind === 'bot' || result.peer?.kind === 'user' ? 'Chưa dùng' : 'Chưa tham gia'}
            items={result.absent || []}
            tone="bg-brand-warn"
          />
          <ItemList
            title={result.peer?.kind === 'bot' || result.peer?.kind === 'user' ? 'Đã dùng' : 'Đã tham gia'}
            items={result.present || []}
            tone="bg-brand-ok"
          />
          <ItemList title="Bỏ qua" items={result.skipped || []} tone="bg-brand-violet" />
          <ItemList title="Lỗi" items={result.failed || []} tone="bg-brand-err" />
        </div>
      )}

      <div className="nb-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <div className="font-extrabold uppercase">Lịch sử kiểm tra</div>
          <span className="text-xs opacity-60">{history.length} gần đây</span>
          <button className="nb-btn !py-1 !px-2 text-xs ml-auto" disabled={historyBusy} onClick={loadHistory}>Làm mới</button>
        </div>
        {history.length === 0 ? (
          <div className="text-sm opacity-60">Chưa có lượt kiểm tra nào được lưu.</div>
        ) : (
          <div className="overflow-auto max-h-80">
            <table className="w-full text-sm">
              <thead className="text-[10px] uppercase font-extrabold border-b-2 border-black dark:border-white sticky top-0 bg-white dark:bg-zinc-900">
                <tr><th className="text-left p-2">Thời điểm</th><th className="text-left p-2">Mục tiêu</th><th className="text-left p-2">Loại</th><th className="text-left p-2">Kết quả</th><th className="p-2" /></tr>
              </thead>
              <tbody>
                {history.map((row) => (
                  <tr key={row.id} className="border-b border-zinc-300 dark:border-zinc-700">
                    <td className="p-2 text-xs whitespace-nowrap">{fmtTime(row.created_at)}</td>
                    <td className="p-2 font-mono text-xs">{row.target}</td>
                    <td className="p-2 text-xs uppercase">{peerKindVi(row.peer?.kind)}</td>
                    <td className="p-2"><div className="flex gap-1 flex-wrap">
                      <CountBadge label="✓" value={row.counts?.present} cls="bg-brand-ok" />
                      <CountBadge label="−" value={row.counts?.absent} cls="bg-brand-warn" />
                      {(row.counts?.skipped || 0) > 0 && <CountBadge label="bỏ qua" value={row.counts.skipped} cls="bg-brand-violet" />}
                      {(row.counts?.failed || 0) > 0 && <CountBadge label="lỗi" value={row.counts.failed} cls="bg-brand-err" />}
                    </div></td>
                    <td className="p-2 text-right"><button className="nb-btn !py-1 !px-2 text-xs" disabled={historyBusy} onClick={() => openHistory(row.id)}>Xem</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
