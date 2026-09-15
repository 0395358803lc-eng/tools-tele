import { useCallback, useEffect, useRef, useState } from 'react'
import { Endpoints } from '../lib/api'
import { useToast } from '../lib/toast.jsx'
import { accountStatusVi } from '../lib/vi'

function fmtTime(iso) {
  if (!iso) return ''
  const norm = /[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z'
  const d = new Date(norm)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString([], { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function preview(message) {
  if (!message) return 'Chưa có tin nhắn'
  if (message.text) return message.text.replace(/\s+/g, ' ').trim()
  return message.media || 'Tin nhắn'
}

export default function InboxTab({ accounts, selected }) {
  const toast = useToast()
  const firstId = selected?.id || accounts.find((a) => a.status === 'connected')?.id || accounts[0]?.id || null
  const [accountId, setAccountId] = useState(firstId)
  const [dialogs, setDialogs] = useState([])
  const [peer, setPeer] = useState(null)
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const [queryDraft, setQueryDraft] = useState('')
  const dialogOffsetRef = useRef(0)
  const [hasMore, setHasMore] = useState(false)
  const [unreadTotal, setUnreadTotal] = useState(0)
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [newByAccount, setNewByAccount] = useState({})
  const seqRef = useRef(0)
  const listRef = useRef(null)

  const account = accounts.find((a) => a.id === accountId) || null

  useEffect(() => {
    if (selected?.id && !accountId) setAccountId(selected.id)
  }, [selected?.id, accountId])

  const loadDialogs = useCallback(async (silent = false, append = false) => {
    if (!accountId) return
    if (!silent) setLoading(true)
    try {
      const offset = append ? dialogOffsetRef.current : 0
      const r = await Endpoints.inboxDialogs(accountId, 60, unreadOnly, query, offset)
      const incoming = r?.dialogs || []
      setDialogs((old) => append ? [...old, ...incoming.filter((row) => !old.some((x) => x.peer.ref === row.peer.ref))] : incoming)
      dialogOffsetRef.current = Number(r?.next_offset || incoming.length || 0)
      setHasMore(!!r?.has_more)
      setUnreadTotal(Number(r?.unread_total || 0))
    } catch (e) {
      if (!silent) toast.error(e.message)
    } finally {
      if (!silent) setLoading(false)
    }
  }, [accountId, unreadOnly, query, toast])

  const loadHistory = useCallback(async (targetPeer = peer, silent = false) => {
    if (!accountId || !targetPeer?.ref) return
    try {
      const r = await Endpoints.inboxHistory(accountId, targetPeer.ref, 80)
      setPeer(r?.peer || targetPeer)
      setMessages(r?.messages || [])
    } catch (e) {
      if (!silent) toast.error(e.message)
    }
  }, [accountId, peer, toast])

  useEffect(() => {
    setPeer(null); setMessages([]); setDraft('')
    if (accountId) loadDialogs()
  }, [accountId, unreadOnly, loadDialogs])

  useEffect(() => {
    if (!accountId) return
    const id = setInterval(() => loadDialogs(true), 8000)
    return () => clearInterval(id)
  }, [accountId, loadDialogs])

  useEffect(() => {
    if (!peer?.ref || !accountId) return
    const id = setInterval(() => loadHistory(peer, true), 5000)
    return () => clearInterval(id)
  }, [peer?.ref, accountId, loadHistory])

  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const r = await Endpoints.inboxActivity(seqRef.current)
        if (!alive) return
        seqRef.current = Math.max(seqRef.current, Number(r?.latest_seq || 0))
        const events = r?.events || []
        if (events.length) {
          setNewByAccount((prev) => {
            const next = { ...prev }
            for (const event of events) next[event.account_id] = (next[event.account_id] || 0) + 1
            return next
          })
          if (events.some((event) => event.account_id === accountId)) {
            loadDialogs(true)
            if (peer?.ref && events.some((event) => event.account_id === accountId && String(event.peer_id) === String(peer.ref))) {
              loadHistory(peer, true)
            }
          }
        }
      } catch { /* transient polling failure */ }
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => { alive = false; clearInterval(id) }
  }, [accountId, peer?.ref, loadDialogs, loadHistory])

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  async function chooseAccount(id) {
    setAccountId(id)
    setNewByAccount((prev) => ({ ...prev, [id]: 0 }))
  }

  async function openDialog(dialog) {
    setPeer(dialog.peer)
    setMessages([])
    try {
      const r = await Endpoints.inboxHistory(accountId, dialog.peer.ref, 80)
      setPeer(r?.peer || dialog.peer)
      setMessages(r?.messages || [])
      if (dialog.unread_count > 0) {
        await Endpoints.inboxMarkRead(accountId, dialog.peer.ref)
        loadDialogs(true)
      }
    } catch (e) {
      toast.error(e.message)
    }
  }

  async function markAllRead() {
    if (!accountId) return
    try {
      const r = await Endpoints.inboxMarkAllRead(accountId)
      toast.success(`Đã đánh dấu ${r.dialogs || 0} hội thoại là đã đọc`)
      await loadDialogs(true)
    } catch (e) { toast.error(e.message) }
  }

  async function sendReply() {
    const text = draft.trim()
    if (!text || !peer?.ref || !accountId) return
    setSending(true)
    try {
      await Endpoints.inboxReply(accountId, peer.ref, text)
      setDraft('')
      await loadHistory(peer, true)
      loadDialogs(true)
    } catch (e) {
      toast.error(e.message)
    } finally {
      setSending(false)
    }
  }

  const filtered = dialogs


  function applySearch() {
    dialogOffsetRef.current = 0
    setQuery(queryDraft.trim())
  }

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[240px_360px_minmax(0,1fr)] gap-3 h-[calc(100vh-150px)] min-h-[560px]">
      <section className="nb-card p-3 overflow-auto">
        <div className="font-extrabold uppercase mb-2">Phiên Telegram</div>
        <div className="text-[11px] opacity-60 mb-3">Chọn session để kiểm tra hộp thư của tài khoản đó.</div>
        <div className="space-y-2">
          {accounts.map((a) => (
            <button key={a.id} onClick={() => chooseAccount(a.id)}
              className={'w-full text-left border-2 border-black dark:border-white p-2 ' + (a.id === accountId ? 'bg-brand-pri text-black' : 'bg-white dark:bg-zinc-900')}>
              <div className="flex items-center gap-2">
                <span className="font-bold truncate">{a.first_name || a.username || a.phone}</span>
                {!!newByAccount[a.id] && <span className="nb-badge bg-brand-err text-white ml-auto">+{newByAccount[a.id]}</span>}
              </div>
              <div className="text-[10px] opacity-60 truncate">{a.phone} · {accountStatusVi(a.status)}</div>
            </button>
          ))}
          {hasMore && <div className="p-2"><button className="nb-btn w-full !py-1 text-xs" disabled={loading} onClick={() => loadDialogs(false, true)}>Tải thêm hội thoại</button></div>}
        </div>
      </section>

      <section className="nb-card flex flex-col min-h-0">
        <div className="p-3 border-b-2 border-black dark:border-white">
          <div className="flex items-center gap-2 mb-2">
            <span className="font-extrabold uppercase">Hội thoại</span>
            <span className="nb-badge bg-brand-violet text-black ml-auto">{unreadTotal} chưa đọc</span>
          </div>
          <input className="nb-input !py-1 text-sm mb-2" placeholder="Tìm người gửi hoặc nội dung…" value={queryDraft} onChange={(e) => setQueryDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') applySearch() }} />
          <div className="flex items-center gap-2">
            <label className="text-xs flex items-center gap-1">
              <input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} /> Chỉ chưa đọc
            </label>
            <button className="nb-btn !py-1 !px-2 text-xs ml-auto" onClick={applySearch}>Tìm</button>
            <button className="nb-btn !py-1 !px-2 text-xs" onClick={markAllRead} disabled={!unreadTotal}>Đọc tất cả</button><button className="nb-btn !py-1 !px-2 text-xs" onClick={() => loadDialogs()} disabled={loading}>{loading ? '…' : 'Làm mới'}</button>
          </div>
        </div>
        <div className="flex-1 overflow-auto">
          {!account && <div className="p-4 text-xs opacity-60">Chưa có session.</div>}
          {account && account.status !== 'connected' && <div className="p-3 text-xs bg-brand-warn text-black">Session đang ở trạng thái <b>{accountStatusVi(account.status)}</b>.</div>}
          {account && filtered.length === 0 && <div className="p-4 text-xs opacity-60">Không có hội thoại phù hợp.</div>}
          {filtered.map((d) => (
            <button key={d.peer.ref} onClick={() => openDialog(d)}
              className={'w-full text-left p-3 border-b border-black/20 dark:border-white/20 hover:bg-zinc-100 dark:hover:bg-zinc-800 ' + (peer?.ref === d.peer.ref ? 'bg-brand-pri/30' : '')}>
              <div className="flex gap-2 items-center">
                <span className="font-bold truncate">{d.title}</span>
                {d.unread_count > 0 && <span className="nb-badge bg-brand-err text-white ml-auto">{d.unread_count}</span>}
              </div>
              <div className="text-[11px] truncate opacity-70">{preview(d.last_message)}</div>
              <div className="text-[10px] opacity-45 mt-1">{fmtTime(d.last_message?.date)}{d.archived ? ' · Lưu trữ' : ''}</div>
            </button>
          ))}
        </div>
      </section>

      <section className="nb-card flex flex-col min-h-0">
        <div className="p-3 border-b-2 border-black dark:border-white flex items-center gap-2">
          <span className="font-extrabold uppercase">Tin nhắn</span>
          {peer && <span className="font-bold truncate">{peer.title}</span>}
          {peer?.username && <span className="text-xs opacity-60">@{peer.username}</span>}
        </div>
        <div ref={listRef} className="flex-1 overflow-auto p-3 space-y-2 bg-zinc-50 dark:bg-zinc-950/40">
          {!peer && <div className="h-full flex items-center justify-center text-center text-xs opacity-50 px-6">Chọn một hội thoại ở cột bên trái để xem tin mới và trả lời.</div>}
          {peer && messages.length === 0 && <div className="h-full flex items-center justify-center text-xs opacity-50">Chưa có tin nhắn.</div>}
          {peer && messages.map((m) => (
            <div key={m.id} className={'flex ' + (m.out ? 'justify-end' : 'justify-start')}>
              <div className={'max-w-[82%] px-3 py-2 border-2 border-black dark:border-white text-sm break-words ' + (m.out ? 'bg-brand-pri text-black' : 'bg-white dark:bg-zinc-800')}>
                {m.text ? <div className="whitespace-pre-wrap">{m.text}</div> : <div className="italic opacity-70">{m.media || '[tin nhắn]'}</div>}
                <div className={'text-[9px] mt-1 text-right ' + (m.out ? 'text-black/50' : 'opacity-50')}>{fmtTime(m.date)}</div>
              </div>
            </div>
          ))}
        </div>
        {peer && (
          <div className="p-3 border-t-2 border-black dark:border-white flex gap-2">
            <textarea className="nb-input min-h-[54px] max-h-32 text-sm" value={draft} onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendReply() } }} placeholder="Nhập nội dung trả lời…" />
            <button className="nb-btn-pri px-4 shrink-0" disabled={sending || !draft.trim()} onClick={sendReply}>{sending ? '…' : 'Trả lời'}</button>
          </div>
        )}
      </section>
    </div>
  )
}
