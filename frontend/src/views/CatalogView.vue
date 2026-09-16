<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { useCatalogStore } from '../stores/catalog'
import { useQueueStore } from '../stores/queue'
import { useToastStore } from '../stores/toast'
import type { CatalogFilters } from '../api/catalog'
import type { PostSummary } from '../types'
import FilterBar from '../components/catalog/FilterBar.vue'
import CatalogTable from '../components/catalog/CatalogTable.vue'
import PaginationBar from '../components/catalog/PaginationBar.vue'
import PostDetailModal from '../components/catalog/PostDetailModal.vue'

const catalogStore = useCatalogStore()
const queueStore = useQueueStore()
const toastStore = useToastStore()

const filters = ref<CatalogFilters>({})
const sortField = ref('published_at')
const sortOrder = ref<'asc' | 'desc'>('desc')
const selectedPostId = ref<string | null>(null)
const modalOpen = ref(false)

function fetchData() {
  catalogStore.fetchPosts({
    ...filters.value,
    sort: sortField.value,
    order: sortOrder.value,
  })
}

watch([filters, sortField, sortOrder], fetchData)

watch(() => catalogStore.page, fetchData)
watch(() => catalogStore.perPage, fetchData)

onMounted(() => {
  fetchData()
  catalogStore.fetchStats()
})

function onFilter(f: CatalogFilters) {
  catalogStore.page = 1
  filters.value = f
}

function onSort(field: string, order: 'asc' | 'desc') {
  sortField.value = field
  sortOrder.value = order
}

function onSelect(post: PostSummary) {
  selectedPostId.value = post.post_id
  modalOpen.value = true
}

function onPageChange(p: number) {
  catalogStore.page = p
}

function onPerPageChange(pp: number) {
  catalogStore.perPage = pp
  catalogStore.page = 1
}

async function onAddToQueue(postId: string) {
  try {
    await queueStore.addToQueue([postId])
    toastStore.add('success', 'Added to queue')
    modalOpen.value = false
  } catch {
    toastStore.add('error', 'Failed to add to queue')
  }
}
</script>

<template>
  <div>
    <h2 class="text-2xl font-semibold text-gray-900 mb-6">Catalog</h2>
    <FilterBar @update:filters="onFilter" />
    <CatalogTable
      :posts="catalogStore.posts"
      :sort-field="sortField"
      :sort-order="sortOrder"
      @sort="onSort"
      @select="onSelect"
    />
    <PaginationBar
      :page="catalogStore.page"
      :per-page="catalogStore.perPage"
      :total="catalogStore.total"
      @update:page="onPageChange"
      @update:per-page="onPerPageChange"
    />
    <PostDetailModal
      :post-id="selectedPostId"
      :open="modalOpen"
      @close="modalOpen = false"
      @add-to-queue="onAddToQueue"
    />
  </div>
</template>
