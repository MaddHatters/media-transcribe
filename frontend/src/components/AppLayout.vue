<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
import { useWebSocketStore } from '../stores/websocket'

const wsStore = useWebSocketStore()

const navItems = [
  { to: '/', name: 'Dashboard', icon: 'grid' },
  { to: '/catalog', name: 'Catalog', icon: 'list' },
  { to: '/queue', name: 'Queue', icon: 'queue' },
  { to: '/watcher', name: 'Watcher', icon: 'eye' },
] as const
</script>

<template>
  <div class="flex min-h-screen">
    <aside class="fixed inset-y-0 left-0 w-64 bg-gray-900 flex flex-col">
      <div class="px-6 py-6">
        <h1 class="text-xl font-bold text-white tracking-tight">Insights</h1>
        <p class="text-xs text-gray-500 mt-1">Pipeline Dashboard</p>
      </div>
      <nav class="flex-1 px-3 space-y-1">
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors"
          :class="$route.path === item.to
            ? 'bg-gray-800 text-white'
            : 'text-gray-400 hover:text-white hover:bg-gray-800'"
        >
          <svg v-if="item.icon === 'grid'" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
          </svg>
          <svg v-else-if="item.icon === 'list'" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zM3.75 12h.007v.008H3.75V12zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm-.375 5.25h.007v.008H3.75v-.008zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
          </svg>
          <svg v-else-if="item.icon === 'queue'" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 010 3.75H5.625a1.875 1.875 0 010-3.75z" />
          </svg>
          <svg v-else-if="item.icon === 'eye'" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.64 0 8.577 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.64 0-8.577-3.007-9.963-7.178z" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          {{ item.name }}
        </RouterLink>
      </nav>
      <div class="mt-auto px-6 py-4 border-t border-gray-800">
        <div class="flex items-center gap-2">
          <span :class="['h-2 w-2 rounded-full', wsStore.connected ? 'bg-green-500' : 'bg-red-500']" />
          <span class="text-xs text-gray-500">{{ wsStore.connected ? 'Live' : 'Disconnected' }}</span>
        </div>
      </div>
    </aside>
    <main class="ml-64 flex-1 bg-gray-50 min-h-screen p-8">
      <RouterView />
    </main>
  </div>
</template>
