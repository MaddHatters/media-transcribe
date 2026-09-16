<script setup lang="ts">
import { ref, computed } from 'vue'
import { useDebounceFn } from '@vueuse/core'
import { catalogApi } from '../../api/catalog'
import { useQueueStore } from '../../stores/queue'
import { useToastStore } from '../../stores/toast'
import type { PostSummary } from '../../types'

const queueStore = useQueueStore()
const toastStore = useToastStore()

const expanded = ref(false)
const query = ref('')
const results = ref<PostSummary[]>([])
const searching = ref(false)

const queuedIds = computed(() => new Set(queueStore.entries.map(e => e.post_id)))

const doSearch = useDebounceFn(async () => {
  if (!query.value.trim()) {
    results.value = []
    return
  }
  searching.value = true
  try {
    const data = await catalogApi.list({ search: query.value, per_page: 10 })
    results.value = data.posts
  } catch {
    results.value = []
  } finally {
    searching.value = false
  }
}, 300)

function onInput() {
  doSearch()
}

async function addPost(postId: string) {
  try {
    await queueStore.addToQueue([postId])
    toastStore.add('success', 'Added to queue')
  } catch {
    toastStore.add('error', 'Failed to add to queue')
  }
}
</script>

<template>
  <div class="mt-4">
    <button
      class="text-sm text-indigo-600 hover:text-indigo-800 font-medium flex items-center gap-1"
      @click="expanded = !expanded"
    >
      <svg
        class="w-4 h-4 transition-transform"
        :class="{ 'rotate-90': expanded }"
        fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"
      >
        <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
      </svg>
      Add Posts to Queue
    </button>

    <div v-if="expanded" class="mt-3 bg-gray-50 border border-gray-200 rounded-lg p-4">
      <input
        v-model="query"
        type="text"
        placeholder="Search catalog posts by title..."
        class="w-full rounded-md border border-gray-300 text-sm px-3 py-2 mb-3"
        @input="onInput"
      />

      <div v-if="searching" class="text-sm text-gray-500 py-2">Searching...</div>
      <div v-else-if="results.length === 0 && query.trim()" class="text-sm text-gray-500 py-2">No results found</div>

      <div v-if="results.length > 0" class="space-y-2">
        <div
          v-for="post in results"
          :key="post.post_id"
          class="flex items-center justify-between bg-white rounded-md border border-gray-200 px-3 py-2"
        >
          <div class="min-w-0 flex-1">
            <p class="text-sm font-medium text-gray-900 truncate">{{ post.title }}</p>
            <p class="text-xs text-gray-500">{{ post.post_type }} &middot; {{ post.overall_status }}</p>
          </div>
          <span
            v-if="queuedIds.has(post.post_id)"
            class="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full shrink-0 ml-2"
          >
            Queued
          </span>
          <button
            v-else
            class="bg-indigo-600 text-white text-xs rounded px-2 py-1 hover:bg-indigo-700 shrink-0 ml-2"
            @click="addPost(post.post_id)"
          >
            Add
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
