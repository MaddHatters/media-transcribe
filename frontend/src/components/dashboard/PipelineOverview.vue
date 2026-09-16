<script setup lang="ts">
import { computed } from 'vue'
import { useCatalogStore } from '../../stores/catalog'
import { PIPELINE_STEPS } from '../../types'
import LoadingSpinner from '../shared/LoadingSpinner.vue'

const catalogStore = useCatalogStore()

function formatStepName(step: string): string {
  return step.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

const stepData = computed(() => {
  if (!catalogStore.stats?.by_step) return []
  const totalPosts = catalogStore.stats.total_posts || 1
  return PIPELINE_STEPS.map(step => {
    const counts = catalogStore.stats!.by_step[step] ?? {}
    const completed = counts.completed ?? 0
    const failed = counts.failed ?? 0
    const running = counts.running ?? counts.in_progress ?? 0
    const pending = counts.pending ?? 0
    const total = completed + failed + running + pending
    return {
      name: formatStepName(step),
      completed,
      failed,
      running,
      pending,
      total,
      completedPct: (completed / totalPosts) * 100,
      failedPct: (failed / totalPosts) * 100,
      runningPct: (running / totalPosts) * 100,
      pendingPct: (pending / totalPosts) * 100,
    }
  })
})
</script>

<template>
  <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
    <h3 class="text-sm font-semibold text-gray-900 mb-4">Pipeline Funnel</h3>

    <div v-if="!catalogStore.stats" class="flex justify-center py-8">
      <LoadingSpinner />
    </div>

    <div v-else class="space-y-3">
      <div v-for="step in stepData" :key="step.name" class="flex items-center gap-3">
        <span class="text-xs text-gray-600 w-28 shrink-0 text-right">{{ step.name }}</span>
        <div class="flex-1 h-5 bg-gray-100 rounded-full overflow-hidden flex">
          <div
            v-if="step.completedPct > 0"
            class="bg-green-500 h-full transition-all"
            :style="{ width: step.completedPct + '%' }"
          />
          <div
            v-if="step.runningPct > 0"
            class="bg-blue-500 h-full transition-all"
            :style="{ width: step.runningPct + '%' }"
          />
          <div
            v-if="step.failedPct > 0"
            class="bg-red-500 h-full transition-all"
            :style="{ width: step.failedPct + '%' }"
          />
          <div
            v-if="step.pendingPct > 0"
            class="bg-gray-300 h-full transition-all"
            :style="{ width: step.pendingPct + '%' }"
          />
        </div>
        <span class="text-xs text-gray-500 w-10 shrink-0">{{ step.completed }}/{{ step.total }}</span>
      </div>

      <div class="flex items-center gap-4 pt-2 mt-2 border-t border-gray-100">
        <div class="flex items-center gap-1.5">
          <span class="h-2.5 w-2.5 rounded-full bg-green-500" />
          <span class="text-xs text-gray-500">Completed</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="h-2.5 w-2.5 rounded-full bg-blue-500" />
          <span class="text-xs text-gray-500">Running</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="h-2.5 w-2.5 rounded-full bg-red-500" />
          <span class="text-xs text-gray-500">Failed</span>
        </div>
        <div class="flex items-center gap-1.5">
          <span class="h-2.5 w-2.5 rounded-full bg-gray-300" />
          <span class="text-xs text-gray-500">Pending</span>
        </div>
      </div>
    </div>
  </div>
</template>
