import type { WatcherStatus } from '../types'
import { api } from './client'

export const watcherApi = {
  status: () => api.get<WatcherStatus>('/api/watcher/status'),
  start: (config: { interval_hours?: number; max_per_run?: number; steps?: string[] }) =>
    api.post<Record<string, unknown>>('/api/watcher/start', config),
  stop: () => api.post<Record<string, unknown>>('/api/watcher/stop'),
  updateConfig: (config: { interval_hours?: number; max_per_run?: number; steps?: string[] }) =>
    api.patch<Record<string, unknown>>('/api/watcher/config', config),
}
