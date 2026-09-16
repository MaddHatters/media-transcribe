import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { QueueEntry } from '../types'
import { queueApi } from '../api/queue'

export const useQueueStore = defineStore('queue', () => {
  const entries = ref<QueueEntry[]>([])
  const loading = ref(false)
  const processing = ref(false)

  async function fetchQueue() {
    loading.value = true
    try {
      entries.value = await queueApi.list()
      processing.value = entries.value.some(e => e.status === 'processing')
    } finally {
      loading.value = false
    }
  }

  async function addToQueue(postIds: string[], priority = 0) {
    const result = await queueApi.add(postIds, priority)
    await fetchQueue()
    return result
  }

  async function removeFromQueue(postId: string) {
    await queueApi.remove(postId)
    await fetchQueue()
  }

  async function reorder(postIds: string[]) {
    await queueApi.reorder(postIds)
    await fetchQueue()
  }

  async function startQueue() {
    const result = await queueApi.start()
    processing.value = true
    await fetchQueue()
    return result
  }

  async function pauseQueue() {
    await queueApi.pause()
    processing.value = false
    await fetchQueue()
  }

  async function clearCompleted() {
    await queueApi.clear()
    await fetchQueue()
  }

  return {
    entries, loading, processing,
    fetchQueue, addToQueue, removeFromQueue, reorder,
    startQueue, pauseQueue, clearCompleted,
  }
})
