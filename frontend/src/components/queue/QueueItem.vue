<script setup lang="ts">
import type { QueueEntry } from '../../types'
import StatusBadge from '../shared/StatusBadge.vue'

defineProps<{ entry: QueueEntry }>()
defineEmits<{ remove: [postId: string] }>()

const borderColors: Record<string, string> = {
  processing: 'border-l-4 border-l-blue-500 bg-blue-50/50',
  done: 'border-l-4 border-l-green-500 opacity-75',
  cancelled: 'border-l-4 border-l-gray-300',
}
</script>

<template>
  <div
    class="bg-white rounded-lg shadow-sm border border-gray-200 px-4 py-3 flex items-center gap-3"
    :class="borderColors[entry.status] ?? ''"
  >
    <!-- Drag handle -->
    <div class="drag-handle cursor-grab text-gray-300 hover:text-gray-500 shrink-0">
      <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
        <path d="M7 2a2 2 0 10.001 4.001A2 2 0 007 2zm0 6a2 2 0 10.001 4.001A2 2 0 007 8zm0 6a2 2 0 10.001 4.001A2 2 0 007 14zm6-8a2 2 0 10-.001-4.001A2 2 0 0013 6zm0 2a2 2 0 10.001 4.001A2 2 0 0013 8zm0 6a2 2 0 10.001 4.001A2 2 0 0013 14z" />
      </svg>
    </div>

    <!-- Title -->
    <span class="flex-1 text-sm truncate" :class="{ 'line-through text-gray-400': entry.status === 'cancelled' }">
      {{ entry.title }}
    </span>

    <!-- Priority badge -->
    <span
      v-if="entry.priority > 0"
      class="bg-indigo-100 text-indigo-700 text-xs font-medium px-2 py-0.5 rounded-full shrink-0"
    >
      P{{ entry.priority }}
    </span>

    <!-- Status -->
    <StatusBadge :status="entry.status" />

    <!-- Remove button -->
    <button
      class="text-gray-400 hover:text-red-500 shrink-0"
      @click.stop="$emit('remove', entry.post_id)"
    >
      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
      </svg>
    </button>
  </div>
</template>
