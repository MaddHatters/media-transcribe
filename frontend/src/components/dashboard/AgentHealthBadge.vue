<script setup lang="ts">
import { computed } from 'vue'
import { useAgentStore } from '../../stores/agent'
import LoadingSpinner from '../shared/LoadingSpinner.vue'

const agentStore = useAgentStore()

const dotColor = computed(() => {
  if (!agentStore.health) return 'bg-red-500'
  if (!agentStore.health.healthy) return 'bg-red-500'
  if (!agentStore.health.obs_connected || !agentStore.health.chrome_available || !agentStore.health.disk_ok) {
    return 'bg-yellow-500'
  }
  return 'bg-green-500'
})

const statusLabel = computed(() => {
  if (!agentStore.health) return 'Unknown'
  if (!agentStore.health.healthy) return 'Unhealthy'
  if (dotColor.value === 'bg-yellow-500') return 'Degraded'
  return 'Healthy'
})

const relativeTime = computed(() => {
  if (!agentStore.lastChecked) return null
  const diff = Date.now() - new Date(agentStore.lastChecked).getTime()
  const secs = Math.floor(diff / 1000)
  if (secs < 5) return 'just now'
  if (secs < 60) return `${secs}s ago`
  return `${Math.floor(secs / 60)}m ago`
})

const indicators = computed(() => [
  {
    label: 'OBS',
    ok: agentStore.health?.obs_connected ?? false,
    text: agentStore.health?.obs_connected ? 'Connected' : 'Disconnected',
  },
  {
    label: 'Chrome',
    ok: agentStore.health?.chrome_available ?? false,
    text: agentStore.health?.chrome_available ? 'Available' : 'Unavailable',
  },
  {
    label: 'Disk',
    ok: agentStore.health?.disk_ok ?? false,
    text: agentStore.health?.disk_ok ? 'OK' : 'Low space',
  },
])
</script>

<template>
  <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
    <div class="flex items-center justify-between mb-4">
      <h3 class="text-sm font-semibold text-gray-900">Agent Status</h3>
      <div class="flex items-center gap-2">
        <span class="text-xs text-gray-500">{{ statusLabel }}</span>
        <span :class="[dotColor, 'h-2.5 w-2.5 rounded-full', dotColor === 'bg-green-500' ? 'animate-pulse' : '']" />
      </div>
    </div>

    <div v-if="!agentStore.health && agentStore.loading" class="flex justify-center py-4">
      <LoadingSpinner size="sm" />
      <span class="ml-2 text-sm text-gray-500">Connecting...</span>
    </div>

    <div v-else class="space-y-3">
      <div
        v-for="ind in indicators"
        :key="ind.label"
        class="flex items-center justify-between"
      >
        <span class="text-sm text-gray-600">{{ ind.label }}</span>
        <div class="flex items-center gap-1.5">
          <span :class="['text-xs', ind.ok ? 'text-green-600' : 'text-red-600']">{{ ind.text }}</span>
          <span :class="['h-1.5 w-1.5 rounded-full', ind.ok ? 'bg-green-500' : 'bg-red-500']" />
        </div>
      </div>

      <div v-if="agentStore.health?.error" class="mt-2 text-xs text-red-500 bg-red-50 rounded p-2">
        {{ agentStore.health.error }}
      </div>
    </div>

    <div v-if="relativeTime" class="mt-4 pt-3 border-t border-gray-100">
      <span class="text-xs text-gray-400">Updated {{ relativeTime }}</span>
    </div>
  </div>
</template>
