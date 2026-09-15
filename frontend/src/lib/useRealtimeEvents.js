import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Endpoints } from './api'
import { streamSSE } from './realtime'

export const MAX_REALTIME_EVENTS = 1500
const HISTORY_PAGE = 200

function normalizeFilters(filters = {}) {
  return {
    feature: filters.feature || '',
    level: filters.level || '',
    job_id: filters.job_id || '',
    account_id: filters.account_id || '',
  }
}

function mergeUnique(current, incoming, prepend = false) {
  const map = new Map()
  const combined = prepend ? [...incoming, ...current] : [...current, ...incoming]
  for (const item of combined) {
    if (!item?.id) continue
    map.set(Number(item.id), item)
  }
  const rows = Array.from(map.values()).sort((a, b) => Number(a.id) - Number(b.id))
  return rows.slice(-MAX_REALTIME_EVENTS)
}

export function useRealtimeEvents({ filters = {}, enabled = true } = {}) {
  const normalized = useMemo(() => normalizeFilters(filters), [
    filters.feature, filters.level, filters.job_id, filters.account_id,
  ])
  const filterKey = JSON.stringify(normalized)
  const [events, setEvents] = useState([])
  const [connection, setConnection] = useState('idle')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [hasMore, setHasMore] = useState(false)
  const [lastHeartbeatAt, setLastHeartbeatAt] = useState(null)
  const cursorRef = useRef(0)
  const oldestRef = useRef(0)

  const queryFor = useCallback((extra = {}) => ({
    ...normalized,
    ...extra,
  }), [filterKey])

  const loadInitial = useCallback(async () => {
    if (!enabled) return
    setLoading(true)
    setError('')
    try {
      const result = await Endpoints.eventHistory(queryFor({ limit: HISTORY_PAGE }))
      const rows = [...(result?.items || [])].reverse()
      setEvents(rows.slice(-MAX_REALTIME_EVENTS))
      cursorRef.current = rows.length ? Math.max(...rows.map((x) => Number(x.id || 0))) : 0
      oldestRef.current = rows.length ? Math.min(...rows.map((x) => Number(x.id || 0))) : 0
      setHasMore((result?.items || []).length >= HISTORY_PAGE)
    } catch (e) {
      setError(e.message || 'Không tải được lịch sử realtime')
    } finally {
      setLoading(false)
    }
  }, [enabled, queryFor])

  const loadOlder = useCallback(async () => {
    const before = oldestRef.current
    if (!enabled || !before || loading) return
    setLoading(true)
    try {
      const result = await Endpoints.eventHistory(queryFor({ limit: HISTORY_PAGE, before_id: before }))
      const rows = [...(result?.items || [])].reverse()
      setEvents((current) => mergeUnique(current, rows, true))
      if (rows.length) oldestRef.current = Math.min(...rows.map((x) => Number(x.id || 0)))
      setHasMore((result?.items || []).length >= HISTORY_PAGE)
    } catch (e) {
      setError(e.message || 'Không tải được lịch sử cũ hơn')
    } finally {
      setLoading(false)
    }
  }, [enabled, loading, queryFor])

  const clearView = useCallback(() => {
    setEvents([])
    oldestRef.current = 0
  }, [])

  useEffect(() => {
    cursorRef.current = 0
    oldestRef.current = 0
    setEvents([])
    setConnection(enabled ? 'connecting' : 'idle')
    if (!enabled) return undefined

    let stopped = false
    let controller = null
    let retryMs = 1000
    let reconnectTimer = null

    async function bootstrapAndStream() {
      try {
        await loadInitial()
      } catch {}
      while (!stopped) {
        controller = new AbortController()
        setConnection(cursorRef.current ? 'reconnecting' : 'connecting')
        try {
          await streamSSE('/api/events/stream', queryFor({ after_id: cursorRef.current }), {
            lastEventId: cursorRef.current,
            signal: controller.signal,
            onHeartbeat: () => { retryMs = 1000; setLastHeartbeatAt(new Date().toISOString()); setConnection('connected'); setError('') },
            onEvent: (payload, meta) => {
              const id = Number(meta?.id || payload?.id || 0)
              if (id) cursorRef.current = Math.max(cursorRef.current, id)
              retryMs = 1000
              setConnection('connected')
              setError('')
              setEvents((current) => mergeUnique(current, [payload]))
              if (!oldestRef.current && id) oldestRef.current = id
            },
          })
          if (stopped) break
          throw new Error('Luồng realtime đã đóng')
        } catch (e) {
          if (stopped || controller.signal.aborted) break
          setConnection(navigator.onLine ? 'reconnecting' : 'offline')
          setError(e.message || 'Mất kết nối realtime')
          await new Promise((resolve) => {
            reconnectTimer = setTimeout(resolve, retryMs)
          })
          retryMs = Math.min(15000, Math.round(retryMs * 1.8))
        }
      }
    }

    bootstrapAndStream()
    return () => {
      stopped = true
      controller?.abort()
      if (reconnectTimer) clearTimeout(reconnectTimer)
    }
  }, [enabled, filterKey, loadInitial, queryFor])

  return {
    events,
    connection,
    loading,
    error,
    hasMore,
    lastHeartbeatAt,
    loadOlder,
    reload: loadInitial,
    clearView,
  }
}
