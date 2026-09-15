import { getAccessToken } from './supabase'

const BASE = ''  // proxied by vite

// listeners notified when any request returns 401
const _onUnauth = new Set()
export function onUnauthorized(cb) { _onUnauth.add(cb); return () => _onUnauth.delete(cb) }
export function notifyUnauthorized() { _onUnauth.forEach((fn) => { try { fn() } catch {} }) }

async function request(method, path, { json, form, query, silent } = {}) {
  let url = path
  if (query) {
    const q = new URLSearchParams(
      Object.entries(query).filter(([, v]) => v !== undefined && v !== null && v !== '')
    ).toString()
    if (q) url += '?' + q
  }
  const token = await getAccessToken()
  const opts = { method, headers: {}, credentials: 'include' }
  if (token) opts.headers.Authorization = `Bearer ${token}`
  if (json !== undefined) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(json)
  } else if (form) {
    opts.body = form
  }
  let r
  try {
    r = await fetch(BASE + url, opts)
  } catch (netErr) {
    // network/CORS/abort — surface a cleaner message
    const e = new Error('Không thể kết nối tới máy chủ')
    e.status = 0
    e.network = true
    throw e
  }
  let body = null
  try { body = await r.json() } catch { /* may not be json */ }
  if (r.status === 401 && !path.startsWith('/api/auth-app/')) {
    notifyUnauthorized()
  }
  if (!r.ok) {
    const msg = body?.detail || body?.message || `${r.status} ${r.statusText}`
    const err = new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
    err.status = r.status
    err.body = body
    throw err
  }
  return body
}

export const api = {
  get:  (p, query)        => request('GET',  p, { query }),
  post: (p, json)         => request('POST', p, { json }),
  put:  (p, json)         => request('PUT',  p, { json }),
  del:  (p)               => request('DELETE', p),
  patch: (p, json)         => request('PATCH', p, { json }),
  postForm: (p, form)     => request('POST', p, { form }),
}

// POST and consume a newline-delimited JSON (NDJSON) stream, calling onEvent(obj)
// for each line as it arrives. Shared by every live bulk task. `init` is passed
// straight to fetch() so callers can stream a JSON body OR a multipart FormData.
async function streamRequest(path, init, onEvent) {
  const token = await getAccessToken()
  const headers = { ...(init.headers || {}) }
  if (token) headers.Authorization = `Bearer ${token}`
  let r
  try {
    r = await fetch(BASE + path, { credentials: 'include', ...init, headers })
  } catch {
    const e = new Error('Không thể kết nối tới máy chủ'); e.status = 0; e.network = true; throw e
  }
  if (r.status === 401) notifyUnauthorized()
  if (!r.ok || !r.body) {
    let detail = `${r.status} ${r.statusText}`
    try { const b = await r.json(); detail = b?.detail || detail } catch { /* not json */ }
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    err.status = r.status
    throw err
  }
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      let nl
      while ((nl = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, nl).trim()
        buf = buf.slice(nl + 1)
        if (line) onEvent(JSON.parse(line))
      }
    }
    const last = buf.trim()
    if (last) onEvent(JSON.parse(last))
  } finally {
    try { reader.cancel() } catch { /* already closed */ }
  }
}

// Stream an NDJSON response from a JSON POST body.
export function streamNDJSON(path, body, onEvent) {
  return streamRequest(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }, onEvent)
}

// Stream an NDJSON response from a multipart/form-data POST (file uploads).
export function streamNDJSONForm(path, form, onEvent) {
  return streamRequest(path, { method: 'POST', body: form }, onEvent)
}


export async function downloadFile(path, filename) {
  const token = await getAccessToken()
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`
  let r
  try {
    r = await fetch(BASE + path, { method: 'GET', headers, credentials: 'include' })
  } catch {
    const e = new Error('Không thể kết nối tới máy chủ'); e.status = 0; throw e
  }
  if (r.status === 401) notifyUnauthorized()
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`
    try { const b = await r.json(); detail = b?.detail || detail } catch {}
    const e = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail)); e.status = r.status; throw e
  }
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a'); a.href = url; a.download = filename || 'download'
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url)
}

