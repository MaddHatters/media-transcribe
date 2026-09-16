<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ seconds: number | null }>()

const formatted = computed(() => {
  if (props.seconds === null || props.seconds === undefined) return '—'
  const s = Math.floor(props.seconds)
  if (s >= 3600) {
    const h = Math.floor(s / 3600)
    const m = Math.floor((s % 3600) / 60)
    return `${h}h ${m}m`
  }
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m}m ${sec}s`
})
</script>

<template>
  <span>{{ formatted }}</span>
</template>
