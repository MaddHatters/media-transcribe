import type { DiscoveryRunResponse, PostSummary } from '../types'
import { api } from './client'

export const discoveryApi = {
  trigger: (fullCatalog = false, force = false) =>
    api.post<DiscoveryRunResponse>('/api/discovery/trigger', { full_catalog: fullCatalog, force }),
  history: () => api.get<DiscoveryRunResponse[]>('/api/discovery/history'),
  newPosts: () => api.get<PostSummary[]>('/api/discovery/new'),
}
