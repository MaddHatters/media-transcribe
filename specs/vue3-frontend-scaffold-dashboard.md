# Plan: Vue 3 Frontend Scaffold + Dashboard View

## Task Description

Scaffold the Vue 3 frontend project and build the Dashboard view for the media-transcribe pipeline dashboard. This covers Steps 15-16 from the master plan at `specs/media-transcribe-web-app.md`. The FastAPI backend already exists at `web/app.py` with all API routes, models, and services fully implemented. No Python files should be modified.

**Task type:** Feature
**Complexity:** Complex

## Objective

When complete:
1. A Vue 3 + TypeScript + Tailwind project lives at `frontend/` with Vite dev server proxying to FastAPI on `:8420`
2. TypeScript interfaces mirror all Pydantic models from `web/models.py`
3. An API client layer provides typed fetch wrappers for every backend route
4. Vue Router is configured with routes for Dashboard, Catalog, Queue, and Watcher (only Dashboard view is built in this plan)
5. A dark sidebar + light content area layout renders with "Insights" branding and navigation links
6. The Dashboard view displays: StatsCards, AgentHealthBadge (polls every 30s), PipelineOverview funnel, RecentActivity feed (from WebSocket), and QuickActions
7. Pinia stores for `catalog` (stats) and `agent` (health/status) are wired to the API client
8. A WebSocket store auto-connects to `/ws/events` and distributes events to other stores
9. `npm run build` produces a production bundle in `frontend/dist/`

## Problem Statement

The FastAPI backend is fully built but has no frontend consumer. Users currently have no browser-based UI to visualize catalog stats, monitor the obs-machine agent health, or view pipeline activity. The frontend must be scaffolded from scratch as a Vue 3 SPA that talks to the existing API.

## Solution Approach

Use Vite + Vue 3 + TypeScript as the framework, Tailwind CSS (v4, via `@tailwindcss/vite` plugin) for styling, Pinia for state management, and Vue Router for navigation. The API client uses plain `fetch` — no axios — with typed return values. The WebSocket store uses native `WebSocket` with exponential backoff reconnection. All components use Tailwind utility classes only — no custom CSS classes, no component libraries.

The layout follows a sidebar navigation pattern: a dark (`bg-gray-900`) sidebar on the left with the "Insights" title and nav links, and a light (`bg-gray-50`) content area on the right where `<router-view />` renders the active page.

---

## Relevant Files

### Existing Files (read-only context, do NOT modify)

- `web/app.py` — FastAPI app factory, lifespan, error handlers, static file mounting point
- `web/models.py` — Pydantic models: `PostSummary`, `PostDetail`, `StepStatusResponse`, `QueueEntry`, `WatcherStatus`, `AgentHealth`, `CatalogStats`, `WebSocketEvent`, etc.
- `web/config.py` — `PORT = 8420`, `CORS_ORIGINS` includes `http://localhost:5173`
- `web/lifecycle.py` — `StepStatus` enum, `PIPELINE_STEPS` list, `derive_post_status()`
- `web/routes/catalog.py` — `GET /api/catalog`, `GET /api/catalog/{post_id}`, `GET /api/catalog/stats`, `POST /api/catalog/import`
- `web/routes/queue.py` — `GET /api/queue`, `POST /api/queue`, `DELETE /api/queue/{post_id}`, `PATCH /api/queue/{post_id}`, `POST /api/queue/reorder`, `POST /api/queue/start`, `POST /api/queue/pause`, `POST /api/queue/clear`
- `web/routes/watcher.py` — `GET /api/watcher/status`, `POST /api/watcher/start`, `POST /api/watcher/stop`, `PATCH /api/watcher/config`
- `web/routes/discovery.py` — `POST /api/discovery/trigger`, `GET /api/discovery/history`, `GET /api/discovery/new`
- `web/routes/pipeline.py` — `GET /api/pipeline/status`, `POST /api/pipeline/run`
- `web/routes/agent.py` — `GET /api/agent/health`, `GET /api/agent/status`
- `web/routes/ws.py` — `WS /ws/events` (heartbeat ping every 30s, event JSON messages)

### New Files

#### Project Root

- `frontend/package.json` — Dependencies and scripts
- `frontend/vite.config.ts` — Vite config with API/WS proxy
- `frontend/tsconfig.json` — TypeScript config
- `frontend/tsconfig.app.json` — App-specific TS config (extends base)
- `frontend/tsconfig.node.json` — Node/Vite-specific TS config
- `frontend/index.html` — SPA entry point
- `frontend/env.d.ts` — Vite client type declarations

