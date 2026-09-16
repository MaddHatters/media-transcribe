<script setup lang="ts">
import { computed } from 'vue'
import type { StepStatusResponse } from '../../types'
import { PIPELINE_STEPS } from '../../types'
import StatusBadge from '../shared/StatusBadge.vue'
import DateDisplay from '../shared/DateDisplay.vue'
import DurationDisplay from '../shared/DurationDisplay.vue'

const props = defineProps<{ steps: Record<string, StepStatusResponse> }>()

const dotColor: Record<string, string> = {
  pending: 'bg-gray-300',
  queued: 'bg-blue-400',
  running: 'bg-yellow-400 animate-pulse',
  completed: 'bg-green-500',
  failed: 'bg-red-500',
  skipped: 'bg-gray-300',
}

function formatStepName(step: string): string {
  return step.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function getStep(step: string): StepStatusResponse {
  return props.steps[step] ?? {
    status: 'pending',
    started_at: null,
    completed_at: null,
    error: null,
    output_path: null,
    duration_seconds: null,
    attempt: 0,
  }
}

const lineStyle = computed(() => (step: string) => {
  const s = getStep(step)
  return s.status === 'completed' ? 'border-gray-300' : 'border-dashed border-gray-200'
})
</script>

<template>
  <div class="relative">
    <div
      v-for="(step, idx) in PIPELINE_STEPS"
      :key="step"
      class="relative flex gap-4 pb-6"
    >
      <!-- Vertical connecting line -->
      <div class="flex flex-col items-center">
        <div
          class="w-3 h-3 rounded-full shrink-0 z-10"
          :class="dotColor[getStep(step).status] ?? 'bg-gray-300'"
        />
        <div
          v-if="idx < PIPELINE_STEPS.length - 1"
          class="w-0 flex-1 border-l-2"
          :class="lineStyle(step)"
        />
      </div>

      <!-- Step content -->
      <div class="flex-1 -mt-0.5">
        <div class="flex items-center gap-2 mb-1">
          <span class="text-sm font-medium text-gray-900">{{ formatStepName(step) }}</span>
          <StatusBadge :status="getStep(step).status" />
        </div>

        <div v-if="getStep(step).status === 'completed'" class="text-xs text-gray-500 space-y-0.5">
          <div v-if="getStep(step).started_at">
            <DateDisplay :date="getStep(step).started_at" />
            <span v-if="getStep(step).completed_at"> &rarr; <DateDisplay :date="getStep(step).completed_at" /></span>
          </div>
          <div v-if="getStep(step).duration_seconds !== null">
            Duration: <DurationDisplay :seconds="getStep(step).duration_seconds" />
          </div>
          <div v-if="getStep(step).output_path" class="font-mono text-xs text-gray-400 truncate">
            {{ getStep(step).output_path }}
          </div>
        </div>

        <div v-if="getStep(step).status === 'failed'" class="text-xs space-y-0.5">
          <p class="text-red-600">{{ getStep(step).error }}</p>
          <p v-if="getStep(step).attempt > 1" class="text-gray-500">Attempt {{ getStep(step).attempt }}</p>
        </div>
      </div>
    </div>
  </div>
</template>
