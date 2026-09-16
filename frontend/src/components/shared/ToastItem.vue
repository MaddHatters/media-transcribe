<script setup lang="ts">
import { useToastStore, type Toast } from '../../stores/toast'

defineProps<{ toast: Toast }>()

const toastStore = useToastStore()

const borderColors: Record<string, string> = {
  success: 'border-l-green-500',
  error: 'border-l-red-500',
  info: 'border-l-blue-500',
  warning: 'border-l-yellow-500',
}

const iconColors: Record<string, string> = {
  success: 'text-green-500',
  error: 'text-red-500',
  info: 'text-blue-500',
  warning: 'text-yellow-500',
}
</script>

<template>
  <div
    class="bg-white rounded-lg shadow-lg border border-gray-200 border-l-4 p-3 flex items-start gap-2 min-w-[280px] max-w-sm"
    :class="borderColors[toast.type]"
  >
    <svg v-if="toast.type === 'success'" :class="['w-5 h-5 shrink-0', iconColors[toast.type]]" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
      <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
    <svg v-else-if="toast.type === 'error'" :class="['w-5 h-5 shrink-0', iconColors[toast.type]]" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
      <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
    </svg>
    <svg v-else-if="toast.type === 'warning'" :class="['w-5 h-5 shrink-0', iconColors[toast.type]]" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
      <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126z" />
    </svg>
    <svg v-else :class="['w-5 h-5 shrink-0', iconColors[toast.type]]" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
      <path stroke-linecap="round" stroke-linejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z" />
    </svg>
    <p class="text-sm text-gray-700 flex-1">{{ toast.message }}</p>
    <button
      class="text-gray-400 hover:text-gray-600 shrink-0"
      @click="toastStore.remove(toast.id)"
    >
      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
      </svg>
    </button>
  </div>
</template>
