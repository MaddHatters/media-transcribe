<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string; step: string }>()

const bgColor: Record<string, string> = {
  pending: 'bg-gray-300',
  queued: 'bg-blue-400',
  running: 'bg-yellow-400 animate-pulse',
  completed: 'bg-green-500',
  failed: 'bg-red-500',
  skipped: 'bg-gray-300',
}

const displayName = computed(() =>
  props.step.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
)

const tooltip = computed(() => `${displayName.value}: ${props.status}`)
</script>

<template>
  <span
    class="relative inline-flex items-center justify-center w-3 h-3 rounded-full"
    :class="bgColor[status] ?? 'bg-gray-300'"
    :title="tooltip"
  >
    <!-- Completed: checkmark overlay -->
    <svg v-if="status === 'completed'" class="w-2 h-2 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="4">
      <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
    </svg>
    <!-- Failed: X overlay -->
    <svg v-else-if="status === 'failed'" class="w-2 h-2 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="4">
      <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
    </svg>
    <!-- Skipped: diagonal line overlay -->
    <svg v-else-if="status === 'skipped'" class="absolute inset-0 w-3 h-3" viewBox="0 0 12 12">
      <line x1="2" y1="10" x2="10" y2="2" stroke="white" stroke-width="2" stroke-linecap="round" />
    </svg>
  </span>
</template>
