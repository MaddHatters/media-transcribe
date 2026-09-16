<script setup lang="ts">
defineProps<{ status: string }>()

const colorMap: Record<string, string> = {
  completed: 'bg-green-100 text-green-800',
  in_progress: 'bg-blue-100 text-blue-800',
  running: 'bg-blue-100 text-blue-800',
  failed: 'bg-red-100 text-red-800',
  pending: 'bg-gray-100 text-gray-800',
  discovered: 'bg-gray-100 text-gray-800',
  queued: 'bg-yellow-100 text-yellow-800',
  skipped: 'bg-gray-100 text-gray-500',
  partial: 'bg-amber-100 text-amber-800',
}
</script>

<template>
  <span
    class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium"
    :class="colorMap[status] ?? 'bg-gray-100 text-gray-800'"
  >
    {{ status }}
  </span>
</template>
