<script setup lang="ts">
import { computed } from 'vue'
import { useWebSocketStore } from '../../stores/websocket'
import type { WebSocketEvent } from '../../types'
import EmptyState from '../shared/EmptyState.vue'

const wsStore = useWebSocketStore()

const events = computed(() =>
  wsStore.recentEvents.filter(e => e.type !== 'ping').slice(0, 10)
)

function formatEvent(event: WebSocketEvent): { text: string; color: string; icon: 'check' | 'x' | 'arrow' | 'circle' } {
  const title = (event.data?.title as string) || (event.data?.post_id as string) || ''
  const step = (event.data?.step as string) || ''

  switch (event.type) {
    case 'step_completed':
      return { text: `${step} completed for ${title}`, color: 'text-green-600', icon: 'check' }
    case 'step_failed':
      return { text: `${step} failed for ${title}`, color: 'text-red-600', icon: 'x' }
    case 'step_started':
      return { text: `${step} started for ${title}`, color: 'text-blue-600', icon: 'arrow' }
    case 'pipeline_complete':
      return { text: 'Pipeline run completed', color: 'text-green-600', icon: 'check' }
    case 'discovery_complete':
      return { text: `Discovery found ${event.data?.new_posts ?? 0} new posts`, color: 'text-indigo-600', icon: 'circle' }
    case 'watcher_cycle':
      return { text: `Watcher cycle ${event.data?.cycle ?? ''} completed`, color: 'text-gray-600', icon: 'circle' }
    default:
      return { text: event.type, color: 'text-gray-600', icon: 'circle' }
  }
}

function relativeTime(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime()
  const secs = Math.floor(diff / 1000)
  if (secs < 5) return 'just now'
  if (secs < 60) return `${secs}s ago`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  return `${hrs}h ago`
}
</script>

<template>
  <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
    <div class="flex items-center gap-2 mb-4">
      <h3 class="text-sm font-semibold text-gray-900">Recent Activity</h3>
      <span
        :class="['h-2 w-2 rounded-full', wsStore.connected ? 'bg-green-500' : 'bg-gray-400']"
        :title="wsStore.connected ? 'Connected' : 'Disconnected'"
      />
    </div>

    <EmptyState v-if="events.length === 0" message="No recent activity" />

    <div v-else class="space-y-3">
      <div
        v-for="(event, i) in events"
        :key="i"
        class="flex items-start gap-3"
      >
        <div class="mt-0.5 shrink-0">
          <svg v-if="formatEvent(event).icon === 'check'" class="w-4 h-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75" />
          </svg>
          <svg v-else-if="formatEvent(event).icon === 'x'" class="w-4 h-4 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
          <svg v-else-if="formatEvent(event).icon === 'arrow'" class="w-4 h-4 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
          </svg>
          <svg v-else class="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="3" />
          </svg>
        </div>
        <div class="flex-1 min-w-0">
          <p :class="['text-sm truncate', formatEvent(event).color]">{{ formatEvent(event).text }}</p>
          <p class="text-xs text-gray-400">{{ relativeTime(event.timestamp) }}</p>
        </div>
      </div>
    </div>
  </div>
</template>
