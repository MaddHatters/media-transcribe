<script setup lang="ts">
import { computed, ref } from 'vue'
import { useIntervalFn } from '@vueuse/core'
import { useWatcherStore } from '../../stores/watcher'
import DateDisplay from '../shared/DateDisplay.vue'

const watcherStore = useWatcherStore()

const now = ref(Date.now())
useIntervalFn(() => { now.value = Date.now() }, 60_000)

const countdown = computed(() => {
  const s = watcherStore.status
  if (!s?.running || !s.next_run) return null
  const diff = new Date(s.next_run).getTime() - now.value
  if (diff <= 0) return 'imminent'
  const h = Math.floor(diff / 3_600_000)
  const m = Math.floor((diff % 3_600_000) / 60_000)
  if (h > 0) return `in ${h}h ${m}m`
  return `in ${m}m`
})
</script>

<template>
  <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
    <h3 class="text-sm font-semibold text-gray-900 mb-4">Watcher Status</h3>

    <div v-if="!watcherStore.status" class="text-sm text-gray-500">Loading...</div>
    <template v-else>
      <!-- Running indicator -->
      <div class="mb-4">
        <span
          class="inline-flex items-center px-3 py-1 rounded-full text-sm font-medium"
          :class="watcherStore.status.running
            ? 'bg-green-100 text-green-800'
            : 'bg-red-100 text-red-800'"
        >
          <span
            class="w-2 h-2 rounded-full mr-2"
            :class="watcherStore.status.running ? 'bg-green-500' : 'bg-red-500'"
          />
          {{ watcherStore.status.running ? 'Running' : 'Stopped' }}
        </span>
      </div>

      <!-- Stats grid -->
      <div class="grid grid-cols-2 gap-3 text-sm mb-4">
        <div v-if="watcherStore.status.running && watcherStore.status.pid">
          <span class="text-gray-500">PID</span>
          <p class="text-gray-900 font-mono">{{ watcherStore.status.pid }}</p>
        </div>
        <div>
          <span class="text-gray-500">Cycle</span>
          <p class="text-gray-900">{{ watcherStore.status.cycle }}</p>
        </div>
        <div>
          <span class="text-gray-500">Interval</span>
          <p class="text-gray-900">{{ watcherStore.status.interval_hours }}h</p>
        </div>
        <div>
          <span class="text-gray-500">Total Recorded</span>
          <p class="text-gray-900">{{ watcherStore.status.total_recorded }}</p>
        </div>
      </div>

      <!-- Timing -->
      <div class="text-sm space-y-1 border-t border-gray-100 pt-3">
        <div class="flex justify-between">
          <span class="text-gray-500">Last run</span>
          <DateDisplay :date="watcherStore.status.last_run" />
        </div>
        <div v-if="watcherStore.status.running && watcherStore.status.next_run" class="flex justify-between">
          <span class="text-gray-500">Next run</span>
          <span class="text-gray-900">{{ countdown }}</span>
        </div>
      </div>
    </template>
  </div>
</template>
