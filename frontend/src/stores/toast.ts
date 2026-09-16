import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface Toast {
  id: number
  type: 'success' | 'error' | 'info' | 'warning'
  message: string
}

export const useToastStore = defineStore('toast', () => {
  const toasts = ref<Toast[]>([])
  let nextId = 0

  function add(type: Toast['type'], message: string, durationMs = 5000) {
    const id = nextId++
    toasts.value.push({ id, type, message })
    if (durationMs > 0) {
      setTimeout(() => remove(id), durationMs)
    }
  }

  function remove(id: number) {
    toasts.value = toasts.value.filter(t => t.id !== id)
  }

  return { toasts, add, remove }
})
