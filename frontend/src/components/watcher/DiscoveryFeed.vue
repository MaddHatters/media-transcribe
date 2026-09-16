<script setup lang="ts">
import { useWatcherStore } from '../../stores/watcher'
import { useQueueStore } from '../../stores/queue'
import { useToastStore } from '../../stores/toast'
import DiscoveryCard from './DiscoveryCard.vue'
import EmptyState from '../shared/EmptyState.vue'
import LoadingSpinner from '../shared/LoadingSpinner.vue'

const watcherStore = useWatcherStore()
const queueStore = useQueueStore()
const toastStore = useToastStore()

async function onDiscover() {
  try {
    await watcherStore.triggerDiscovery()
    toastStore.add('success', 'Discovery completed')
  } catch {
    toastStore.add('error', 'Discovery failed')
  }
}

async function onAddToQueue(postId: string) {
  try {
    await queueStore.addToQueue([postId])
    toastStore.add('success', 'Added to queue')
  } catch {
    toastStore.add('error', 'Failed to add to queue')
  }
}
</script>

<template>
  <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
    <div class="flex items-center justify-between mb-4">
      <div class="flex items-center gap-2">
        <h3 class="text-sm font-semibold text-gray-900">Recently Discovered</h3>
        <span
          v-if="watcherStore.newPosts.length > 0"
          class="bg-indigo-100 text-indigo-700 text-xs font-medium px-2 py-0.5 rounded-full"
        >
          {{ watcherStore.newPosts.length }}
        </span>
      </div>
      <button
        :disabled="watcherStore.discovering"
        class="bg-indigo-600 text-white text-xs font-medium px-3 py-1.5 rounded-md hover:bg-indigo-700 disabled:opacity-50 flex items-center gap-1"
        @click="onDiscover"
      >
        <LoadingSpinner v-if="watcherStore.discovering" size="sm" />
        Discover Now
      </button>
    </div>

    <template v-if="watcherStore.newPosts.length === 0">
      <EmptyState message="No new posts discovered" />
    </template>
    <div v-else class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      <DiscoveryCard
        v-for="post in watcherStore.newPosts"
        :key="post.post_id"
        :post="post"
        @add-to-queue="onAddToQueue"
      />
    </div>
  </div>
</template>
