import { useState, useRef, useMemo, useEffect } from 'react'
import { Endpoints } from '../lib/api'
import { useToast } from '../lib/toast.jsx'
import ProgressModal from '../components/ProgressModal.jsx'
import { useBulkProgress } from '../lib/useBulkProgress'

// RFC-4180-style CSV/TXT parser with support for quoted commas/tabs,
// escaped quotes (""), CRLF, and embedded newlines inside quoted fields.
function detectDelimiter(text) {
  let quoted = false
  let commas = 0
  let tabs = 0
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]
    if (ch === '"') {
      if (quoted && text[i + 1] === '"') { i += 1; continue }
      quoted = !quoted
      continue
    }
    if (!quoted && (ch === '\n' || ch === '\r')) break
    if (!quoted && ch === ',') commas += 1
    if (!quoted && ch === '\t') tabs += 1
  }
  return tabs > commas ? '\t' : ','
}

function parseDelimited(text, sep) {
  const rows = []
  let row = []
  let field = ''
  let quoted = false
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]
    if (ch === '"') {
      if (quoted && text[i + 1] === '"') { field += '"'; i += 1; continue }
      quoted = !quoted
      continue
    }
    if (!quoted && ch === sep) {
      row.push(field); field = ''; continue
    }
    if (!quoted && (ch === '\n' || ch === '\r')) {
      if (ch === '\r' && text[i + 1] === '\n') i += 1
      row.push(field); field = ''
      if (row.some((v) => v.trim() !== '')) rows.push(row)
      row = []
      continue
    }
    field += ch
  }
  row.push(field)
  if (row.some((v) => v.trim() !== '')) rows.push(row)
  return rows
}

export function parseCsv(text) {
  const sep = detectDelimiter(text)
  return parseDelimited(text, sep).map((parts) => ({
    first_name: (parts[0] ?? '').trim(),
    last_name: (parts[1] ?? '').trim(),
    username: (parts[2] ?? '').trim().replace(/^@/, ''),
    bio: parts.slice(3).join(sep).trim(),
  }))
}


