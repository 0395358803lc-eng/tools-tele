import { useRef, useState } from 'react'
import { Endpoints } from '../lib/api'
import { useToast } from '../lib/toast.jsx'
import ProgressModal from '../components/ProgressModal.jsx'
import ReactionBuilderModal from '../components/ReactionBuilderModal.jsx'
import { useBulkProgress } from '../lib/useBulkProgress'

function AccountPicker({ accounts, ids, setIds }) {
  return (
    <div className="nb-card-sm p-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="font-bold text-xs uppercase">Tài khoản</span>
        <button className="nb-btn !py-0.5 !px-1 text-[10px]" onClick={() => setIds(accounts.map((a) => a.id))}>Tất cả</button>
        <button className="nb-btn !py-0.5 !px-1 text-[10px]" onClick={() => setIds([])}>Không chọn</button>
        <span className="text-xs opacity-70 ml-auto">{ids.length} đã chọn</span>
      </div>
      <div className="flex flex-wrap gap-1 max-h-32 overflow-auto">
        {accounts.map((a) => (
          <label key={a.id} className={'nb-badge cursor-pointer ' + (ids.includes(a.id) ? 'bg-brand-pri text-black' : 'bg-white text-black')}>
            <input type="checkbox" className="mr-1"
              checked={ids.includes(a.id)}
              onChange={() => setIds((arr) => arr.includes(a.id) ? arr.filter((x) => x !== a.id) : [...arr, a.id])}
            />
            {(a.first_name || a.phone).slice(0, 14)}
          </label>
        ))}
      </div>
    </div>
  )
}

const keyOf = (e) => (e.custom_emoji_id ? `c:${e.custom_emoji_id}` : `s:${e.emoji}`)

function parseTargetList(value) {
  const out = []
  const seen = new Set()
  for (const raw of String(value || '').split(/[\n,;]+/)) {
    const target = raw.trim()
    if (!target) continue
    const key = target.startsWith('+')
      ? '+' + target.replace(/\D/g, '')
      : target.toLowerCase().replace(/^https?:\/\//, '').replace(/^@/, '')
    if (seen.has(key)) continue
    seen.add(key)
    out.push(target)
  }
  return out
}

// Split account ids across emojis by percentage. Shuffled so it's fair.
// Leftover accounts (when total% < 100) simply don't react. custom_emoji_id is
// carried through so premium custom emoji reactions reach the backend.
function distribute(ids, emojis) {
  const shuffled = [...ids]
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]]
  }
  const N = shuffled.length
  let cursor = 0
  const reactions = []
  for (const e of emojis) {
    let count = Math.min(Math.round((e.pct / 100) * N), N - cursor)
    const slice = shuffled.slice(cursor, cursor + count)
    cursor += count
    if (slice.length) reactions.push({ emoji: e.emoji, custom_emoji_id: e.custom_emoji_id || null, account_ids: slice })
  }
  return reactions
}

