<script setup lang="ts">
import { useWatcherStore } from '../../stores/watcher'
import DateDisplay from '../shared/DateDisplay.vue'
import StatusBadge from '../shared/StatusBadge.vue'
import EmptyState from '../shared/EmptyState.vue'

const watcherStore = useWatcherStore()
</script>

<template>
  <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
    <h3 class="text-sm font-semibold text-gray-900 mb-4">Cycle History</h3>

    <template v-if="watcherStore.discoveryHistory.length === 0">
      <EmptyState message="No watcher cycles yet" />
    </template>
    <div v-else class="overflow-x-auto">
      <table class="w-full">
        <thead class="bg-gray-50 border-b border-gray-200">
          <tr>
            <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
            <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
            <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Found</th>
            <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">New</th>
            <th class="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          <tr v-for="run in watcherStore.discoveryHistory" :key="run.id ?? run.started_at">
            <td class="px-4 py-2 text-sm text-gray-600">
              <DateDisplay :date="run.started_at" />
            </td>
            <td class="px-4 py-2 text-sm text-gray-600">{{ run.source }}</td>
            <td class="px-4 py-2 text-sm text-gray-900">{{ run.posts_found }}</td>
            <td class="px-4 py-2 text-sm text-gray-900">{{ run.new_posts }}</td>
            <td class="px-4 py-2">
              <StatusBadge :status="run.status" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
