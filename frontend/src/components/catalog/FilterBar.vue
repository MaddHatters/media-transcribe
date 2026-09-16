<script setup lang="ts">
import { reactive } from 'vue'
import { useDebounceFn } from '@vueuse/core'
import { PIPELINE_STEPS } from '../../types'
import type { CatalogFilters } from '../../api/catalog'

interface ExtendedFilters extends CatalogFilters {
  date_from?: string
  date_to?: string
}

const emit = defineEmits<{
  'update:filters': [filters: ExtendedFilters]
}>()

const filters = reactive<ExtendedFilters>({
  type: '',
  status: '',
  step: '',
  search: '',
  date_from: '',
  date_to: '',
})

function emitFilters() {
  const clean: ExtendedFilters = {}
  if (filters.type) clean.type = filters.type
  if (filters.status) clean.status = filters.status
  if (filters.step) clean.step = filters.step
  if (filters.search) clean.search = filters.search
  if (filters.date_from) clean.date_from = filters.date_from
  if (filters.date_to) clean.date_to = filters.date_to
  emit('update:filters', clean)
}

const debouncedEmit = useDebounceFn(emitFilters, 300)

function onSearchInput() {
  debouncedEmit()
}

function onChange() {
  emitFilters()
}

function reset() {
  filters.type = ''
  filters.status = ''
  filters.step = ''
  filters.search = ''
  filters.date_from = ''
  filters.date_to = ''
  emitFilters()
}

const stepStatusOptions: string[] = []
for (const step of PIPELINE_STEPS) {
  for (const s of ['pending', 'completed', 'failed', 'running']) {
    stepStatusOptions.push(`${step}:${s}`)
  }
}

function formatStepOption(opt: string): string {
  const [step, status] = opt.split(':')
  const name = step.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  return `${name}: ${status}`
}
</script>

<template>
  <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-4 mb-4">
    <div class="flex flex-wrap items-end gap-3">
      <div>
        <label class="block text-xs font-medium text-gray-600 mb-1">Type</label>
        <select v-model="filters.type" class="rounded-md border-gray-300 text-sm px-2 py-1.5 border" @change="onChange">
          <option value="">All</option>
          <option value="video_embed">Video</option>
          <option value="audio">Audio</option>
          <option value="podcast">Podcast</option>
          <option value="text">Text</option>
        </select>
      </div>

      <div>
        <label class="block text-xs font-medium text-gray-600 mb-1">Status</label>
        <select v-model="filters.status" class="rounded-md border-gray-300 text-sm px-2 py-1.5 border" @change="onChange">
          <option value="">All</option>
          <option value="discovered">Discovered</option>
          <option value="queued">Queued</option>
          <option value="in_progress">In Progress</option>
          <option value="partial">Partial</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
        </select>
      </div>

      <div>
        <label class="block text-xs font-medium text-gray-600 mb-1">Step</label>
        <select v-model="filters.step" class="rounded-md border-gray-300 text-sm px-2 py-1.5 border" @change="onChange">
          <option value="">Any step</option>
          <option v-for="opt in stepStatusOptions" :key="opt" :value="opt">
            {{ formatStepOption(opt) }}
          </option>
        </select>
      </div>

      <div>
        <label class="block text-xs font-medium text-gray-600 mb-1">Search</label>
        <input
          v-model="filters.search"
          type="text"
          placeholder="Search titles..."
          class="rounded-md border-gray-300 text-sm px-2 py-1.5 border w-48"
          @input="onSearchInput"
        />
      </div>

      <div>
        <label class="block text-xs font-medium text-gray-600 mb-1">From</label>
        <input
          v-model="filters.date_from"
          type="date"
          class="rounded-md border-gray-300 text-sm px-2 py-1.5 border"
          @change="onChange"
        />
      </div>

      <div>
        <label class="block text-xs font-medium text-gray-600 mb-1">To</label>
        <input
          v-model="filters.date_to"
          type="date"
          class="rounded-md border-gray-300 text-sm px-2 py-1.5 border"
          @change="onChange"
        />
      </div>

      <button
        class="rounded-md border border-gray-300 text-sm px-3 py-1.5 text-gray-600 hover:bg-gray-50"
        @click="reset"
      >
        Reset
      </button>
    </div>
  </div>
</template>
