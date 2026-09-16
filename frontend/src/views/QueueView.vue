<script setup lang="ts">
import { onMounted } from 'vue'
import { useQueueStore } from '../stores/queue'
import QueueControls from '../components/queue/QueueControls.vue'
import QueueList from '../components/queue/QueueList.vue'
import AddToQueuePanel from '../components/queue/AddToQueuePanel.vue'

const queueStore = useQueueStore()

onMounted(() => {
  queueStore.fetchQueue()
})
</script>

<template>
  <div>
    <h2 class="text-2xl font-semibold text-gray-900 mb-6">Queue</h2>
    <QueueControls />
    <QueueList />
    <AddToQueuePanel />
  </div>
</template>
