<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ date: string | null; relative?: boolean }>(), {
  relative: true,
})

const formatted = computed(() => {
  if (!props.date) return '—'
  const d = new Date(props.date)
  if (!props.relative) {
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }
  const diff = Date.now() - d.getTime()
  const secs = Math.floor(diff / 1000)
  if (secs < 5) return 'just now'
  if (secs < 60) return `${secs}s ago`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 30) return `${days} day${days > 1 ? 's' : ''} ago`
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
})
</script>

<template>
  <span>{{ formatted }}</span>
</template>