#### Source

- `frontend/src/main.ts` — Vue app bootstrap (createApp, router, pinia)
- `frontend/src/App.vue` — Root component (mounts AppLayout)
- `frontend/src/style.css` — Tailwind import (`@import "tailwindcss"`)
- `frontend/src/router.ts` — Vue Router config (4 routes)

#### Types

- `frontend/src/types/index.ts` — All TypeScript interfaces matching Pydantic models

#### API Client

- `frontend/src/api/client.ts` — Base fetch wrapper with error handling
- `frontend/src/api/catalog.ts` — Catalog API calls
- `frontend/src/api/queue.ts` — Queue API calls
- `frontend/src/api/watcher.ts` — Watcher API calls
- `frontend/src/api/discovery.ts` — Discovery API calls
- `frontend/src/api/agent.ts` — Agent health/status API calls

#### Stores (Pinia)

- `frontend/src/stores/catalog.ts` — Posts, filters, pagination, stats
- `frontend/src/stores/agent.ts` — Agent health, status, polling
- `frontend/src/stores/websocket.ts` — WebSocket connection + event distribution

#### Layout

- `frontend/src/components/AppLayout.vue` — Sidebar + content area wrapper

#### Dashboard View + Components

- `frontend/src/views/DashboardView.vue` — Dashboard page composing subcomponents
- `frontend/src/components/dashboard/StatsCards.vue` — Total posts, videos, transcribed, pending, failed
- `frontend/src/components/dashboard/AgentHealthBadge.vue` — obs-machine health (green/yellow/red dot, polls every 30s)
- `frontend/src/components/dashboard/PipelineOverview.vue` — Step-by-step horizontal funnel bar
- `frontend/src/components/dashboard/RecentActivity.vue` — Last 10 WebSocket events
- `frontend/src/components/dashboard/QuickActions.vue` — Discover Now, View Queue, Open Catalog buttons

#### Placeholder Views

- `frontend/src/views/CatalogView.vue` — Placeholder with title
- `frontend/src/views/QueueView.vue` — Placeholder with title
- `frontend/src/views/WatcherView.vue` — Placeholder with title

#### Shared Components

- `frontend/src/components/shared/StatusBadge.vue` — Color-coded status badge
- `frontend/src/components/shared/PostTypeIcon.vue` — Icon for video/audio/podcast/text
- `frontend/src/components/shared/DurationDisplay.vue` — Formats seconds to "1h 23m"
- `frontend/src/components/shared/DateDisplay.vue` — Relative/absolute date display
- `frontend/src/components/shared/LoadingSpinner.vue` — Loading indicator
- `frontend/src/components/shared/EmptyState.vue` — "No data" message with icon

---

## Implementation Phases

### Phase 1: Foundation (Steps 1-4)
Scaffold the project, install deps, configure Vite/Tailwind/Router/Pinia, define TypeScript types.

### Phase 2: Core Infrastructure (Steps 5-7)
Build the API client layer, Pinia stores (catalog, agent, websocket), and the app layout shell.

### Phase 3: Dashboard View (Steps 8-11)
Build all Dashboard subcomponents: StatsCards, AgentHealthBadge, PipelineOverview, RecentActivity, QuickActions. Wire to stores and API.

### Phase 4: Shared Components + Validation (Steps 12-13)
Build reusable shared components and validate the full build.

---

## Step by Step Tasks

IMPORTANT: Execute every step in order, top to bottom.

### 1. Scaffold Vite + Vue 3 Project

- Create the `frontend/` directory at the repo root
- Run:
  ```bash
  cd /home/tuna/repos/media-transcribe
  npm create vite@latest frontend -- --template vue-ts
  ```
- This generates the boilerplate: `package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`, `src/main.ts`, `src/App.vue`, etc.
- Remove the generated boilerplate files we'll replace: `src/components/HelloWorld.vue`, `src/assets/vue.svg`, any default `src/style.css` content

### 2. Install Dependencies

- From the `frontend/` directory:
  ```bash
  cd frontend
  npm install vue-router@4 pinia @vueuse/core
  npm install -D tailwindcss @tailwindcss/vite
  ```

### 3. Configure Vite

- Replace `frontend/vite.config.ts` with:
  ```typescript
  import { defineConfig } from 'vite'
  import vue from '@vitejs/plugin-vue'
  import tailwindcss from '@tailwindcss/vite'

  export default defineConfig({
    plugins: [vue(), tailwindcss()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://localhost:8420',
          changeOrigin: true,
        },
        '/ws': {
          target: 'ws://localhost:8420',
          ws: true,
        },
      },
    },
  })
  ```

