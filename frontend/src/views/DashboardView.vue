<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useCatalogStore } from '../stores/catalog'
import { useAgentStore } from '../stores/agent'
import { useWebSocketStore } from '../stores/websocket'
import StatsCards from '../components/dashboard/StatsCards.vue'
import AgentHealthBadge from '../components/dashboard/AgentHealthBadge.vue'
import PipelineOverview from '../components/dashboard/PipelineOverview.vue'
import RecentActivity from '../components/dashboard/RecentActivity.vue'
import QuickActions from '../components/dashboard/QuickActions.vue'

const catalogStore = useCatalogStore()
const agentStore = useAgentStore()
const wsStore = useWebSocketStore()

onMounted(() => {
  catalogStore.fetchStats()
  agentStore.startPolling()
  wsStore.connect()
})

onUnmounted(() => {
  agentStore.stopPolling()
})
</script>

<template>
  <div>
    <h2 class="text-2xl font-semibold text-gray-900 mb-6">Dashboard</h2>
    <StatsCards />
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6">
      <div class="lg:col-span-2">
        <PipelineOverview />
      </div>
      <div>
        <AgentHealthBadge />
      </div>
    </div>
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6">
      <div class="lg:col-span-2">
        <RecentActivity />
      </div>
      <div>
        <QuickActions />
      </div>
    </div>
  </div>
</template>
