<script setup lang="ts">
import { watch, computed } from 'vue'
import { onKeyStroke } from '@vueuse/core'
import { useCatalogStore } from '../../stores/catalog'
import StatusBadge from '../shared/StatusBadge.vue'
import PostTypeIcon from '../shared/PostTypeIcon.vue'
import DateDisplay from '../shared/DateDisplay.vue'
import DurationDisplay from '../shared/DurationDisplay.vue'
import LoadingSpinner from '../shared/LoadingSpinner.vue'
import StepTimeline from './StepTimeline.vue'

const props = defineProps<{
  postId: string | null
  open: boolean
}>()

const emit = defineEmits<{
  close: []
  'add-to-queue': [postId: string]
}>()

const catalogStore = useCatalogStore()
const post = computed(() => catalogStore.currentPost)

watch(() => props.postId, (id) => {
  if (id) catalogStore.fetchPost(id)
})

onKeyStroke('Escape', () => {
  if (props.open) emit('close')
})

function onBackdrop() {
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-40">
      <div class="fixed inset-0 bg-black/50" @click="onBackdrop" />
      <div class="fixed inset-0 flex items-center justify-center p-4">
        <div class="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto relative">
          <div v-if="!post" class="flex justify-center py-12">
            <LoadingSpinner />
          </div>
          <template v-else>
            <!-- Header -->
            <div class="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-start justify-between rounded-t-xl">
              <div class="flex items-center gap-2 min-w-0">
                <PostTypeIcon :type="post.post_type" />
                <h3 class="text-lg font-semibold text-gray-900 truncate">{{ post.title }}</h3>
                <StatusBadge :status="post.overall_status" />
              </div>
              <button class="text-gray-400 hover:text-gray-600 shrink-0 ml-4" @click="emit('close')">
                <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <!-- Metadata -->
            <div class="px-6 py-4 border-b border-gray-100">
              <div class="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <span class="text-gray-500">Published</span>
                  <p class="text-gray-900"><DateDisplay :date="post.published_at" :relative="false" /></p>
                </div>
                <div>
                  <span class="text-gray-500">Duration</span>
                  <p class="text-gray-900"><DurationDisplay :seconds="post.duration_seconds" /></p>
                </div>
                <div v-if="post.like_count !== null">
                  <span class="text-gray-500">Likes</span>
                  <p class="text-gray-900">{{ post.like_count }}</p>
                </div>
                <div v-if="post.comment_count !== null">
                  <span class="text-gray-500">Comments</span>
                  <p class="text-gray-900">{{ post.comment_count }}</p>
                </div>
              </div>
              <div v-if="post.tags.length > 0" class="mt-3 flex flex-wrap gap-1">
                <span
                  v-for="tag in post.tags"
                  :key="tag"
                  class="inline-block bg-gray-100 text-gray-600 text-xs rounded-full px-2 py-0.5"
                >
                  {{ tag }}
                </span>
              </div>
              <div v-if="post.thumbnail_url" class="mt-3">
                <img :src="post.thumbnail_url" alt="Thumbnail" class="rounded-lg object-cover h-32 w-full" />
              </div>
            </div>

            <!-- Step Timeline -->
            <div class="px-6 py-4">
              <h4 class="text-sm font-semibold text-gray-900 mb-4">Pipeline Steps</h4>
              <StepTimeline :steps="post.steps" />
            </div>

            <!-- Actions -->
            <div class="px-6 py-4 border-t border-gray-100 flex items-center gap-3">
              <button
                class="bg-indigo-600 text-white text-sm rounded-md px-4 py-2 hover:bg-indigo-700"
                @click="emit('add-to-queue', post.post_id)"
              >
                Add to Queue
              </button>
              <a
                v-if="post.url"
                :href="post.url"
                target="_blank"
                rel="noopener noreferrer"
                class="text-sm text-indigo-600 hover:text-indigo-800"
              >
                View on Patreon &rarr;
              </a>
            </div>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</template>