### 4. Configure Tailwind CSS

- Replace `frontend/src/style.css` with:
  ```css
  @import "tailwindcss";
  ```
- Ensure `style.css` is imported in `main.ts`

### 5. Create TypeScript Interfaces

- Create `frontend/src/types/index.ts` matching every Pydantic model in `web/models.py`. The interfaces must include:

  ```typescript
  export interface StepStatusResponse {
    status: string
    started_at: string | null
    completed_at: string | null
    error: string | null
    output_path: string | null
    duration_seconds: number | null
    attempt: number
  }

  export interface PostSummary {
    post_id: string
    source_id: string
    url: string
    title: string
    published_at: string | null
    post_type: string
    has_video: boolean
    has_audio: boolean
    duration_seconds: number | null
    thumbnail_url: string | null
    tags: string[]
    overall_status: string
    steps: Record<string, StepStatusResponse>
  }

  export interface PostDetail extends PostSummary {
    created_at: string | null
    edited_at: string | null
    embed_url: string | null
    embed_provider: string | null
    like_count: number | null
    comment_count: number | null
    is_paid: boolean | null
    min_cents_pledged_to_view: number | null
    discovered_at: string | null
    recording_mb: number | null
    transcript_words: number | null
    output_path: string | null
  }

  export interface QueueEntry {
    post_id: string
    title: string
    priority: number
    added_at: string
    status: string
  }

  export interface WatcherStatus {
    running: boolean
    pid: number | null
    cycle: number
    interval_hours: number
    last_run: string | null
    next_run: string | null
    last_result: Record<string, unknown>
    total_recorded: number
  }

  export interface AgentHealth {
    healthy: boolean
    obs_connected: boolean
    chrome_available: boolean
    disk_ok: boolean
    obs_version: string | null
    error: string | null
  }

  export interface CatalogStats {
    total_posts: number
    video_posts: number
    audio_posts: number
    by_status: Record<string, number>
    by_type: Record<string, number>
    by_step: Record<string, Record<string, number>>
  }

  export interface WebSocketEvent {
    type: string
    data: Record<string, unknown>
    timestamp: string
  }

  export interface PaginatedPosts {
    posts: PostSummary[]
    total: number
    page: number
    per_page: number
  }

  export interface DiscoveryRunResponse {
    id: number | null
    started_at: string
    completed_at: string | null
    posts_found: number
    new_posts: number
    source: string
    status: string
  }

  // Pipeline steps constant — mirrors web/lifecycle.py PIPELINE_STEPS
  export const PIPELINE_STEPS = [
    'record', 'analyze', 'transcribe', 'correct',
    'find_gaps', 'extract_frames', 'ocr',
  ] as const

  export type PipelineStep = typeof PIPELINE_STEPS[number]
  ```

### 6. Create API Client Layer

- Create `frontend/src/api/client.ts`:
  ```typescript
  // Base fetch wrapper — all API calls go through this.
  // In dev, Vite proxies /api to localhost:8420.
  // In prod, same origin serves both static files and API.

  export class ApiError extends Error {
    constructor(public status: number, message: string) {
      super(message)
    }
  }

  async function request<T>(path: string, options?: RequestInit): Promise<T> {
    const res = await fetch(path, {
      headers: { 'Content-Type': 'application/json', ...options?.headers },
      ...options,
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }))
      throw new ApiError(res.status, body.detail || res.statusText)
    }
    return res.json()
  }

  export const api = {
    get: <T>(path: string) => request<T>(path),
    post: <T>(path: string, body?: unknown) =>
      request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
    patch: <T>(path: string, body: unknown) =>
      request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
    delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  }
  ```

- Create `frontend/src/api/catalog.ts`:
  ```typescript
  import type { CatalogStats, PaginatedPosts, PostDetail } from '../types'
  import { api } from './client'

  export interface CatalogFilters {
    type?: string
    status?: string
    step?: string
    search?: string
    tag?: string
    source_id?: string
    sort?: string
    order?: 'asc' | 'desc'
    page?: number
    per_page?: number
  }

  export const catalogApi = {
    list(filters: CatalogFilters = {}) {
      const params = new URLSearchParams()
      for (const [k, v] of Object.entries(filters)) {
        if (v !== undefined && v !== null && v !== '') params.set(k, String(v))
      }
      const qs = params.toString()
      return api.get<PaginatedPosts>(`/api/catalog${qs ? '?' + qs : ''}`)
    },
    get(postId: string) {
      return api.get<PostDetail>(`/api/catalog/${postId}`)
    },
    stats() {
      return api.get<CatalogStats>('/api/catalog/stats')
    },
    importCatalog(jsonPath?: string) {
      return api.post<{ imported: number }>('/api/catalog/import', { json_path: jsonPath ?? null })
    },
  }
  ```

