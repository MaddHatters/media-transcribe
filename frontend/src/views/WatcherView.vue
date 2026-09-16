<script setup lang="ts">
import { onMounted } from 'vue'
import { useWatcherStore } from '../stores/watcher'
import WatcherStatus from '../components/watcher/WatcherStatus.vue'
import WatcherControls from '../components/watcher/WatcherControls.vue'
import DiscoveryFeed from '../components/watcher/DiscoveryFeed.vue'
import WatcherTimeline from '../components/watcher/WatcherTimeline.vue'

const watcherStore = useWatcherStore()

onMounted(() => {
  watcherStore.fetchStatus()
  watcherStore.fetchDiscoveryHistory()
  watcherStore.fetchNewPosts()
})
</script>

<template>
  <div>
    <h2 class="text-2xl font-semibold text-gray-900 mb-6">Watcher</h2>
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div class="lg:col-span-2">
        <WatcherStatus />
      </div>
      <div>
        <WatcherControls />
      </div>
    </div>
    <div class="mt-6">
      <DiscoveryFeed />
    </div>
    <div class="mt-6">
      <WatcherTimeline />
    </div>
  </div>
</template>
