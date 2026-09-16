<script setup lang="ts">
import type { PostSummary } from '../../types'
import { useCatalogStore } from '../../stores/catalog'
import CatalogRow from './CatalogRow.vue'
import LoadingSpinner from '../shared/LoadingSpinner.vue'
import EmptyState from '../shared/EmptyState.vue'

const props = defineProps<{
  posts: PostSummary[]
  sortField: string
  sortOrder: 'asc' | 'desc'
}>()

const emit = defineEmits<{
  sort: [field: string, order: 'asc' | 'desc']
  select: [post: PostSummary]
}>()

const catalogStore = useCatalogStore()

interface Column {
  key: string
  label: string
  sortable: boolean
}

const columns: Column[] = [
  { key: 'title', label: 'Title', sortable: true },
  { key: 'post_type', label: 'Type', sortable: true },
  { key: 'published_at', label: 'Published', sortable: true },
  { key: 'overall_status', label: 'Status', sortable: true },
  { key: 'steps', label: 'Steps', sortable: false },
  { key: 'duration_seconds', label: 'Duration', sortable: true },
]

function toggleSort(field: string) {
  if (props.sortField === field) {
    emit('sort', field, props.sortOrder === 'asc' ? 'desc' : 'asc')
  } else {
    emit('sort', field, 'asc')
  }
}
</script>

<template>
  <div class="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
    <div v-if="catalogStore.loading" class="flex justify-center py-12">
      <LoadingSpinner />
    </div>
    <template v-else-if="posts.length === 0">
      <EmptyState message="No posts match your filters" />
    </template>
    <div v-else class="overflow-x-auto">
      <table class="w-full">
        <thead class="bg-gray-50 border-b border-gray-200">
          <tr>
            <th
              v-for="col in columns"
              :key="col.key"
              class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
              :class="{ 'cursor-pointer hover:text-gray-700': col.sortable }"
              @click="col.sortable && toggleSort(col.key)"
            >
              <span class="inline-flex items-center gap-1">
                {{ col.label }}
                <template v-if="col.sortable && sortField === col.key">
                  <svg v-if="sortOrder === 'asc'" class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5" />
                  </svg>
                  <svg v-else class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
                  </svg>
                </template>
              </span>
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          <CatalogRow
            v-for="post in posts"
            :key="post.post_id"
            :post="post"
            @click="emit('select', post)"
          />
        </tbody>
      </table>
    </div>
  </div>
</template>