// Convenience endpoints
export const Endpoints = {
  health: () => api.get('/api/health'),
  systemStatus: () => api.get('/api/system/status'),
  stats: () => api.get('/api/stats'),
  accounts: () => api.get('/api/accounts'),
  account: (id) => api.get(`/api/accounts/${id}`),
  deleteAccount: (id) => api.del(`/api/accounts/${id}`),
  removeAllAccounts: (password) => api.post('/api/accounts/remove_all', { password }),

  // gone / banned account history
  goneAccounts: () => api.get('/api/gone_accounts'),
  clearGoneAccounts: () => api.del('/api/gone_accounts'),
  deleteGoneAccount: (id) => api.del(`/api/gone_accounts/${id}`),

  sendCode: (phone) => api.post('/api/auth/send_code', { phone }),
  signIn: (phone, code) => api.post('/api/auth/sign_in', { phone, code }),
  signIn2fa: (phone, password) => api.post('/api/auth/sign_in_2fa', { phone, code: '', password }),
  authCancel: (phone) => api.post('/api/auth/cancel', { phone }),
  importSessions: (files) => {
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    return api.postForm('/api/auth/import_sessions', fd)
  },
  syncSessionsFolder: () => api.post('/api/auth/sync_sessions_folder'),

  qrStart:    () => api.post('/api/auth/qr/start'),
  qrRecreate: (qr_id) => api.post('/api/auth/qr/recreate', { qr_id }),
  qrPoll:     (qr_id) => api.post('/api/auth/qr/poll', { qr_id }),
  qrSignIn2fa:(qr_id, password) => api.post('/api/auth/qr/sign_in_2fa', { qr_id, password }),
  qrCancel:   (qr_id) => api.post('/api/auth/qr/cancel', { qr_id }),

  updateProfile: (id, payload) => api.put(`/api/accounts/${id}/profile`, payload),
  checkUsername: (id, username) => api.get(`/api/accounts/${id}/profile/check_username`, { username }),
  updateUsername: (id, username) => api.put(`/api/accounts/${id}/profile/username`, { username }),
  photoUrl: (id) => api.get(`/api/accounts/${id}/profile/photo_url`),
  uploadPhoto: (id, file) => {
    const fd = new FormData(); fd.append('file', file)
    return api.postForm(`/api/accounts/${id}/profile/photo`, fd)
  },

  // bulk profile/photo stream live progress (NDJSON), same as the other bulk tasks
  bulkProfile: (payload, onEvent) => streamNDJSON('/api/bulk/profile', payload, onEvent),
  bulkPhoto: (ids, files, onEvent) => {
    const fd = new FormData()
    fd.append('account_ids', ids.join(','))
    for (const f of files) fd.append('files', f)
    return streamNDJSONForm('/api/bulk/photo', fd, onEvent)
  },

  securityMessages: (accountId, onlyUnread) =>
    api.get('/api/security/messages', { account_id: accountId, only_unread: onlyUnread }),
  markRead: (id) => api.post(`/api/security/messages/${id}/read`),
  markAllRead: (accountId) => api.post('/api/security/messages/mark_all_read' + (accountId ? `?account_id=${accountId}` : '')),
  backfillSecurity: (accountId, limit = 50) => api.post(`/api/security/messages/${accountId}/backfill?limit=${limit}`),
  tgSessions: (id) => api.get(`/api/security/sessions/${id}`),
  terminateSession: (id, hash) => api.del(`/api/security/sessions/${id}/${hash}`),
  terminateOthers: (id) => api.post(`/api/security/sessions/${id}/terminate_others`),
  terminateOthersAll: (onEvent) => streamNDJSON('/api/security/sessions/terminate_others_all', {}, onEvent),

  // bulk 2FA: how many current passwords we already remember from login, and the
  // streaming change run (tries remembered pw first, then the bank; ≤5 per account)
  twofaKnown: () => api.get('/api/security/twofa_known'),
  bulk2fa: (payload, onEvent) => streamNDJSON('/api/security/bulk_2fa', payload, onEvent),

  joinGroup: (id, target) => api.post(`/api/groups/${id}/join`, { target }),
  bulkJoin: (ids, target, onEvent) => streamNDJSON('/api/groups/bulk_join', { account_ids: ids, target }, onEvent),
  listGroups: (id) => api.get(`/api/groups/${id}/list`),
  leaveGroup: (id, chat_id) => api.post(`/api/groups/${id}/leave`, { chat_id }),
  bulkLeave: (ids, chat_id, onEvent) => streamNDJSON('/api/groups/bulk_leave', { account_ids: ids, chat_id }, onEvent),
  // leave ONE target (by @username / invite link) from selected accounts that are members
  bulkLeaveTarget: (ids, target, onEvent) => streamNDJSON('/api/groups/bulk_leave_target', { account_ids: ids, target }, onEvent),
  // leave EVERY group/channel each selected account is in
  bulkLeaveAll: (ids, onEvent) => streamNDJSON('/api/groups/bulk_leave_all', { account_ids: ids, confirm: true }, onEvent),
  // delete every message each selected account sent across ALL its groups/channels
  bulkDeleteMyMessages: (ids, max_scan, onEvent) =>
    streamNDJSON('/api/groups/bulk_delete_my_messages', { account_ids: ids, max_scan, confirm: true }, onEvent),
  countMyMessages: (id, chat_id, max_scan = 1000) =>
    api.get(`/api/groups/${id}/my_messages_count`, { chat_id, max_scan }),
  deleteMyMessages: (id, chat_id, max_scan = 2000) =>
    api.post(`/api/groups/${id}/delete_my_messages?chat_id=${chat_id}&max_scan=${max_scan}`),

  sendMessage: (id, target, text) => api.post(`/api/messaging/${id}/send`, { target, text }),
  bulkSend: (ids, target, text, onEvent) => streamNDJSON('/api/messaging/bulk_send', { account_ids: ids, target, text }, onEvent),
  multiSend: (ids, targets, text, onEvent) => streamNDJSON('/api/messaging/multi_send', { account_ids: ids, targets, text }, onEvent),
  previewMessageTargets: (file) => { const fd = new FormData(); fd.append('file', file); return api.postForm('/api/messaging/import_targets/preview', fd) },
  importMessageTargets: (file, selectedColumns = null, hasHeader = null) => {
    const fd = new FormData(); fd.append('file', file)
    if (selectedColumns?.length) fd.append('selected_columns', selectedColumns.join(','))
    if (hasHeader !== null && hasHeader !== undefined) fd.append('has_header', String(!!hasHeader))
    return api.postForm('/api/messaging/import_targets', fd)
  },
  // wipe the ENTIRE chat with one user (by @username / t.me link) from selected
  // accounts: clears history for both sides (revoke) and removes the dialog
  bulkWipeChat: (ids, target, onEvent) => streamNDJSON('/api/messaging/bulk_wipe_chat', { account_ids: ids, target, confirm: true }, onEvent),

  // Telegram-like chat panel: open by @username / t.me link (referral links
  // like t.me/Bot?start=CODE fire the bot /start), poll history, send.
  openChat: (id, input, limit = 40) => api.post(`/api/messaging/${id}/open`, { input, limit }),
  chatHistory: (id, peer, limit = 40) => api.get(`/api/messaging/${id}/history`, { peer, limit }),
  chatSend: (id, peer, text) => api.post(`/api/messaging/${id}/chat_send`, { peer, text }),

  // Inbox: live Telegram dialogs for each connected session. Message bodies stay on Telegram.
  inboxActivity: (sinceSeq = 0) => api.get('/api/inbox/activity', { since_seq: sinceSeq }),
  inboxDialogs: (id, limit = 60, unreadOnly = false, q = '', offset = 0) => api.get(`/api/inbox/${id}/dialogs`, { limit, unread_only: unreadOnly, q, offset }),
  inboxHistory: (id, peer, limit = 60) => api.get(`/api/inbox/${id}/history`, { peer, limit }),
  inboxMarkRead: (id, peer) => api.post(`/api/inbox/${id}/read`, { peer }),
  inboxMarkAllRead: (id) => api.post(`/api/inbox/${id}/read-all`),
  inboxReply: (id, peer, text) => api.post(`/api/inbox/${id}/reply`, { peer, text }),
  targetCheck: (target) => api.post('/api/messaging/target_check', { target }),
  targetChecks: (limit = 30) => api.get('/api/messaging/target_checks', { limit }),
  targetCheckDetail: (id) => api.get(`/api/messaging/target_checks/${id}`),
  previewPhoneChecks: (phones, phone_region = 'VN') => api.post('/api/phone-checks/preview', { phones, phone_region }),
  importPhoneChecks: (file, phone_region = 'VN') => { const fd = new FormData(); fd.append('file', file); fd.append('phone_region', phone_region); return api.postForm('/api/phone-checks/import', fd) },
  createPhoneCheckJob: (payload) => api.post('/api/phone-checks/jobs', payload),
  phoneCheckJobs: (limit = 50) => api.get('/api/phone-checks/jobs', { limit }),
  phoneCheckJob: (id, params = {}) => api.get(`/api/phone-checks/jobs/${id}`, params),
  pausePhoneCheckJob: (id) => api.post(`/api/phone-checks/jobs/${id}/pause`),
  resumePhoneCheckJob: (id) => api.post(`/api/phone-checks/jobs/${id}/resume`),
  cancelPhoneCheckJob: (id) => api.post(`/api/phone-checks/jobs/${id}/cancel`),
  rebalancePhoneCheckJob: (id) => api.post(`/api/phone-checks/jobs/${id}/rebalance`),
  downloadPhoneCheckExport: (id, kind, query = '') => downloadFile(`/api/phone-checks/jobs/${id}/export.${kind}${query ? `?${query}` : ''}`, `phone-check-${id}.${kind}`),
  proxies: () => api.get('/api/proxies'),
  saveProxy: (id, payload) => api.put(`/api/proxies/${id}`, payload),
  deleteProxy: (id) => api.del(`/api/proxies/${id}`),
  testProxy: (id) => api.post(`/api/proxies/${id}/test`),
  testProxyConfig: (id, payload) => api.post(`/api/proxies/${id}/test-config`, payload),
  testFallbackProxy: (id) => api.post(`/api/proxies/${id}/test-fallback`),
  switchProxy: (id, slot) => api.post(`/api/proxies/${id}/switch`, { slot }),
  applyProxy: (id) => api.post(`/api/proxies/${id}/apply`),
  // which reactions this post's chat actually allows (standard + custom emoji)
  allowedReactions: (post_link, account_id) => api.post('/api/messaging/allowed_reactions', { post_link, account_id }),
  // reactions: [{ emoji, account_ids, custom_emoji_id? }]
  react: (post_link, reactions, onEvent) => streamNDJSON('/api/messaging/react', { post_link, reactions }, onEvent),
  view: (ids, post_link, onEvent) => streamNDJSON('/api/messaging/view', { account_ids: ids, post_link }, onEvent),

  audit: (limit = 100, action, account_id) => api.get('/api/audit', { limit, action, account_id }),
  eventHistory: (params = {}) => api.get('/api/events/history', params),

  jobs: (limit = 50) => api.get('/api/jobs', { limit }),
  job: (id) => api.get(`/api/jobs/${id}`),
  pauseJob: (id) => api.post(`/api/jobs/${id}/pause`),
  resumeJob: (id) => api.post(`/api/jobs/${id}/resume`),
  cancelJob: (id) => api.post(`/api/jobs/${id}/cancel`),
  retryJob: (id, onEvent) => streamNDJSON(`/api/jobs/${id}/retry`, {}, onEvent),
  retryMessageJob: (id, text, onEvent) => streamNDJSON(`/api/jobs/${id}/retry-message`, { text }, onEvent),
  downloadJobExport: (id, kind) => downloadFile(`/api/jobs/${id}/export.${kind}`, `job-${id}.${kind}`),

  getSettings: () => api.get('/api/settings'),
  putSettings: (s) => api.put('/api/settings', s),
  exportJson: () => api.get('/api/settings/export'),

  // Supabase identity / admin
  bootstrapStatus: () => api.get('/api/auth-app/bootstrap/status'),
  bootstrapAdmin: (username, password) => api.post('/api/auth-app/bootstrap', { username, password }),
  me: () => api.get('/api/auth-app/me'),
  logout: () => api.post('/api/auth-app/logout'),
  adminSummary: () => api.get('/api/admin/summary'),
  adminDashboard: () => api.get('/api/admin/dashboard'),
  adminUsers: () => api.get('/api/admin/users'),
  adminUserOverview: (id) => api.get(`/api/admin/users/${id}/overview`),
  adminCreateUser: (payload) => api.post('/api/admin/users', payload),
  adminUpdateUser: (id, payload) => api.patch(`/api/admin/users/${id}`, payload),
  adminForceLogout: (id) => api.post(`/api/admin/users/${id}/force-logout`),
  adminDeleteUser: (id) => api.del(`/api/admin/users/${id}`),
  adminPurgeUser: (id, confirm_username) => api.post(`/api/admin/users/${id}/purge`, { confirm_username }),
  adminAudit: (params = {}) => api.get('/api/admin/audit', params),
  adminJobs: (params = {}) => api.get('/api/admin/jobs', params),
  adminCancelJob: (id) => api.post(`/api/admin/jobs/${id}/cancel`),
  adminRetryJob: (id, onEvent) => streamNDJSON(`/api/admin/jobs/${id}/retry`, {}, onEvent),
  adminHealth: () => api.get('/api/admin/health'),
  adminQuotaDefaults: () => api.get('/api/admin/quota-defaults'),
}
