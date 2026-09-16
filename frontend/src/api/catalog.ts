import type { CatalogStats, PaginatedPosts, PostDetail } from '../types'
import { api } from './client'

export interface CatalogFilters {
  type?: string
  status?: string
  step?: string
  search?: string
  tag?: string
  source_id?: string
  sort?: string
  order?: 'asc' | 'desc'
  page?: number
  per_page?: number
}

export const catalogApi = {
  list(filters: CatalogFilters = {}) {
    const params = new URLSearchParams()
    for (const [k, v] of Object.entries(filters)) {
      if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
    }
    const qs = params.toString()
    return api.get<PaginatedPosts>(`/api/catalog${qs ? '?' + qs : ''}`)
  },
  get(postId: string) {
    return api.get<PostDetail>(`/api/catalog/${postId}`)
  },
  stats() {
    return api.get<CatalogStats>('/api/catalog/stats')
  },
  importCatalog(jsonPath?: string) {
    return api.post<{ imported: number }>('/api/catalog/import', { json_path: jsonPath ?? null })
  },
}
