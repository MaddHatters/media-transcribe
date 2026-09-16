<script setup lang="ts">
import type { PostSummary } from '../../types'
import { PIPELINE_STEPS } from '../../types'
import PostTypeIcon from '../shared/PostTypeIcon.vue'
import StatusBadge from '../shared/StatusBadge.vue'
import DateDisplay from '../shared/DateDisplay.vue'
import DurationDisplay from '../shared/DurationDisplay.vue'
import StepBadge from './StepBadge.vue'

defineProps<{ post: PostSummary }>()
defineEmits<{ click: [] }>()
</script>

<template>
  <tr class="hover:bg-gray-50 cursor-pointer" @click="$emit('click')">
    <td class="px-4 py-3 text-sm">
      <div class="flex items-center gap-2">
        <PostTypeIcon :type="post.post_type" />
        <span class="truncate max-w-xs hover:text-indigo-600">{{ post.title }}</span>
      </div>
    </td>
    <td class="px-4 py-3 text-sm text-gray-500">{{ post.post_type }}</td>
    <td class="px-4 py-3 text-sm text-gray-500">
      <DateDisplay :date="post.published_at" :relative="false" />
    </td>
    <td class="px-4 py-3">
      <StatusBadge :status="post.overall_status" />
    </td>
    <td class="px-4 py-3">
      <div class="flex items-center gap-1">
        <StepBadge
          v-for="step in PIPELINE_STEPS"
          :key="step"
          :step="step"
          :status="post.steps[step]?.status ?? 'pending'"
        />
      </div>
    </td>
    <td class="px-4 py-3 text-sm text-gray-500">
      <DurationDisplay :seconds="post.duration_seconds" />
    </td>
  </tr>
</template>
