import { getAccessToken } from './supabase'
import { notifyUnauthorized } from './api'

function buildUrl(path, query = {}) {
  const params = new URLSearchParams(
    Object.entries(query).filter(([, value]) => value !== undefined && value !== null && value !== '')
  )
  return params.size ? `${path}?${params.toString()}` : path
}

function parseBlock(block) {
  const lines = block.split(/\r?\n/)
  let id = null
  let event = 'message'
  const data = []
  for (const line of lines) {
    if (!line || line.startsWith(':')) continue
    const idx = line.indexOf(':')
    const field = idx >= 0 ? line.slice(0, idx) : line
    const value = idx >= 0 ? line.slice(idx + 1).replace(/^ /, '') : ''
    if (field === 'id') id = value
    else if (field === 'event') event = value
    else if (field === 'data') data.push(value)
  }
  if (!data.length) return null
  return { id, event, data: data.join('\n') }
}

export async function streamSSE(path, query, {
  lastEventId = 0,
  signal,
  onEvent,
  onHeartbeat,
} = {}) {
  const token = await getAccessToken()
  const headers = { Accept: 'text/event-stream' }
  if (token) headers.Authorization = `Bearer ${token}`
  if (lastEventId) headers['Last-Event-ID'] = String(lastEventId)

  let response
  try {
    response = await fetch(buildUrl(path, query), {
      method: 'GET',
      headers,
      credentials: 'include',
      cache: 'no-store',
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    const wrapped = new Error('Mất kết nối tới luồng realtime')
    wrapped.network = true
    wrapped.status = 0
    throw wrapped
  }

  if (response.status === 401) notifyUnauthorized()
  if (!response.ok || !response.body) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      detail = body?.detail || body?.message || detail
    } catch {}
    const error = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    error.status = response.status
    throw error
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let boundary
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        if (block.startsWith(':')) {
          onHeartbeat?.(block.slice(1).trim())
          continue
        }
        const parsed = parseBlock(block)
        if (!parsed) continue
        let payload = parsed.data
        try { payload = JSON.parse(parsed.data) } catch {}
        onEvent?.(payload, {
          id: parsed.id ? Number(parsed.id) : null,
          event: parsed.event,
        })
      }
    }
  } finally {
    try { await reader.cancel() } catch {}
  }
}

export const realtimeConnectionLabels = {
  idle: 'Chưa kết nối',
  connecting: 'Đang kết nối',
  connected: 'Đã kết nối',
  reconnecting: 'Đang kết nối lại',
  offline: 'Mất kết nối',
}
