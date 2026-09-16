<script setup lang="ts">
import { VueDraggable } from 'vue-draggable-plus'
import { useQueueStore } from '../../stores/queue'
import QueueItem from './QueueItem.vue'
import LoadingSpinner from '../shared/LoadingSpinner.vue'
import EmptyState from '../shared/EmptyState.vue'

const queueStore = useQueueStore()

function onDragEnd() {
  const newOrder = queueStore.entries.map(e => e.post_id)
  queueStore.reorder(newOrder)
}

function onRemove(postId: string) {
  queueStore.removeFromQueue(postId)
}
</script>

<template>
  <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
    <h3 class="text-sm font-semibold text-gray-900 mb-4">Queue Entries</h3>

    <div v-if="queueStore.loading" class="flex justify-center py-8">
      <LoadingSpinner />
    </div>
    <template v-else-if="queueStore.entries.length === 0">
      <EmptyState message="Queue is empty" />
    </template>
    <VueDraggable
      v-else
      v-model="queueStore.entries"
      handle=".drag-handle"
      :animation="200"
      ghost-class="opacity-50"
      class="space-y-2"
      @end="onDragEnd"
    >
      <QueueItem
        v-for="entry in queueStore.entries"
        :key="entry.post_id"
        :entry="entry"
        @remove="onRemove"
      />
    </VueDraggable>
  </div>
</template>