export default function BulkTab({ accounts, onDone }) {
  const toast = useToast()
  const { progress, run, close } = useBulkProgress()
  const [ids, setIds] = useState([])
  // simple mode (one value to all)
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [username, setUsername] = useState('')
  const [bio, setBio] = useState('')
  const [appendNumber, setAppendNumber] = useState(false)
  const [startNumber, setStartNumber] = useState(1)
  // CSV mode
  const [csvRows, setCsvRows] = useState([])  // [{first_name, last_name, bio}, ...]
  const csvRef = useRef(null)
  // photos (accumulating)
  const [photos, setPhotos] = useState([])    // File[]
  const photoRef = useRef(null)
  const [busy, setBusy] = useState(false)

  const allChecked = ids.length === accounts.length && accounts.length > 0
  const toggleAll = () => setIds(allChecked ? [] : accounts.map((a) => a.id))
  const toggle = (id) => setIds((arr) => arr.includes(id) ? arr.filter((x) => x !== id) : [...arr, id])

  // ----- CSV -----
  function loadCsv(e) {
    const file = e.target.files?.[0]; if (!file) return
    const reader = new FileReader()
    reader.onload = () => {
      const rows = parseCsv(String(reader.result || ''))
      setCsvRows(rows)
      toast.info(`Đã tải ${rows.length} dòng CSV`)
    }
    reader.onerror = () => toast.error('Không thể đọc tệp CSV')
    reader.readAsText(file)
    if (csvRef.current) csvRef.current.value = ''
  }
  function clearCsv() { setCsvRows([]) }

  async function applyProfile() {
    if (ids.length === 0) { toast.error('Hãy chọn tài khoản'); return }
    const usingCsv = csvRows.length > 0
    if (!usingCsv && !firstName && !lastName && !username && bio === '') {
      toast.error('Hãy đặt ít nhất một trường hoặc tải tệp CSV')
      return
    }
    if (!usingCsv && username && !appendNumber && ids.length > 1) {
      toast.error('Tên người dùng phải là duy nhất. Hãy bật "Thêm số thứ tự" hoặc dùng CSV cho nhiều tài khoản.')
      return
    }
    if (!confirm(`Áp dụng thay đổi hồ sơ cho ${ids.length} tài khoản?` + (usingCsv ? ` (CSV sẽ ánh xạ ${Math.min(ids.length, csvRows.length)} dòng đầu tiên)` : ''))) return
    let per_account = null
    if (usingCsv) {
      per_account = {}
      ids.forEach((aid, i) => {
        const row = csvRows[i]
        if (!row) return
        per_account[String(aid)] = {
          first_name: row.first_name || null,
          last_name:  row.last_name  || null,
          username:   row.username   || null,
          bio:        row.bio        || null,
        }
      })
    }
    const payload = {
      account_ids: ids,
      first_name: usingCsv ? null : (firstName || null),
      last_name:  usingCsv ? null : (lastName || null),
      username:   usingCsv ? null : (username || null),
      bio:        usingCsv ? null : (bio === '' ? null : bio),
      append_number: !usingCsv && appendNumber,
      start_number: startNumber,
      per_account,
    }
    setBusy(true)
    await run(`Sửa hồ sơ hàng loạt (${ids.length} tài khoản)`, (onEvent) => Endpoints.bulkProfile(payload, onEvent))
    setBusy(false)
    onDone?.()
  }

  // ----- PHOTOS -----
  function addPhotos(e) {
    const list = Array.from(e.target.files || [])
    if (!list.length) return
    setPhotos((cur) => [...cur, ...list])
    if (photoRef.current) photoRef.current.value = ''  // allow re-picking same files
    toast.info(`Đã thêm ${list.length} ảnh (tổng ${photos.length + list.length})`)
  }
  function removePhoto(i) { setPhotos((cur) => cur.filter((_, j) => j !== i)) }
  function clearPhotos() { setPhotos([]) }

  const photoThumbs = useMemo(
    () => photos.map((f) => ({ name: f.name, size: f.size, url: URL.createObjectURL(f) })),
    [photos]
  )

  useEffect(() => {
    return () => {
      for (const thumb of photoThumbs) URL.revokeObjectURL(thumb.url)
    }
  }, [photoThumbs])

  async function applyPhoto() {
    if (photos.length === 0) { toast.error('Hãy chọn ít nhất một ảnh'); return }
    if (ids.length === 0) { toast.error('Hãy chọn tài khoản'); return }
    const usable = Math.min(photos.length, ids.length)
    const extra = photos.length > ids.length ? ` (${photos.length - ids.length} ảnh thừa sẽ bị bỏ qua)` : ''
    const missing = ids.length > photos.length ? ` (${ids.length - photos.length} tài khoản bị bỏ qua vì thiếu ảnh)` : ''
    if (!confirm(`Áp dụng ${usable} ảnh cho ${ids.length} tài khoản theo thứ tự?${extra}${missing}`)) return
    setBusy(true)
    await run(`Ảnh hồ sơ hàng loạt (${usable}/${ids.length})`, (onEvent) => Endpoints.bulkPhoto(ids, photos, onEvent))
    setBusy(false)
    onDone?.()
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <div className="lg:col-span-2 space-y-4">
        <div className="nb-card p-4">
          <h3 className="font-extrabold uppercase mb-3">Sửa hồ sơ hàng loạt</h3>

          <div className="nb-card-sm p-3 mb-3 bg-zinc-50 dark:bg-zinc-800">
            <div className="text-xs font-bold uppercase mb-2">Nhập CSV / TXT (tùy chọn)</div>
            <div className="flex items-center gap-2 flex-wrap">
              <input ref={csvRef} type="file" accept=".csv,.txt" onChange={loadCsv}
                className="text-xs file:nb-btn file:!py-1 file:!px-2" />
              {csvRows.length > 0 && (
                <>
                  <span className="text-xs font-bold">{csvRows.length} dòng đã tải</span>
                  <button className="nb-btn !py-0.5 !px-2 text-xs" onClick={clearCsv}>Xóa chọn</button>
                </>
              )}
            </div>
            <div className="text-[10px] opacity-60 mt-1">
              Định dạng: mỗi dòng = <code>firstname,lastname,username,bio</code> (tab hoặc dấu phẩy). Hỗ trợ trường có dấu ngoặc kép và dấu phẩy bên trong. Dòng N áp dụng cho tài khoản được chọn thứ N.
              Có thể để trống bất kỳ trường nào để bỏ qua. <b>Tên người dùng phải là duy nhất</b> cho từng tài khoản (quy định Telegram) — tên đã được dùng sẽ được báo riêng theo tài khoản.
              {csvRows.length > 0 && firstName === '' && lastName === '' && bio === '' ? '' : ' Khi đã tải CSV, các trường bên dưới sẽ được bỏ qua.'}
            </div>
            {csvRows.length > 0 && (
              <div className="mt-2 max-h-32 overflow-auto text-xs font-mono opacity-80">
                {csvRows.slice(0, 5).map((r, i) => (
                  <div key={i}>{i + 1}. {r.first_name} | {r.last_name} | {r.username ? '@' + r.username : '—'} | {r.bio.slice(0, 40)}</div>
                ))}
                {csvRows.length > 5 && <div>... +{csvRows.length - 5} dòng nữa</div>}
              </div>
            )}
          </div>

          <div className={'grid grid-cols-2 gap-3 ' + (csvRows.length > 0 ? 'opacity-50 pointer-events-none' : '')}>
            <label>
              <div className="text-xs font-bold uppercase mb-1">Tên (giống nhau cho tất cả)</div>
              <input className="nb-input" value={firstName} onChange={(e) => setFirstName(e.target.value)} placeholder="để trống để bỏ qua" />
            </label>
            <label>
              <div className="text-xs font-bold uppercase mb-1">Họ (giống nhau cho tất cả)</div>
              <input className="nb-input" value={lastName} onChange={(e) => setLastName(e.target.value)} placeholder="để trống để bỏ qua" />
            </label>
            <label className="col-span-2">
              <div className="text-xs font-bold uppercase mb-1">Tên người dùng (không có @)</div>
              <input className="nb-input" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="để trống để bỏ qua" />
              <div className="text-[10px] opacity-60 mt-1">
                Phải là duy nhất cho mỗi tài khoản. Dùng "Thêm số thứ tự" bên dưới để tự tạo (ví dụ myuser1, myuser2), hoặc dùng CSV để đặt tên riêng.
              </div>
            </label>
            <label className="col-span-2">
              <div className="text-xs font-bold uppercase mb-1">Tiểu sử (tối đa 70 ký tự)</div>
              <textarea maxLength={70} className="nb-input" value={bio} onChange={(e) => setBio(e.target.value)} placeholder="để trống để bỏ qua" />
            </label>
          </div>
          <label className={'flex items-center gap-2 mt-3 ' + (csvRows.length > 0 ? 'opacity-50 pointer-events-none' : '')}>
            <input type="checkbox" checked={appendNumber} onChange={(e) => setAppendNumber(e.target.checked)} />
            <span className="text-sm">Thêm số thứ tự vào tên/họ{username ? ' và tên người dùng' : ''} (ví dụ "Family 1", "Family 2"{username ? `, "${username}1", "${username}2"` : ''})</span>
            {appendNumber && (
              <input type="number" min={1} className="nb-input !w-20 !py-1" value={startNumber}
                onChange={(e) => setStartNumber(Number(e.target.value) || 1)} />
            )}
          </label>

          <button className="nb-btn-pri mt-3" disabled={busy} onClick={applyProfile}>
            Áp dụng hồ sơ cho {ids.length} tài khoản
            {csvRows.length > 0 && ids.length > 0 && (
              <span className="ml-1 opacity-70">(dùng CSV — đã ánh xạ {Math.min(ids.length, csvRows.length)})</span>
            )}
          </button>
        </div>

        <div className="nb-card p-4">
          <h3 className="font-extrabold uppercase mb-3">Ảnh hồ sơ hàng loạt</h3>
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <input ref={photoRef} type="file" accept="image/*" multiple onChange={addPhotos}
              className="text-xs file:nb-btn file:!py-1 file:!px-2" />
            <button className="nb-btn !py-1 !px-2 text-xs" disabled={photos.length === 0} onClick={clearPhotos}>
              Xóa tất cả
            </button>
            <div className="text-xs ml-auto">
              <span className="font-bold">{photos.length}</span> ảnh •{' '}
              <span className="font-bold">{ids.length}</span> tài khoản
              {photos.length > 0 && ids.length > 0 && (
                <span className={'ml-2 nb-badge text-black ' + (photos.length >= ids.length ? 'bg-brand-ok' : 'bg-brand-warn')}>
                  {photos.length >= ids.length ? 'đủ ảnh' : `cần thêm ${ids.length - photos.length} ảnh`}
                </span>
              )}
            </div>
          </div>
          <div className="text-[11px] opacity-70 mb-2">
            Chọn ảnh theo nhiều đợt (có thể bấm "Chọn tệp" nhiều lần để cộng dồn). Ảnh #1 → tài khoản #1, ảnh #2 → tài khoản #2... Ảnh thừa sẽ bị bỏ qua; nếu ảnh ít hơn số tài khoản, các tài khoản còn lại sẽ được bỏ qua.
          </div>
          {photos.length > 0 && (
            <div className="grid grid-cols-6 sm:grid-cols-8 gap-2 mb-3 max-h-72 overflow-auto p-2 bg-zinc-50 dark:bg-zinc-800 border-2 border-black dark:border-white">
              {photoThumbs.map((p, i) => (
                <div key={i} className="relative group">
                  <img src={p.url} alt={p.name} className="w-full aspect-square object-cover border-2 border-black dark:border-white" />
                  <span className="absolute top-0 left-0 bg-black text-white text-[10px] font-bold px-1">{i + 1}</span>
                  <button onClick={() => removePhoto(i)}
                    className="absolute top-0 right-0 bg-brand-err text-black text-[10px] font-bold px-1 opacity-0 group-hover:opacity-100 transition">
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
          <button className="nb-btn-pri" disabled={busy || photos.length === 0 || ids.length === 0} onClick={applyPhoto}>
            Áp dụng ảnh cho {Math.min(photos.length, ids.length)}/{ids.length} tài khoản
          </button>
        </div>
      </div>

      <div className="nb-card p-4 h-fit">
        <h3 className="font-extrabold uppercase mb-3">Chọn tài khoản</h3>
        <label className="flex items-center gap-2 mb-2">
          <input type="checkbox" checked={allChecked} onChange={toggleAll} />
          <span className="font-bold text-sm">Chọn tất cả ({accounts.length})</span>
        </label>
        <div className="text-[10px] opacity-60 mb-2">
          Thứ tự rất quan trọng: dòng N của CSV / ảnh #N → tài khoản #N (từ trên xuống dưới danh sách).
        </div>
        <div className="space-y-1 max-h-[60vh] overflow-auto">
          {accounts.map((a, i) => (
            <label key={a.id} className="flex items-center gap-2 p-1 cursor-pointer hover:bg-zinc-100 dark:hover:bg-zinc-800">
              <input type="checkbox" checked={ids.includes(a.id)} onChange={() => toggle(a.id)} />
              <span className="text-[10px] opacity-50 font-mono w-5">{ids.indexOf(a.id) + 1 || ''}</span>
              <span className="text-sm truncate flex-1">{(a.first_name + ' ' + a.last_name).trim() || a.phone}</span>
              <span className="text-xs opacity-60 font-mono">{a.status === 'connected' ? '●' : '○'}</span>
            </label>
          ))}
        </div>
      </div>

      <ProgressModal progress={progress} onClose={close} />
    </div>
  )
}
