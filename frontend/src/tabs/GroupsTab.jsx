import { useEffect, useState } from 'react'
import { Endpoints } from '../lib/api'
import { useToast } from '../lib/toast.jsx'
import { CopyButton } from '../lib/CopyButton'
import ProgressModal from '../components/ProgressModal.jsx'
import { useBulkProgress } from '../lib/useBulkProgress'
import { groupTypeVi } from '../lib/vi'

export default function GroupsTab({ accounts, selected }) {
  const toast = useToast()
  const [target, setTarget] = useState('')
  const [groups, setGroups] = useState([])
  const [loading, setLoading] = useState(false)
  const [bulkIds, setBulkIds] = useState([])
  const [busy, setBusy] = useState(false)
  const { progress, run, close } = useBulkProgress()

  async function loadGroups(id) {
    setLoading(true)
    try { setGroups(await Endpoints.listGroups(id)) }
    catch (e) { toast.error(e.message); setGroups([]) }
    finally { setLoading(false) }
  }

  useEffect(() => {
    if (selected) loadGroups(selected.id)
    else setGroups([])
  }, [selected?.id])

  async function joinOne() {
    if (!selected) { toast.error('Hãy chọn một tài khoản trước'); return }
    if (!target.trim()) return
    setBusy(true)
    try {
      await Endpoints.joinGroup(selected.id, target)
      toast.success('Đã tham gia!')
      await loadGroups(selected.id)
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }

  async function bulkJoin() {
    if (!target.trim() || bulkIds.length === 0) { toast.error('Hãy chọn tài khoản và nhập mục tiêu'); return }
    if (!confirm(`Tham gia ${target} bằng ${bulkIds.length} tài khoản?`)) return
    setBusy(true)
    await run(`Tham gia hàng loạt — ${target}`, (onEvent) => Endpoints.bulkJoin(bulkIds, target, onEvent))
    setBusy(false)
    if (selected) loadGroups(selected.id)
  }

  async function bulkLeaveTarget() {
    if (!target.trim() || bulkIds.length === 0) { toast.error('Hãy chọn tài khoản và nhập mục tiêu'); return }
    if (!confirm(`Rời ${target} trên các tài khoản đang là thành viên trong ${bulkIds.length} tài khoản đã chọn?`)) return
    setBusy(true)
    await run(`Rời hàng loạt — ${target}`, (onEvent) => Endpoints.bulkLeaveTarget(bulkIds, target, onEvent))
    setBusy(false)
    if (selected) loadGroups(selected.id)
  }

  async function leaveOne(chat_id) {
    if (!selected) return
    if (!confirm('Rời nhóm/kênh này?')) return
    setBusy(true)
    try {
      await Endpoints.leaveGroup(selected.id, chat_id)
      toast.success('Đã rời.')
      await loadGroups(selected.id)
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }

  async function bulkLeave(chat_id) {
    if (bulkIds.length === 0) { toast.error('Hãy chọn tài khoản'); return }
    if (!confirm(`Rời trên ${bulkIds.length} tài khoản?`)) return
    setBusy(true)
    await run(`Rời hàng loạt (${bulkIds.length} tài khoản)`, (onEvent) => Endpoints.bulkLeave(bulkIds, chat_id, onEvent))
    setBusy(false)
    if (selected) loadGroups(selected.id)
  }

  async function bulkLeaveAll() {
    if (bulkIds.length === 0) { toast.error('Hãy chọn tài khoản trước'); return }
    if (!confirm(
      `Rời MỌI nhóm/kênh trên ${bulkIds.length} tài khoản?\n\n` +
      `Mỗi tài khoản sẽ rời TOÀN BỘ nhóm và kênh hiện đang tham gia.\n` +
      `Thao tác này không thể hoàn tác (bạn sẽ phải tự tham gia lại từng nơi).`
    )) return
    setBusy(true)
    await run(`Rời TOÀN BỘ nhóm — ${bulkIds.length} tài khoản`, (onEvent) => Endpoints.bulkLeaveAll(bulkIds, onEvent))
    setBusy(false)
    if (selected) loadGroups(selected.id)
  }

  async function bulkDeleteAllMessages() {
    if (bulkIds.length === 0) { toast.error('Hãy chọn tài khoản trước'); return }
    if (!confirm(
      `Xóa TOÀN BỘ tin nhắn của bạn trong MỌI nhóm trên ${bulkIds.length} tài khoản?\n\n` +
      `Với mỗi tài khoản, mọi tin nhắn đã gửi trong TOÀN BỘ nhóm/kênh\n` +
      `(quét 2000 tin gần nhất mỗi nhóm) sẽ bị xóa với mọi người (revoke=true).\n\n` +
      `Thao tác này là VĨNH VIỄN.`
    )) return
    setBusy(true)
    await run(`Xóa TOÀN BỘ tin nhắn của tôi — ${bulkIds.length} tài khoản`, (onEvent) => Endpoints.bulkDeleteMyMessages(bulkIds, 2000, onEvent))
    setBusy(false)
    if (selected) loadGroups(selected.id)
  }

  async function deleteMyMessages(chat_id, title) {
    if (!selected) return
    setBusy(true)
    try {
      toast.info('Đang đếm tin nhắn của bạn trong cuộc trò chuyện này...')
      const cnt = await Endpoints.countMyMessages(selected.id, chat_id, 2000)
      if (cnt.count === 0) {
        toast.info('Không tìm thấy tin nhắn của bạn trong cuộc trò chuyện này (đã quét 2000 tin gần nhất)')
        setBusy(false)
        return
      }
      if (!confirm(
        `Xóa TOÀN BỘ ${cnt.count} tin nhắn bạn đã gửi trong "${title}"?\n\n` +
        `Thao tác này là VĨNH VIỄN và xóa tin nhắn với mọi người (revoke=true).\n\n` +
        `Tài khoản: ${(selected.first_name || selected.phone)}\n` +
        `Đã quét: 2000 tin nhắn gần nhất.`
      )) { setBusy(false); return }
      const r = await Endpoints.deleteMyMessages(selected.id, chat_id, 2000)
      toast.success(`Đã xóa ${r.deleted} tin nhắn khỏi "${title}"`)
      await loadGroups(selected.id)
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }

  const toggleId = (id) => setBulkIds((arr) => arr.includes(id) ? arr.filter((x) => x !== id) : [...arr, id])

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="lg:col-span-2">
        <div className="nb-card p-4 mb-4">
          <h3 className="font-extrabold uppercase mb-3">Tham gia nhóm / kênh</h3>
          <div className="flex gap-2">
            <input
              className="nb-input"
              placeholder="@username hoặc t.me/joinchat/AAA…"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            />
            <button className="nb-btn-pri" disabled={busy} onClick={joinOne}>Tham gia (1 tài khoản)</button>
            <button className="nb-btn" disabled={busy} onClick={bulkJoin}>Tham gia hàng loạt ({bulkIds.length})</button>
            <button className="nb-btn-err" disabled={busy} onClick={bulkLeaveTarget}>Rời hàng loạt ({bulkIds.length})</button>
          </div>
          <div className="text-[11px] opacity-60 mt-2">
            Rời hàng loạt: trong các tài khoản đã chọn, tài khoản nào đang là thành viên của liên kết/@username này sẽ rời.
          </div>
        </div>

        <div className="nb-card p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-extrabold uppercase">
              {selected ? `Nhóm & Kênh — ${(selected.first_name || selected.phone)}` : 'Chọn một tài khoản'}
            </h3>
            {selected && (
              <button className="nb-btn !py-1 !px-2 text-xs" onClick={() => loadGroups(selected.id)}>Làm mới</button>
            )}
          </div>
          {loading && <div className="opacity-60 text-sm">Đang tải…</div>}
          {!loading && !selected && <div className="opacity-60 text-sm">Hãy chọn một tài khoản từ thanh bên.</div>}
          {!loading && selected && groups.length === 0 && <div className="opacity-60 text-sm">Không tìm thấy nhóm/kênh.</div>}
          <div className="space-y-2">
            {groups.map((g) => (
              <div key={g.id} className="nb-card-sm p-3 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="font-bold truncate flex items-center gap-1">
                    {g.title}
                    {g.invite_link && <CopyButton value={g.invite_link} label="liên kết" />}
                  </div>
                  <div className="text-xs opacity-70 truncate flex items-center gap-1">
                    <span className="nb-badge bg-white text-black !px-1 !py-0">{groupTypeVi(g.type)}</span>
                    {g.username && (
                      <span className="flex items-center gap-1">@{g.username}<CopyButton value={g.username} /></span>
                    )}
                    {g.members != null && <span>• {g.members.toLocaleString()} thành viên</span>}
                  </div>
                </div>
                <button className="nb-btn-err !py-1 !px-2 text-xs" title="Xóa mọi tin nhắn BẠN đã gửi tại đây (thu hồi với mọi người)"
                  onClick={() => deleteMyMessages(g.id, g.title)} disabled={busy}>
                  Xóa tin của tôi
                </button>
                <button className="nb-btn-err !py-1 !px-2 text-xs" onClick={() => leaveOne(g.id)}>Rời</button>
                <button className="nb-btn !py-1 !px-2 text-xs" onClick={() => bulkLeave(g.id)}>Rời hàng loạt</button>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="nb-card p-4 h-fit">
        <h3 className="font-extrabold uppercase mb-3">Chọn hàng loạt</h3>
        <div className="flex items-center gap-2 mb-2">
          <button className="nb-btn !py-1 !px-2 text-xs" onClick={() => setBulkIds(accounts.map((a) => a.id))}>Chọn tất cả</button>
          <button className="nb-btn !py-1 !px-2 text-xs" onClick={() => setBulkIds([])}>Xóa chọn</button>
          <span className="text-xs opacity-70 ml-auto">{bulkIds.length} đã chọn</span>
        </div>
        <div className="space-y-1 max-h-[45vh] overflow-auto">
          {accounts.map((a) => (
            <label key={a.id} className="flex items-center gap-2 p-1 cursor-pointer hover:bg-zinc-100 dark:hover:bg-zinc-800">
              <input type="checkbox" checked={bulkIds.includes(a.id)} onChange={() => toggleId(a.id)} />
              <span className="text-sm truncate">{(a.first_name + ' ' + a.last_name).trim() || a.phone}</span>
            </label>
          ))}
        </div>

        {/* DANGER ZONE — acts on EVERY group of EVERY selected account */}
        <div className="mt-4 pt-3 border-t-2 border-black dark:border-white">
          <div className="text-[10px] uppercase font-extrabold tracking-tight text-brand-err mb-2">
            Vùng nguy hiểm — toàn bộ nhóm, toàn bộ tài khoản đã chọn
          </div>
          <div className="space-y-2">
            <button className="nb-btn-err w-full text-xs" disabled={busy || bulkIds.length === 0} onClick={bulkLeaveAll}>
              Rời TOÀN BỘ nhóm ({bulkIds.length})
            </button>
            <button className="nb-btn-err w-full text-xs" disabled={busy || bulkIds.length === 0} onClick={bulkDeleteAllMessages}>
              Xóa TOÀN BỘ tin của tôi ở mọi nơi ({bulkIds.length})
            </button>
          </div>
        </div>
      </div>

      <ProgressModal progress={progress} onClose={close} />
    </div>
  )
}
