<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { discoveryApi } from '../../api/discovery'
import LoadingSpinner from '../shared/LoadingSpinner.vue'

const router = useRouter()
const discovering = ref(false)
const discoverResult = ref<string | null>(null)

async function handleDiscover() {
  discovering.value = true
  discoverResult.value = null
  try {
    const res = await discoveryApi.trigger()
    discoverResult.value = `Found ${res.new_posts} new posts`
    setTimeout(() => { discoverResult.value = null }, 5000)
  } catch {
    discoverResult.value = 'Discovery failed'
    setTimeout(() => { discoverResult.value = null }, 5000)
  } finally {
    discovering.value = false
  }
}
</script>

<template>
  <div class="bg-white rounded-lg shadow-sm border border-gray-200 p-5">
    <h3 class="text-sm font-semibold text-gray-900 mb-4">Quick Actions</h3>
    <div class="space-y-3">
      <button
        class="w-full flex items-center justify-center gap-2 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2.5 text-sm font-medium transition-colors disabled:opacity-50"
        :disabled="discovering"
        @click="handleDiscover"
      >
        <LoadingSpinner v-if="discovering" size="sm" />
        <template v-else>
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          Discover Now
        </template>
      </button>
      <p v-if="discoverResult" class="text-xs text-center" :class="discoverResult.includes('failed') ? 'text-red-500' : 'text-green-600'">
        {{ discoverResult }}
      </p>
      <button
        class="w-full flex items-center justify-center gap-2 rounded-lg bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 px-4 py-2.5 text-sm font-medium transition-colors"
        @click="router.push('/queue')"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 010 3.75H5.625a1.875 1.875 0 010-3.75z" />
        </svg>
        View Queue
      </button>
      <button
        class="w-full flex items-center justify-center gap-2 rounded-lg bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 px-4 py-2.5 text-sm font-medium transition-colors"
        @click="router.push('/catalog')"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zM3.75 12h.007v.008H3.75V12zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm-.375 5.25h.007v.008H3.75v-.008zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
        </svg>
        Open Catalog
      </button>
    </div>
  </div>
</template>
