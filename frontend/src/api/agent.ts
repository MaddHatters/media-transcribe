import type { AgentHealth } from '../types'
import { api } from './client'

export const agentApi = {
  health: () => api.get<AgentHealth>('/api/agent/health'),
  status: () => api.get<Record<string, unknown>>('/api/agent/status'),
}
