import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { CatalogStats, PostSummary, PostDetail } from '../types'
import { catalogApi, type CatalogFilters } from '../api/catalog'

export const useCatalogStore = defineStore('catalog', () => {
  const posts = ref<PostSummary[]>([])
  const total = ref(0)
  const page = ref(1)
  const perPage = ref(50)
  const stats = ref<CatalogStats | null>(null)
  const loading = ref(false)
  const currentPost = ref<PostDetail | null>(null)

  async function fetchPosts(filters: CatalogFilters = {}) {
    loading.value = true
    try {
      const data = await catalogApi.list({
        page: page.value,
        per_page: perPage.value,
        ...filters,
      })
      posts.value = data.posts
      total.value = data.total
      page.value = data.page
    } finally {
      loading.value = false
    }
  }

  async function fetchStats() {
    stats.value = await catalogApi.stats()
  }

  async function fetchPost(id: string) {
    currentPost.value = await catalogApi.get(id)
  }

  return { posts, total, page, perPage, stats, loading, currentPost, fetchPosts, fetchStats, fetchPost }
})
