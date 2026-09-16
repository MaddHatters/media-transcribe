<script setup lang="ts">
import { useCatalogStore } from '../../stores/catalog'
import LoadingSpinner from '../shared/LoadingSpinner.vue'

const catalogStore = useCatalogStore()

const cards = [
  { label: 'Total Posts', key: 'total', color: 'text-blue-600', bg: 'bg-blue-50' },
  { label: 'Videos', key: 'videos', color: 'text-indigo-600', bg: 'bg-indigo-50' },
  { label: 'Completed', key: 'completed', color: 'text-green-600', bg: 'bg-green-50' },
  { label: 'Pending', key: 'pending', color: 'text-amber-500', bg: 'bg-amber-50' },
  { label: 'Failed', key: 'failed', color: 'text-red-600', bg: 'bg-red-50' },
] as const

function getValue(key: string): number {
  if (!catalogStore.stats) return 0
  if (key === 'total') return catalogStore.stats.total_posts
  if (key === 'videos') return catalogStore.stats.video_posts
  if (key === 'completed') return catalogStore.stats.by_status?.completed ?? 0
  if (key === 'pending') return catalogStore.stats.by_status?.discovered ?? 0
  if (key === 'failed') return catalogStore.stats.by_status?.failed ?? 0
  return 0
}
</script>

<template>
  <div v-if="!catalogStore.stats" class="flex justify-center py-8">
    <LoadingSpinner />
  </div>
  <div v-else class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
    <div
      v-for="card in cards"
      :key="card.key"
      class="bg-white rounded-lg shadow-sm border border-gray-200 p-5"
    >
      <div class="flex items-center gap-2 mb-2">
        <div :class="[card.bg, 'rounded-md p-1.5']">
          <svg v-if="card.key === 'total'" :class="['w-4 h-4', card.color]" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
          </svg>
          <svg v-else-if="card.key === 'videos'" :class="['w-4 h-4', card.color]" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M15.91 11.672a.375.375 0 010 .656l-5.603 3.113a.375.375 0 01-.557-.328V8.887c0-.286.307-.466.557-.327l5.603 3.112z" />
          </svg>
          <svg v-else-if="card.key === 'completed'" :class="['w-4 h-4', card.color]" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <svg v-else-if="card.key === 'pending'" :class="['w-4 h-4', card.color]" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <svg v-else-if="card.key === 'failed'" :class="['w-4 h-4', card.color]" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
        </div>
        <span class="text-sm text-gray-500">{{ card.label }}</span>
      </div>
      <div :class="['text-3xl font-bold', card.color]">{{ getValue(card.key) }}</div>
    </div>
  </div>
</template>
