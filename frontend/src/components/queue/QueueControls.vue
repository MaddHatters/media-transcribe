<script setup lang="ts">
import { computed } from 'vue'
import { useQueueStore } from '../../stores/queue'
import { useToastStore } from '../../stores/toast'
import LoadingSpinner from '../shared/LoadingSpinner.vue'

const queueStore = useQueueStore()
const toastStore = useToastStore()

const hasEntries = computed(() => queueStore.entries.length > 0)
const hasCompleted = computed(() => queueStore.entries.some(e => e.status === 'done' || e.status === 'cancelled'))
const processingCount = computed(() => queueStore.entries.filter(e => e.status === 'processing').length)
const totalCount = computed(() => queueStore.entries.length)

const statusText = computed(() => {
  if (queueStore.processing) return `Processing (${processingCount.value}/${totalCount.value})`
  return 'Idle'
})

const statusDotColor = computed(() => {
  if (queueStore.processing) return 'bg-blue-500 animate-pulse'
  return 'bg-gray-400'
})

async function onStart() {
  try {
    await queueStore.startQueue()
    toastStore.add('success', 'Pipeline started')
  } catch {
    toastStore.add('error', 'Failed to start pipeline')
  }
}

async function onPause() {
  try {
    await queueStore.pauseQueue()
    toastStore.add('info', 'Pipeline paused')
  } catch {
    toastStore.add('error', 'Failed to pause pipeline')
  }
}

async function onClear() {
  try {
    await queueStore.clearCompleted()
    toastStore.add('success', 'Cleared completed entries')
  } catch {
    toastStore.add('error', 'Failed to clear completed')
  }
}
</script>

<template>
  <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-5 mb-4">
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button
          v-if="!queueStore.processing"
          :disabled="!hasEntries"
          class="bg-green-600 hover:bg-green-700 text-white text-sm font-medium px-4 py-2 rounded-md disabled:opacity-50 disabled:cursor-not-allowed"
          @click="onStart"
        >
          Start Pipeline
        </button>
        <template v-else>
          <button class="bg-green-600 text-white text-sm font-medium px-4 py-2 rounded-md opacity-75 cursor-wait flex items-center gap-2" disabled>
            <LoadingSpinner size="sm" />
            Processing...
          </button>
          <button
            class="bg-yellow-500 hover:bg-yellow-600 text-white text-sm font-medium px-4 py-2 rounded-md"
            @click="onPause"
          >
            Pause
          </button>
        </template>
        <button
          :disabled="!hasCompleted"
          class="bg-white border border-gray-300 text-gray-700 text-sm font-medium px-4 py-2 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          @click="onClear"
        >
          Clear Completed
        </button>
      </div>

      <div class="flex items-center gap-2">
        <span class="h-2 w-2 rounded-full" :class="statusDotColor" />
        <span class="text-sm text-gray-600">{{ statusText }}</span>
      </div>
    </div>
  </div>
</template>