- Create `frontend/src/api/queue.ts`:
  ```typescript
  import type { QueueEntry } from '../types'
  import { api } from './client'

  export const queueApi = {
    list: () => api.get<QueueEntry[]>('/api/queue'),
    add: (postIds: string[], priority = 0) =>
      api.post<{ added: number }>('/api/queue', { post_ids: postIds, priority }),
    remove: (postId: string) => api.delete<{ removed: boolean }>(`/api/queue/${postId}`),
    updatePriority: (postId: string, priority: number) =>
      api.patch<{ ok: boolean }>(`/api/queue/${postId}`, { priority }),
    reorder: (postIds: string[]) =>
      api.post<{ ok: boolean }>('/api/queue/reorder', { post_ids: postIds }),
    start: () => api.post<Record<string, unknown>>('/api/queue/start'),
    pause: () => api.post<{ ok: boolean }>('/api/queue/pause'),
    clear: () => api.post<{ ok: boolean }>('/api/queue/clear'),
  }
  ```

- Create `frontend/src/api/watcher.ts`:
  ```typescript
  import type { WatcherStatus } from '../types'
  import { api } from './client'

  export const watcherApi = {
    status: () => api.get<WatcherStatus>('/api/watcher/status'),
    start: (config: { interval_hours?: number; max_per_run?: number; steps?: string[] }) =>
      api.post<Record<string, unknown>>('/api/watcher/start', config),
    stop: () => api.post<Record<string, unknown>>('/api/watcher/stop'),
    updateConfig: (config: { interval_hours?: number; max_per_run?: number; steps?: string[] }) =>
      api.patch<Record<string, unknown>>('/api/watcher/config', config),
  }
  ```

- Create `frontend/src/api/discovery.ts`:
  ```typescript
  import type { DiscoveryRunResponse, PostSummary } from '../types'
  import { api } from './client'

  export const discoveryApi = {
    trigger: (fullCatalog = false, force = false) =>
      api.post<DiscoveryRunResponse>('/api/discovery/trigger', { full_catalog: fullCatalog, force }),
    history: () => api.get<DiscoveryRunResponse[]>('/api/discovery/history'),
    newPosts: () => api.get<PostSummary[]>('/api/discovery/new'),
  }
  ```

- Create `frontend/src/api/agent.ts`:
  ```typescript
  import type { AgentHealth } from '../types'
  import { api } from './client'

  export const agentApi = {
    health: () => api.get<AgentHealth>('/api/agent/health'),
    status: () => api.get<Record<string, unknown>>('/api/agent/status'),
  }
  ```

### 7. Create Pinia Stores

- Create `frontend/src/stores/catalog.ts`:
  ```typescript
  import { defineStore } from 'pinia'
  import { ref } from 'vue'
  import type { CatalogStats, PostSummary, PostDetail, PaginatedPosts } from '../types'
  import { catalogApi, type CatalogFilters } from '../api/catalog'

  export const useCatalogStore = defineStore('catalog', () => {
    const posts = ref<PostSummary[]>([])
    const total = ref(0)
    const page = ref(1)
    const perPage = ref(50)
    const stats = ref<CatalogStats | null>(null)
    const loading = ref(false)
    const currentPost = ref<PostDetail | null>(null)

    async function fetchPosts(filters: CatalogFilters = {}) {
      loading.value = true
      try {
        const data = await catalogApi.list({
          page: page.value,
          per_page: perPage.value,
          ...filters,
        })
        posts.value = data.posts
        total.value = data.total
        page.value = data.page
      } finally {
        loading.value = false
      }
    }

    async function fetchStats() {
      stats.value = await catalogApi.stats()
    }

    async function fetchPost(id: string) {
      currentPost.value = await catalogApi.get(id)
    }

    return { posts, total, page, perPage, stats, loading, currentPost, fetchPosts, fetchStats, fetchPost }
  })
  ```

