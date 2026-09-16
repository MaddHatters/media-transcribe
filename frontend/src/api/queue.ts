import type { QueueEntry } from '../types'
import { api } from './client'

export const queueApi = {
  list: () => api.get<QueueEntry[]>('/api/queue'),
  add: (postIds: string[], priority = 0) =>
    api.post<{ added: number }>('/api/queue', { post_ids: postIds, priority }),
  remove: (postId: string) => api.delete<{ removed: boolean }>(`/api/queue/${postId}`),
  updatePriority: (postId: string, priority: number) =>
    api.patch<{ ok: boolean }>(`/api/queue/${postId}`, { priority }),
  reorder: (postIds: string[]) =>
    api.post<{ ok: boolean }>('/api/queue/reorder', { post_ids: postIds }),
  start: () => api.post<Record<string, unknown>>('/api/queue/start'),
  pause: () => api.post<{ ok: boolean }>('/api/queue/pause'),
  clear: () => api.post<{ ok: boolean }>('/api/queue/clear'),
}
