<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  page: number
  perPage: number
  total: number
}>()

const emit = defineEmits<{
  'update:page': [n: number]
  'update:perPage': [n: number]
}>()

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.perPage)))
const startItem = computed(() => props.total === 0 ? 0 : (props.page - 1) * props.perPage + 1)
const endItem = computed(() => Math.min(props.page * props.perPage, props.total))

const pageNumbers = computed(() => {
  const total = totalPages.value
  const current = props.page
  const pages: (number | '...')[] = []

  if (total <= 7) {
    for (let i = 1; i <= total; i++) pages.push(i)
    return pages
  }

  pages.push(1)
  if (current > 3) pages.push('...')

  const start = Math.max(2, current - 1)
  const end = Math.min(total - 1, current + 1)
  for (let i = start; i <= end; i++) pages.push(i)

  if (current < total - 2) pages.push('...')
  pages.push(total)

  return pages
})

function changePerPage(e: Event) {
  const val = parseInt((e.target as HTMLSelectElement).value)
  emit('update:perPage', val)
}
</script>

<template>
  <div class="flex items-center justify-between py-4">
    <span class="text-sm text-gray-600">
      Showing {{ startItem }}–{{ endItem }} of {{ total }} posts
    </span>

    <div class="flex items-center gap-1">
      <button
        v-for="p in pageNumbers"
        :key="typeof p === 'number' ? p : `ellipsis-${pageNumbers.indexOf(p)}`"
        :disabled="p === '...'"
        class="px-3 py-1 text-sm rounded-md"
        :class="p === page
          ? 'bg-indigo-600 text-white'
          : p === '...'
            ? 'text-gray-400 cursor-default'
            : 'bg-white border border-gray-300 hover:bg-gray-50 text-gray-700'"
        @click="typeof p === 'number' && emit('update:page', p)"
      >
        {{ p }}
      </button>
    </div>

    <div class="flex items-center gap-2">
      <label class="text-sm text-gray-600">Per page:</label>
      <select
        :value="perPage"
        class="rounded-md border border-gray-300 text-sm px-2 py-1"
        @change="changePerPage"
      >
        <option :value="25">25</option>
        <option :value="50">50</option>
        <option :value="100">100</option>
      </select>
    </div>
  </div>
</template>