- Create `frontend/src/stores/agent.ts`:
  ```typescript
  import { defineStore } from 'pinia'
  import { ref, onUnmounted } from 'vue'
  import type { AgentHealth } from '../types'
  import { agentApi } from '../api/agent'

  export const useAgentStore = defineStore('agent', () => {
    const health = ref<AgentHealth | null>(null)
    const status = ref<Record<string, unknown> | null>(null)
    const lastChecked = ref<string | null>(null)
    const loading = ref(false)
    let pollInterval: ReturnType<typeof setInterval> | null = null

    async function fetchHealth() {
      loading.value = true
      try {
        health.value = await agentApi.health()
        lastChecked.value = new Date().toISOString()
      } catch {
        health.value = {
          healthy: false,
          obs_connected: false,
          chrome_available: false,
          disk_ok: false,
          error: 'Failed to reach API',
          obs_version: null,
        }
      } finally {
        loading.value = false
      }
    }

    async function fetchStatus() {
      status.value = await agentApi.status()
    }

    function startPolling(intervalMs = 30_000) {
      fetchHealth()
      pollInterval = setInterval(fetchHealth, intervalMs)
    }

    function stopPolling() {
      if (pollInterval) {
        clearInterval(pollInterval)
        pollInterval = null
      }
    }

    return { health, status, lastChecked, loading, fetchHealth, fetchStatus, startPolling, stopPolling }
  })
  ```

