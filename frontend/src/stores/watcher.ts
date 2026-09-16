import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { WatcherStatus, DiscoveryRunResponse, PostSummary } from '../types'
import { watcherApi } from '../api/watcher'
import { discoveryApi } from '../api/discovery'

export const useWatcherStore = defineStore('watcher', () => {
  const status = ref<WatcherStatus | null>(null)
  const discoveryHistory = ref<DiscoveryRunResponse[]>([])
  const newPosts = ref<PostSummary[]>([])
  const loading = ref(false)
  const discovering = ref(false)

  async function fetchStatus() {
    loading.value = true
    try {
      status.value = await watcherApi.status()
    } catch {
      status.value = null
    } finally {
      loading.value = false
    }
  }

  async function startWatcher(config: { interval_hours?: number; max_per_run?: number; steps?: string[] }) {
    await watcherApi.start(config)
    await fetchStatus()
  }

  async function stopWatcher() {
    await watcherApi.stop()
    await fetchStatus()
  }

  async function updateConfig(config: { interval_hours?: number; max_per_run?: number; steps?: string[] }) {
    await watcherApi.updateConfig(config)
    await fetchStatus()
  }

  async function fetchDiscoveryHistory() {
    discoveryHistory.value = await discoveryApi.history()
  }

  async function fetchNewPosts() {
    newPosts.value = await discoveryApi.newPosts()
  }

  async function triggerDiscovery(fullCatalog = false) {
    discovering.value = true
    try {
      const result = await discoveryApi.trigger(fullCatalog)
      await fetchNewPosts()
      await fetchDiscoveryHistory()
      return result
    } finally {
      discovering.value = false
    }
  }

  return {
    status, discoveryHistory, newPosts, loading, discovering,
    fetchStatus, startWatcher, stopWatcher, updateConfig,
    fetchDiscoveryHistory, fetchNewPosts, triggerDiscovery,
  }
})
