<script setup lang="ts">
import { ref, watch } from 'vue'
import { useWatcherStore } from '../../stores/watcher'
import { useToastStore } from '../../stores/toast'
import { PIPELINE_STEPS } from '../../types'

const watcherStore = useWatcherStore()
const toastStore = useToastStore()

const intervalHours = ref(24)
const maxPerRun = ref(3)
const selectedSteps = ref<string[]>(['record', 'transcribe', 'correct'])

watch(() => watcherStore.status, (s) => {
  if (s) {
    intervalHours.value = s.interval_hours
  }
}, { immediate: true })

async function onToggle() {
  try {
    if (watcherStore.status?.running) {
      await watcherStore.stopWatcher()
      toastStore.add('info', 'Watcher stopped')
    } else {
      await watcherStore.startWatcher({
        interval_hours: intervalHours.value,
        max_per_run: maxPerRun.value,
        steps: selectedSteps.value,
      })
      toastStore.add('success', 'Watcher started')
    }
  } catch {
    toastStore.add('error', 'Failed to toggle watcher')
  }
}

async function onApplyConfig() {
  try {
    await watcherStore.updateConfig({
      interval_hours: intervalHours.value,
      max_per_run: maxPerRun.value,
      steps: selectedSteps.value,
    })
    toastStore.add('success', 'Config updated')
  } catch {
    toastStore.add('error', 'Failed to update config')
  }
}

function formatStep(step: string): string {
  return step.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}
</script>

<template>
  <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
    <h3 class="text-sm font-semibold text-gray-900 mb-4">Controls</h3>

    <!-- Start/Stop toggle -->
    <button
      class="w-full text-white text-sm font-medium px-4 py-2 rounded-md mb-4"
      :class="watcherStore.status?.running
        ? 'bg-red-600 hover:bg-red-700'
        : 'bg-green-600 hover:bg-green-700'"
      @click="onToggle"
    >
      {{ watcherStore.status?.running ? 'Stop Watcher' : 'Start Watcher' }}
    </button>

    <!-- Config inputs -->
    <fieldset :disabled="watcherStore.status?.running" class="space-y-3">
      <div>
        <label class="block text-xs font-medium text-gray-600 mb-1">Interval (hours)</label>
        <input
          v-model.number="intervalHours"
          type="number"
          min="12"
          step="1"
          class="w-full rounded-md border border-gray-300 text-sm px-2 py-1.5 disabled:bg-gray-50 disabled:text-gray-400"
        />
      </div>
      <div>
        <label class="block text-xs font-medium text-gray-600 mb-1">Max per run</label>
        <input
          v-model.number="maxPerRun"
          type="number"
          min="1"
          max="20"
          class="w-full rounded-md border border-gray-300 text-sm px-2 py-1.5 disabled:bg-gray-50 disabled:text-gray-400"
        />
      </div>
      <div>
        <label class="block text-xs font-medium text-gray-600 mb-1">Pipeline Steps</label>
        <div class="space-y-1">
          <label
            v-for="step in PIPELINE_STEPS"
            :key="step"
            class="flex items-center gap-2 text-sm text-gray-700"
          >
            <input
              v-model="selectedSteps"
              type="checkbox"
              :value="step"
              class="rounded border-gray-300"
            />
            {{ formatStep(step) }}
          </label>
        </div>
      </div>
      <button
        class="w-full bg-white border border-gray-300 text-gray-700 text-sm font-medium px-4 py-2 rounded-md hover:bg-gray-50 disabled:opacity-50"
        @click="onApplyConfig"
      >
        Apply Config
      </button>
    </fieldset>
  </div>
</template>
