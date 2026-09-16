import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { WebSocketEvent } from '../types'

export const useWebSocketStore = defineStore('websocket', () => {
  const connected = ref(false)
  const recentEvents = ref<WebSocketEvent[]>([])
  const maxEvents = 50
  let ws: WebSocket | null = null
  let reconnectDelay = 1000
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null

  function getWsUrl(): string {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${location.host}/ws/events`
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return

    ws = new WebSocket(getWsUrl())

    ws.onopen = () => {
      connected.value = true
      reconnectDelay = 1000
    }

    ws.onmessage = (event) => {
      const data: WebSocketEvent = JSON.parse(event.data)
      if (data.type === 'ping') return
      recentEvents.value.unshift(data)
      if (recentEvents.value.length > maxEvents) {
        recentEvents.value = recentEvents.value.slice(0, maxEvents)
      }

      dispatchEvent(data)
    }

    ws.onclose = () => {
      connected.value = false
      scheduleReconnect()
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  async function dispatchEvent(data: WebSocketEvent) {
    const { useCatalogStore } = await import('../stores/catalog')
    const { useQueueStore } = await import('../stores/queue')
    const { useWatcherStore } = await import('../stores/watcher')
    const { useToastStore } = await import('../stores/toast')

    const catalog = useCatalogStore()
    const queue = useQueueStore()
    const watcher = useWatcherStore()
    const toast = useToastStore()

    switch (data.type) {
      case 'step_started':
      case 'step_completed':
      case 'step_failed':
        catalog.fetchPosts()
        if (data.type === 'step_failed') {
          toast.add('error', `Step "${data.data.step}" failed for "${data.data.title || data.data.post_id}"`)
        }
        if (data.type === 'step_completed') {
          toast.add('success', `Step "${data.data.step}" completed`)
        }
        break
      case 'queue_update':
        queue.fetchQueue()
        break
      case 'watcher_cycle':
        watcher.fetchStatus()
        watcher.fetchDiscoveryHistory()
        toast.add('info', `Watcher cycle ${data.data.cycle ?? ''} completed`)
        break
      case 'discovery_complete':
        watcher.fetchNewPosts()
        watcher.fetchDiscoveryHistory()
        catalog.fetchStats()
        toast.add('info', `Discovery found ${data.data.new_posts ?? 0} new posts`)
        break
      case 'pipeline_complete':
        catalog.fetchStats()
        queue.fetchQueue()
        toast.add('success', 'Pipeline run completed')
        break
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) return
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      reconnectDelay = Math.min(reconnectDelay * 2, 30_000)
      connect()
    }, reconnectDelay)
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    ws?.close()
    ws = null
    connected.value = false
  }

  return { connected, recentEvents, connect, disconnect }
})
