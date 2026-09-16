<script setup lang="ts">
import { useToastStore } from '../../stores/toast'
import ToastItem from './ToastItem.vue'

const toastStore = useToastStore()
</script>

<template>
  <div class="fixed bottom-4 right-4 z-50 flex flex-col-reverse gap-2">
    <TransitionGroup
      enter-active-class="transition ease-out duration-300"
      enter-from-class="translate-x-full opacity-0"
      enter-to-class="translate-x-0 opacity-100"
      leave-active-class="transition ease-in duration-200"
      leave-from-class="translate-x-0 opacity-100"
      leave-to-class="translate-x-full opacity-0"
    >
      <ToastItem
        v-for="toast in toastStore.toasts"
        :key="toast.id"
        :toast="toast"
      />
    </TransitionGroup>
  </div>
</template>