- Create `frontend/src/stores/websocket.ts`:
  ```typescript
  import { defineStore } from 'pinia'
  import { ref } from 'vue'
  import type { WebSocketEvent } from '../types'

  export const useWebSocketStore = defineStore('websocket', () => {
    const connected = ref(false)
    const recentEvents = ref<WebSocketEvent[]>([])
    const maxEvents = 50
    let ws: WebSocket | null = null
    let reconnectDelay = 1000
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    function getWsUrl(): string {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
      return `${proto}//${location.host}/ws/events`
    }

    function connect() {
      if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return

      ws = new WebSocket(getWsUrl())

      ws.onopen = () => {
        connected.value = true
        reconnectDelay = 1000
      }

      ws.onmessage = (event) => {
        const data: WebSocketEvent = JSON.parse(event.data)
        if (data.type === 'ping') return
        recentEvents.value.unshift(data)
        if (recentEvents.value.length > maxEvents) {
          recentEvents.value = recentEvents.value.slice(0, maxEvents)
        }
      }

      ws.onclose = () => {
        connected.value = false
        scheduleReconnect()
      }

      ws.onerror = () => {
        ws?.close()
      }
    }

    function scheduleReconnect() {
      if (reconnectTimer) return
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null
        reconnectDelay = Math.min(reconnectDelay * 2, 30_000)
        connect()
      }, reconnectDelay)
    }

    function disconnect() {
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
      ws?.close()
      ws = null
      connected.value = false
    }

    return { connected, recentEvents, connect, disconnect }
  })
  ```

### 8. Configure Vue Router

- Create `frontend/src/router.ts`:
  ```typescript
  import { createRouter, createWebHistory } from 'vue-router'
  import DashboardView from './views/DashboardView.vue'

  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: DashboardView },
      { path: '/catalog', name: 'catalog', component: () => import('./views/CatalogView.vue') },
      { path: '/queue', name: 'queue', component: () => import('./views/QueueView.vue') },
      { path: '/watcher', name: 'watcher', component: () => import('./views/WatcherView.vue') },
    ],
  })

  export default router
  ```

### 9. Create App Entry Point and Root Component

- Replace `frontend/src/main.ts`:
  ```typescript
  import { createApp } from 'vue'
  import { createPinia } from 'pinia'
  import App from './App.vue'
  import router from './router'
  import './style.css'

  const app = createApp(App)
  app.use(createPinia())
  app.use(router)
  app.mount('#app')
  ```

- Replace `frontend/src/App.vue`:
  ```vue
  <script setup lang="ts">
  import AppLayout from './components/AppLayout.vue'
  </script>

  <template>
    <AppLayout />
  </template>
  ```

### 10. Build App Layout (Sidebar + Content)

- Create `frontend/src/components/AppLayout.vue`:
  - Dark sidebar (`bg-gray-900`, `w-64`, full height, fixed) on the left
  - "Insights" title at the top of the sidebar in `text-white text-xl font-bold`
  - Navigation links: Dashboard, Catalog, Queue, Watcher — each a `<router-link>` with active state styling (`bg-gray-800 text-white` when active, `text-gray-400 hover:text-white hover:bg-gray-800` when inactive)
  - Each nav link has an inline SVG icon (simple geometric shapes: grid for Dashboard, list for Catalog, queue bars for Queue, eye for Watcher)
  - Light content area (`bg-gray-50 min-h-screen ml-64 p-8`) on the right containing `<router-view />`

  Layout structure:
  ```html
  <div class="flex min-h-screen">
    <!-- Sidebar -->
    <aside class="fixed inset-y-0 left-0 w-64 bg-gray-900 flex flex-col">
      <div class="px-6 py-6">
        <h1 class="text-xl font-bold text-white tracking-tight">Insights</h1>
        <p class="text-xs text-gray-500 mt-1">Pipeline Dashboard</p>
      </div>
      <nav class="flex-1 px-3 space-y-1">
        <!-- router-links here -->
      </nav>
    </aside>
    <!-- Content -->
    <main class="ml-64 flex-1 bg-gray-50 min-h-screen p-8">
      <router-view />
    </main>
  </div>
  ```

### 11. Build Dashboard View

- Create `frontend/src/views/DashboardView.vue`:
  - On mount: fetch catalog stats, start agent health polling, connect WebSocket
  - On unmount: stop polling (WebSocket stays connected for the app lifetime)
  - Layout:
    ```html
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
    ```

### 12. Build StatsCards Component

- Create `frontend/src/components/dashboard/StatsCards.vue`:
  - Uses `useCatalogStore()` to read `stats`
  - Displays 5 stat cards in a responsive grid (`grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4`)
  - Each card is a white rounded box (`bg-white rounded-lg shadow-sm border border-gray-200 p-5`)
  - Cards:
    1. **Total Posts** — `stats.total_posts` — icon: document stack — text-blue-600
    2. **Videos** — `stats.video_posts` — icon: play circle — text-indigo-600
    3. **Completed** — `stats.by_status.completed ?? 0` — icon: check circle — text-green-600
    4. **Pending** — `stats.by_status.discovered ?? 0` (posts not yet started) — icon: clock — text-amber-500
    5. **Failed** — `stats.by_status.failed ?? 0` — icon: exclamation circle — text-red-600
  - Each card shows: small icon + label on top, large number below (`text-3xl font-bold`)
  - Show `LoadingSpinner` if stats is null

### 13. Build AgentHealthBadge Component

- Create `frontend/src/components/dashboard/AgentHealthBadge.vue`:
  - Uses `useAgentStore()` to read `health` and `lastChecked`
  - Card container: `bg-white rounded-lg shadow-sm border border-gray-200 p-5`
  - Title: "Agent Status" with a colored dot indicator:
    - Green (`bg-green-500`) pulsing dot — `health.healthy === true`
    - Yellow (`bg-yellow-500`) — partially healthy (e.g., `healthy` but one subsystem down)
    - Red (`bg-red-500`) — `health.healthy === false` or `health === null`
  - Below the dot/status, show 3 sub-indicators as rows:
    - OBS: connected/disconnected
    - Chrome: available/unavailable
    - Disk: OK / low space
  - Each sub-indicator: icon + label + status text + colored dot
  - Show `lastChecked` as relative time at the bottom (e.g., "Updated 15s ago")
  - If `health` is null, show "Connecting..." with `LoadingSpinner`

### 14. Build PipelineOverview Component

- Create `frontend/src/components/dashboard/PipelineOverview.vue`:
  - Uses `useCatalogStore()` to read `stats.by_step`
  - Card container: `bg-white rounded-lg shadow-sm border border-gray-200 p-5`
  - Title: "Pipeline Funnel"
  - Displays a horizontal bar chart for each pipeline step (record, analyze, transcribe, correct, find_gaps, extract_frames, ocr)
  - Each step row shows:
    - Step name on the left (capitalize, replace underscores: "Record", "Analyze", "Find Gaps", etc.)
    - Horizontal stacked bar on the right showing proportions of pending/completed/failed/running
    - Color segments: green for completed, gray for pending, red for failed, blue for running
    - Count labels to the right of the bar
  - Implementation: for each step, read `stats.by_step[stepName]` which returns `{ pending: N, completed: N, failed: N, ... }`
  - Calculate widths as percentages of total posts
  - If `stats` is null, show `LoadingSpinner`

### 15. Build RecentActivity Component

- Create `frontend/src/components/dashboard/RecentActivity.vue`:
  - Uses `useWebSocketStore()` to read `recentEvents`
  - Card container: `bg-white rounded-lg shadow-sm border border-gray-200 p-5`
  - Title: "Recent Activity" with a green/gray dot indicating WebSocket connection state
  - Lists last 10 events (filter `recentEvents` to exclude pings, take first 10)
  - Each event row shows:
    - Icon based on event type (check for completed, x for failed, arrow for started)
    - Event description: e.g., "Transcription completed for Masterclass 19"
    - Relative timestamp (e.g., "2m ago")
  - Format event descriptions based on `type`:
    - `step_completed` → "{step} completed for {post title or post_id}" — green text
    - `step_failed` → "{step} failed for {post title or post_id}" — red text
    - `step_started` → "{step} started for {post title or post_id}" — blue text
    - `pipeline_complete` → "Pipeline run completed" — green text
    - `discovery_complete` → "Discovery found {N} new posts" — indigo text
    - `watcher_cycle` → "Watcher cycle {N} completed" — gray text
    - Default → raw type string
  - If no events, show `EmptyState` with "No recent activity" message

### 16. Build QuickActions Component

- Create `frontend/src/components/dashboard/QuickActions.vue`:
  - Card container: `bg-white rounded-lg shadow-sm border border-gray-200 p-5`
  - Title: "Quick Actions"
  - 3 buttons stacked vertically with `space-y-3`:
    1. **Discover Now** — calls `discoveryApi.trigger()` — indigo button (`bg-indigo-600 hover:bg-indigo-700 text-white`)
    2. **View Queue** — navigates to `/queue` via `router.push` — white button (`bg-white border border-gray-300 hover:bg-gray-50 text-gray-700`)
    3. **Open Catalog** — navigates to `/catalog` via `router.push` — white button (same style)
  - "Discover Now" shows a loading spinner while the request is in flight, then briefly shows the result ("Found N new posts") before resetting
  - All buttons are full-width (`w-full`), rounded (`rounded-lg`), padded (`px-4 py-2.5`)

### 17. Build Shared Components

- Create `frontend/src/components/shared/StatusBadge.vue`:
  - Props: `status: string`
  - Renders a small badge (`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium`)
  - Color map:
    - `completed` → `bg-green-100 text-green-800`
    - `in_progress` / `running` → `bg-blue-100 text-blue-800`
    - `failed` → `bg-red-100 text-red-800`
    - `pending` / `discovered` → `bg-gray-100 text-gray-800`
    - `queued` → `bg-yellow-100 text-yellow-800`
    - `skipped` → `bg-gray-100 text-gray-500`
    - `partial` → `bg-amber-100 text-amber-800`

- Create `frontend/src/components/shared/PostTypeIcon.vue`:
  - Props: `type: string`
  - Renders an inline SVG icon (16x16) based on post type:
    - `video_external_file` → play icon (triangle in circle)
    - `video_embed` → play icon variant
    - `podcast` / `audio` → music note
    - Default → document icon

- Create `frontend/src/components/shared/DurationDisplay.vue`:
  - Props: `seconds: number | null`
  - Renders formatted duration: if `seconds` is null → "—", else format as "Xh Ym" or "Ym Zs" depending on magnitude

- Create `frontend/src/components/shared/DateDisplay.vue`:
  - Props: `date: string | null`, `relative: boolean = true`
  - If `relative` is true, render relative time (e.g., "3 days ago", "just now")
  - If false, render formatted date ("Sep 13, 2026")
  - If `date` is null, render "—"
  - Use simple date math — no external library

- Create `frontend/src/components/shared/LoadingSpinner.vue`:
  - Props: `size: 'sm' | 'md' | 'lg'` (default `'md'`)
  - Renders an animated spinner SVG with `animate-spin` class
  - Size map: sm → `h-4 w-4`, md → `h-6 w-6`, lg → `h-10 w-10`
  - Color: `text-indigo-600`

- Create `frontend/src/components/shared/EmptyState.vue`:
  - Props: `message: string`, `icon?: string` (default: empty box)
  - Centered layout with a muted icon and the message text below
  - Styling: `text-center py-12 text-gray-500`

### 18. Create Placeholder Views

- Create `frontend/src/views/CatalogView.vue`:
  ```vue
  <template>
    <div>
      <h2 class="text-2xl font-semibold text-gray-900 mb-6">Catalog</h2>
      <p class="text-gray-500">Catalog browser coming soon.</p>
    </div>
  </template>
  ```

- Create `frontend/src/views/QueueView.vue`:
  ```vue
  <template>
    <div>
      <h2 class="text-2xl font-semibold text-gray-900 mb-6">Queue</h2>
      <p class="text-gray-500">Queue management coming soon.</p>
    </div>
  </template>
  ```

- Create `frontend/src/views/WatcherView.vue`:
  ```vue
  <template>
    <div>
      <h2 class="text-2xl font-semibold text-gray-900 mb-6">Watcher</h2>
      <p class="text-gray-500">Watcher dashboard coming soon.</p>
    </div>
  </template>
  ```

### 19. Validate the Build

- Run the following commands to verify everything compiles and builds:
  ```bash
  cd /home/tuna/repos/media-transcribe/frontend
  npm run build
  ```
- Fix any TypeScript errors or build failures
- Verify the `dist/` directory is created with `index.html`, JS, and CSS assets

---

## Testing Strategy

### Manual Testing (Primary)

Since this is a frontend scaffolding step, testing is primarily manual:

1. **Dev server**: `cd frontend && npm run dev` — verify Vite starts on `:5173`
2. **Navigation**: Click all sidebar links — Dashboard, Catalog, Queue, Watcher — verify routing works
3. **Stats cards**: With backend running (`uv run cli.py web`), dashboard should load stats from `/api/catalog/stats`
4. **Agent health**: Badge should show red (agent unreachable) or green (if agent server is running on obs-machine)
5. **WebSocket**: Green/gray dot in RecentActivity should reflect connection state
6. **Quick Actions**: "Discover Now" button should trigger discovery API call
7. **Responsive**: Resize browser — verify grid layout adapts (5 → 3 → 2 columns for stat cards)
8. **Build**: `npm run build` produces error-free output in `dist/`

### Type Safety

TypeScript strict mode catches interface mismatches between frontend types and backend API responses. No runtime type tests needed — the TS compiler is the test.

### Future Tests

Component-level tests with Vitest + Vue Test Utils will be added when building Catalog/Queue/Watcher views (Steps 17-18 of the master plan). Not in scope for this plan.

---

## Acceptance Criteria

1. `cd frontend && npm run build` succeeds with zero errors
2. `cd frontend && npm run dev` starts Vite dev server on `:5173`
3. API proxy works: requests to `/api/catalog/stats` from the frontend reach FastAPI on `:8420`
4. WebSocket proxy works: connection to `/ws/events` from the frontend reaches FastAPI's WebSocket endpoint
5. Dashboard view renders with StatsCards, AgentHealthBadge, PipelineOverview, RecentActivity, QuickActions
6. Stats cards display counts from the backend API (or zeros if DB is empty)
7. AgentHealthBadge polls `/api/agent/health` every 30 seconds and updates the dot color
8. PipelineOverview shows per-step funnel bars from `stats.by_step`
9. RecentActivity shows WebSocket events in real-time (or "No recent activity" if none)
10. QuickActions "Discover Now" button calls the discovery API; "View Queue" and "Open Catalog" navigate correctly
11. Sidebar navigation works for all 4 routes (Dashboard, Catalog, Queue, Watcher)
12. Dark sidebar (`bg-gray-900`) + light content area (`bg-gray-50`) layout matches the design spec
13. All Pydantic models from `web/models.py` have matching TypeScript interfaces
14. No Python files are modified
15. Tailwind utility classes only — no custom CSS classes

## Validation Commands

Execute these commands to validate the task is complete:

- `cd /home/tuna/repos/media-transcribe/frontend && npm run build` — Verify production build succeeds
- `cd /home/tuna/repos/media-transcribe/frontend && npx vue-tsc --noEmit` — Verify TypeScript type checking passes
- `ls /home/tuna/repos/media-transcribe/frontend/dist/index.html` — Verify built assets exist
- `cd /home/tuna/repos/media-transcribe/frontend && npm run dev &; sleep 3; curl -s http://localhost:5173/ | head -20` — Verify dev server starts and serves HTML
- `cd /home/tuna/repos/media-transcribe && uv run cli.py web &; sleep 3; cd frontend && npm run dev &; sleep 3; curl -s http://localhost:5173/api/catalog/stats` — Verify API proxy reaches FastAPI

## Notes

- **Node.js**: v24.14.1 and npm 11.11.0 are available on devbox-01
- **Tailwind v4**: Uses the `@tailwindcss/vite` plugin and `@import "tailwindcss"` in CSS — no `tailwind.config.js` needed (v4 auto-detects content files)
- **No component library**: All UI is built with raw Tailwind utility classes — no Headless UI, no shadcn, no Vuetify
- **Icons**: Use inline SVG elements directly in templates — no icon library dependency. Keep icons simple (heroicons-style outlines as path data)
- **WebSocket reconnect**: Exponential backoff starting at 1s, max 30s. Ping events from server every 30s keep the connection alive
- **API base URL**: In dev, Vite proxy handles `/api` → `:8420`. In prod, FastAPI serves static files from `frontend/dist/` at the same origin — no CORS needed
- **`@vueuse/core`**: Installed for later use by Queue/Watcher views (drag utilities, etc.). Not used by Dashboard but bundled now to avoid a second install step
