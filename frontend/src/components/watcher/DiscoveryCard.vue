<script setup lang="ts">
import type { PostSummary } from '../../types'
import PostTypeIcon from '../shared/PostTypeIcon.vue'
import StatusBadge from '../shared/StatusBadge.vue'
import DateDisplay from '../shared/DateDisplay.vue'

defineProps<{ post: PostSummary }>()
defineEmits<{ 'add-to-queue': [postId: string] }>()
</script>

<template>
  <div class="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
    <!-- Thumbnail -->
    <div v-if="post.thumbnail_url" class="h-24 w-full">
      <img :src="post.thumbnail_url" alt="" class="rounded-t-lg object-cover h-24 w-full" />
    </div>
    <div v-else class="h-24 w-full bg-gradient-to-br from-indigo-100 to-indigo-50 flex items-center justify-center rounded-t-lg">
      <PostTypeIcon :type="post.post_type" />
    </div>

    <div class="p-3 relative">
      <div class="absolute top-3 right-3">
        <StatusBadge :status="post.overall_status" />
      </div>
      <div class="flex items-center gap-1 mb-1">
        <PostTypeIcon :type="post.post_type" />
        <p class="text-sm font-medium text-gray-900 truncate pr-16">{{ post.title }}</p>
      </div>
      <p class="text-xs text-gray-500 mb-2">
        <DateDisplay :date="post.published_at" :relative="false" />
      </p>
      <button
        class="bg-indigo-600 text-white text-xs rounded px-2 py-1 hover:bg-indigo-700"
        @click="$emit('add-to-queue', post.post_id)"
      >
        Add to Queue
      </button>
    </div>
  </div>
</template>
