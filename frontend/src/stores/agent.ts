import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { AgentHealth } from '../types'
import { agentApi } from '../api/agent'

export const useAgentStore = defineStore('agent', () => {
  const health = ref<AgentHealth | null>(null)
  const status = ref<Record<string, unknown> | null>(null)
  const lastChecked = ref<string | null>(null)
  const loading = ref(false)
  let pollInterval: ReturnType<typeof setInterval> | null = null

  async function fetchHealth() {
    loading.value = true
    try {
      health.value = await agentApi.health()
      lastChecked.value = new Date().toISOString()
    } catch {
      health.value = {
        healthy: false,
        obs_connected: false,
        chrome_available: false,
        disk_ok: false,
        error: 'Failed to reach API',
        obs_version: null,
      }
    } finally {
      loading.value = false
    }
  }

  async function fetchStatus() {
    status.value = await agentApi.status()
  }

  function startPolling(intervalMs = 30_000) {
    fetchHealth()
    pollInterval = setInterval(fetchHealth, intervalMs)
  }

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  }

  return { health, status, lastChecked, loading, fetchHealth, fetchStatus, startPolling, stopPolling }
})