export default function MessagingTab({ accounts, selected }) {
  const toast = useToast()
  const { progress, run, close } = useBulkProgress()

  const [target, setTarget] = useState('')
  const [text, setText] = useState('')
  const [bulkIds, setBulkIds] = useState([])
  const [targetsText, setTargetsText] = useState('')
  const [importingTargets, setImportingTargets] = useState(false)
  const [importInfo, setImportInfo] = useState(null)
  const [recipientFile, setRecipientFile] = useState(null)
  const [importPreview, setImportPreview] = useState(null)
  const [importColumns, setImportColumns] = useState([])
  const [importHasHeader, setImportHasHeader] = useState(false)
  const recipientFileRef = useRef(null)
  const [busy, setBusy] = useState(false)

  // react
  const [postLink, setPostLink] = useState('')
  const [emojis, setEmojis] = useState([{ emoji: '🔥', pct: 100 }]) // [{emoji, pct}]
  const [reactModal, setReactModal] = useState(false)
  const [reactIds, setReactIds] = useState([])

  // view
  const [viewLink, setViewLink] = useState('')
  const [viewIds, setViewIds] = useState([])

  // wipe DM / chat by username (deletes the whole conversation, both sides)
  const [wipeTarget, setWipeTarget] = useState('')
  const [wipeIds, setWipeIds] = useState([])

  const totalPct = emojis.reduce((s, e) => s + (Number(e.pct) || 0), 0)
  const multiTargets = parseTargetList(targetsText)

  async function sendOne() {
    if (!selected) { toast.error('Hãy chọn một tài khoản trước'); return }
    setBusy(true)
    try {
      await Endpoints.sendMessage(selected.id, target, text)
      toast.success('Đã gửi!')
    } catch (e) { toast.error(e.message) } finally { setBusy(false) }
  }

  async function sendBulk() {
    if (bulkIds.length === 0 || !target || !text) { toast.error('Hãy chọn tài khoản, mục tiêu và nội dung'); return }
    if (!confirm(`Gửi từ ${bulkIds.length} tài khoản?`)) return
    setBusy(true)
    await run(`Gửi hàng loạt (${bulkIds.length} tài khoản)`, (onEvent) => Endpoints.bulkSend(bulkIds, target, text, onEvent))
    setBusy(false)
  }

  async function importRecipientFile(file) {
    if (!file) return
    setImportingTargets(true)
    try {
      const preview = await Endpoints.previewMessageTargets(file)
      setRecipientFile(file)
      setImportPreview(preview)
      setImportColumns(preview.suggested_columns?.length ? preview.suggested_columns : (preview.column_count === 1 ? [0] : []))
      setImportHasHeader(!!preview.header_detected)
      setImportInfo(null)
    } catch (e) { toast.error(e.message) }
    finally {
      setImportingTargets(false)
      if (recipientFileRef.current) recipientFileRef.current.value = ''
    }
  }

  async function confirmRecipientImport() {
    if (!recipientFile || !importColumns.length) return toast.error('Chọn ít nhất một cột người nhận')
    setImportingTargets(true)
    try {
      const result = await Endpoints.importMessageTargets(recipientFile, importColumns, importHasHeader)
      const merged = parseTargetList([targetsText, ...(result.targets || [])].join('\n'))
      setTargetsText(merged.join('\n')); setImportInfo(result)
      setImportPreview(null); setRecipientFile(null); setImportColumns([])
      const notes = []
      if (result.duplicates) notes.push(`${result.duplicates} trùng`)
      if (result.invalid_count) notes.push(`${result.invalid_count} không hợp lệ`)
      toast.success(`Đã thêm ${result.count} người nhận${notes.length ? ` (${notes.join(', ')})` : ''}`)
    } catch (e) { toast.error(e.message) }
    finally { setImportingTargets(false) }
  }

  async function sendMultiTargets() {
    if (bulkIds.length === 0 || multiTargets.length === 0 || !text.trim()) {
      toast.error('Hãy chọn tài khoản, nhập danh sách người nhận và nội dung')
      return
    }
    if (!confirm(
      `Gửi 1 lần tới ${multiTargets.length} người nhận bằng ${bulkIds.length} tài khoản?\n\n` +
      `Danh sách sẽ được chia đều; mỗi người nhận chỉ xuất hiện một lần trong tác vụ.`
    )) return
    setBusy(true)
    await run(
      `Gửi ${multiTargets.length} người nhận (${bulkIds.length} tài khoản)`,
      (onEvent) => Endpoints.multiSend(bulkIds, multiTargets, text, onEvent),
    )
    setBusy(false)
  }

  async function doReact() {
    if (reactIds.length === 0 || !postLink || emojis.length === 0) { toast.error('Hãy chọn tài khoản, liên kết và emoji'); return }
    if (totalPct > 100) { toast.error('Tổng tỷ lệ không được vượt quá 100%'); return }
    const reactions = distribute(reactIds, emojis)
    if (reactions.length === 0) { toast.error('Hãy tăng tỷ lệ — chưa có tài khoản nào được phân bổ'); return }
    setBusy(true)
    await run('Thả cảm xúc bài viết', (onEvent) => Endpoints.react(postLink, reactions, onEvent))
    setBusy(false)
  }

  async function doView() {
    if (viewIds.length === 0 || !viewLink) { toast.error('Hãy chọn tài khoản và liên kết'); return }
    setBusy(true)
    await run(`Xem bài viết (${viewIds.length} tài khoản)`, (onEvent) => Endpoints.view(viewIds, viewLink, onEvent))
    setBusy(false)
  }

  async function doWipe() {
    const t = wipeTarget.trim()
    if (wipeIds.length === 0 || !t) { toast.error('Hãy chọn tài khoản và nhập @username'); return }
    if (!confirm(
      `Xóa SẠCH toàn bộ cuộc trò chuyện với "${t}" trên ${wipeIds.length} tài khoản?\n\n` +
      `Mọi tin nhắn trong cuộc trò chuyện sẽ bị xóa ở CẢ HAI phía (revoke=true)\n` +
      `và cuộc trò chuyện bị xóa hoàn toàn — sẽ không còn tồn tại.\n\n` +
      `Thao tác này là VĨNH VIỄN và không thể hoàn tác.`
    )) return
    setBusy(true)
    await run(`Xóa cuộc trò chuyện — ${t} (${wipeIds.length} tài khoản)`, (onEvent) => Endpoints.bulkWipeChat(wipeIds, t, onEvent))
    setBusy(false)
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="nb-card p-4">
        <h3 className="font-extrabold uppercase mb-3">Gửi tin nhắn</h3>
        <input className="nb-input mb-2" placeholder="@username hoặc liên kết trò chuyện"
          value={target} onChange={(e) => setTarget(e.target.value)} />
        <textarea className="nb-input min-h-[100px] mb-2" placeholder="Nội dung tin nhắn"
          value={text} onChange={(e) => setText(e.target.value)} />
        <div className="flex gap-2">
          <button className="nb-btn-pri flex-1" disabled={busy || !target || !text} onClick={sendOne}>
            Gửi (1 tài khoản)
          </button>
        </div>
        <div className="mt-4">
          <AccountPicker accounts={accounts} ids={bulkIds} setIds={setBulkIds} />
        </div>
        <button className="nb-btn mt-3 w-full" disabled={busy} onClick={sendBulk}>
          Gửi cùng 1 người nhận từ {bulkIds.length} tài khoản
        </button>

        <div className="border-t-2 border-black dark:border-white mt-4 pt-4">
          <div className="flex items-center gap-2 mb-2">
            <div className="font-extrabold uppercase text-sm">Gửi nhiều người nhận</div>
            <span className="nb-badge bg-brand-violet text-black ml-auto">{multiTargets.length} người nhận</span>
          </div>
          <textarea
            className="nb-input min-h-[130px] mb-2 font-mono text-sm"
            placeholder={'@username1\n@username2\n+84901234567\nhttps://t.me/username3'}
            value={targetsText}
            onChange={(e) => setTargetsText(e.target.value)}
          />
          <input
            ref={recipientFileRef}
            type="file"
            className="hidden"
            accept=".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
            onChange={(e) => importRecipientFile(e.target.files?.[0])}
          />
          <div className="flex gap-2 mb-2">
            <button
              type="button"
              className="nb-btn flex-1"
              disabled={busy || importingTargets}
              onClick={() => recipientFileRef.current?.click()}
            >
              {importingTargets ? 'Đang đọc tệp…' : 'Thêm từ CSV / Excel'}
            </button>
            <button
              type="button"
              className="nb-btn"
              disabled={busy || !targetsText}
              onClick={() => { setTargetsText(''); setImportInfo(null) }}
            >
              Xóa danh sách
            </button>
          </div>
          {importPreview && (
            <div className="nb-card-sm p-3 text-xs mb-2 space-y-2">
              <div className="font-extrabold uppercase">Xem trước file · {importPreview.rows} dòng</div>
              <div className="flex flex-wrap gap-2">
                {(importPreview.headers || []).map((header, idx) => (
                  <label key={idx} className={'nb-badge cursor-pointer ' + (importColumns.includes(idx) ? 'bg-brand-pri text-black' : 'bg-white text-black')}>
                    <input type="checkbox" className="mr-1" checked={importColumns.includes(idx)}
                      onChange={() => setImportColumns((old) => old.includes(idx) ? old.filter((x) => x !== idx) : [...old, idx])} />
                    {header || `Cột ${idx + 1}`}
                  </label>
                ))}
              </div>
              <label className="flex items-center gap-2"><input type="checkbox" checked={importHasHeader} onChange={(e) => setImportHasHeader(e.target.checked)} /> Dòng đầu là tiêu đề cột</label>
              <div className="overflow-auto max-h-36 border border-black/20 dark:border-white/20">
                <table className="w-full text-[10px]"><tbody>{(importPreview.sample || []).map((row, r) => <tr key={r} className="border-b border-black/10 dark:border-white/10">{row.map((cell, c) => <td key={c} className="p-1 whitespace-nowrap max-w-40 truncate">{cell}</td>)}</tr>)}</tbody></table>
              </div>
              <div className="flex gap-2"><button className="nb-btn-pri !py-1 !px-2" disabled={importingTargets || !importColumns.length} onClick={confirmRecipientImport}>Nhập cột đã chọn</button><button className="nb-btn !py-1 !px-2" onClick={() => { setImportPreview(null); setRecipientFile(null); setImportColumns([]) }}>Hủy</button></div>
            </div>
          )}
          {importInfo && (
            <div className="nb-card-sm p-2 text-[11px] mb-2">
              <b>{importInfo.filename}</b> · {importInfo.count} người nhận
              {importInfo.columns?.length ? ` · cột: ${importInfo.columns.join(', ')}` : ''}
              {importInfo.duplicates ? ` · ${importInfo.duplicates} trùng đã bỏ` : ''}
              {importInfo.invalid_count ? ` · ${importInfo.invalid_count} dòng không hợp lệ` : ''}
            </div>
          )}
          <div className="text-[11px] opacity-70 mb-2">
            Mỗi dòng, dấu phẩy hoặc dấu chấm phẩy là một người nhận. Hệ thống tự loại trùng và chia đều cho các tài khoản đã chọn; mỗi người nhận chỉ được gửi một lần. Số điện thoại nên dùng dạng quốc tế +mã_quốc_gia và chỉ hoạt động khi Telegram của tài khoản gửi có thể nhận diện số đó.
          </div>
          {multiTargets.length > 200 && (
            <div className="nb-card-sm p-2 text-[11px] bg-brand-err text-black mb-2">
              Danh sách có {multiTargets.length} người nhận. Mỗi tác vụ hỗ trợ tối đa 200; hãy chia danh sách thành nhiều lần gửi.
            </div>
          )}
          <div className="text-[11px] font-bold mb-3">Chỉ sử dụng với người nhận bạn được phép liên hệ.</div>
          <button
            className="nb-btn-pri w-full"
            disabled={busy || bulkIds.length === 0 || multiTargets.length === 0 || multiTargets.length > 200 || !text.trim()}
            onClick={sendMultiTargets}
          >
            Gửi danh sách — chia đều qua {bulkIds.length} tài khoản
          </button>
        </div>
      </div>

      <div className="nb-card p-4">
        <h3 className="font-extrabold uppercase mb-3">Thả cảm xúc bài viết</h3>
        <input className="nb-input mb-2" placeholder="https://t.me/channel/123"
          value={postLink} onChange={(e) => setPostLink(e.target.value)} />

        {/* chosen reactions summary + open the % builder popup */}
        <div className="nb-card-sm p-3 mb-3">
          <div className="flex items-center gap-2 mb-2">
            <span className="font-bold text-xs uppercase">Cảm xúc</span>
            <button className="nb-btn !py-0.5 !px-2 text-[11px] ml-auto" onClick={() => setReactModal(true)}>
              Đặt cảm xúc & tỷ lệ %
            </button>
          </div>
          {emojis.length === 0 ? (
            <div className="text-xs opacity-60">Chưa chọn cảm xúc — bấm “Đặt cảm xúc & tỷ lệ %”.</div>
          ) : (
            <div className="flex flex-wrap gap-1">
              {emojis.map((e) => (
                <span key={keyOf(e)} className="nb-badge bg-white text-black flex items-center gap-1">
                  <span className="text-base leading-none">{e.emoji}</span>
                  {e.custom_emoji_id && <span className="text-[9px] font-bold text-brand-violet" title="emoji tùy chỉnh">★</span>}
                  <span className="font-mono text-[11px]">{e.pct}%</span>
                </span>
              ))}
              <span className={'text-[11px] ml-auto font-bold self-center ' + (totalPct > 100 ? 'text-brand-err' : 'opacity-60')}>
                tổng {totalPct}%
              </span>
            </div>
          )}
        </div>

        <AccountPicker accounts={accounts} ids={reactIds} setIds={setReactIds} />
        <button className="nb-btn-pri mt-3 w-full" disabled={busy} onClick={doReact}>
          Gửi cảm xúc ({reactIds.length} tài khoản)
        </button>
      </div>

      <div className="nb-card p-4 lg:col-span-2">
        <h3 className="font-extrabold uppercase mb-3">Xem / Mở bài viết</h3>
        <input className="nb-input mb-2" placeholder="https://t.me/channel/123"
          value={viewLink} onChange={(e) => setViewLink(e.target.value)} />
        <AccountPicker accounts={accounts} ids={viewIds} setIds={setViewIds} />
        <button className="nb-btn-pri mt-3" disabled={busy} onClick={doView}>
          Mở bài viết ({viewIds.length})
        </button>
      </div>

      <div className="nb-card p-4 lg:col-span-2">
        <h3 className="font-extrabold uppercase mb-1 text-brand-err">Xóa sạch DM / Trò chuyện</h3>
        <div className="text-[11px] opacity-70 mb-3">
          Dán @username (hoặc liên kết t.me). Với mỗi tài khoản đã chọn, TOÀN BỘ cuộc trò chuyện
          với người dùng đó sẽ bị xóa ở <b>cả hai phía</b> (thu hồi) và cuộc trò chuyện sẽ bị xóa —
          sẽ bị xóa hoàn toàn. Vĩnh viễn, không thể hoàn tác.
        </div>
        <input className="nb-input mb-2" placeholder="@username hoặc https://t.me/username"
          value={wipeTarget} onChange={(e) => setWipeTarget(e.target.value)} />
        <AccountPicker accounts={accounts} ids={wipeIds} setIds={setWipeIds} />
        <button className="nb-btn-err mt-3" disabled={busy || wipeIds.length === 0 || !wipeTarget.trim()} onClick={doWipe}>
          Xóa trò chuyện trên {wipeIds.length} tài khoản
        </button>
      </div>

      {reactModal && (
        <ReactionBuilderModal
          accountCount={reactIds.length}
          accountId={reactIds[0] ?? selected?.id ?? accounts[0]?.id ?? null}
          postLink={postLink}
          initial={emojis}
          onConfirm={(list) => { setEmojis(list); setReactModal(false) }}
          onClose={() => setReactModal(false)}
        />
      )}

      <ProgressModal progress={progress} onClose={close} />
    </div>
  )
}
