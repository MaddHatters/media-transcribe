# Plan: Frontend Views — Catalog Browser, Queue Manager, Watcher Dashboard

## Task Description

Build the three remaining frontend views for the media-transcribe pipeline dashboard: Catalog Browser, Queue Manager, and Watcher Dashboard — plus upgrade WebSocket integration to dispatch events across stores and show toast notifications. This covers Steps 17–19 from `specs/media-transcribe-web-app.md`.

**Task type:** Feature
**Complexity:** Complex

## Objective

When complete, the Vue 3 SPA will have four fully functional views:
1. **Catalog Browser** — browse 1,640+ posts with rich filtering, per-step status badges, sortable columns, pagination, and a detail modal with step timeline
2. **Queue Manager** — drag-to-reorder queue with Start/Pause/Clear controls and a search-add panel
3. **Watcher Dashboard** — watcher status/controls, cycle history timeline, and a discovery feed with "Add to Queue" cards
4. **WebSocket integration** — event dispatch to all stores, toast notifications, connection indicator in sidebar

## Problem Statement

The frontend project is scaffolded with a working Dashboard view, shared components, API clients, types, and a WebSocket store with reconnection — but the Catalog, Queue, and Watcher routes are stubs (`"coming soon"` placeholders). The WebSocket store collects events but doesn't dispatch them to other stores.

## Solution Approach

Build each view as a composition of focused, single-responsibility child components following the patterns established in the Dashboard view (Tailwind utility classes, `bg-white rounded-lg shadow-sm border border-gray-200` card pattern, `text-sm font-semibold text-gray-900` headers). Use the existing API client modules and Pinia stores, adding `queue.ts` and `watcher.ts` stores. Install `vue-draggable-plus` for drag-to-reorder. Extend the WebSocket store to dispatch events to other stores and power a toast system.

### Design Patterns (from existing code)

- **Store pattern**: Composition API (`defineStore` with `() => {}` setup), `ref()` state, `async` actions, no getters-only computed
- **API calls**: Through dedicated `api/*.ts` modules using the `api` helper (`api.get<T>()`, `api.post<T>()`, etc.)
- **Card layout**: `bg-white rounded-lg shadow-sm border border-gray-200 p-5`
- **Section headers**: `text-sm font-semibold text-gray-900 mb-4`
- **Icons**: Inline Heroicons (SVG paths) within components
- **Loading**: `LoadingSpinner` component + `loading` ref in stores
- **Empty state**: `EmptyState` component with message prop
- **Tailwind**: v4 (`@import "tailwindcss"`), no config file needed, use `@theme` for custom values if necessary

---

## Relevant Files

### Existing Files (read-only context)

- `frontend/src/types/index.ts` — TypeScript interfaces (`PostSummary`, `PostDetail`, `StepStatusResponse`, `QueueEntry`, `WatcherStatus`, `CatalogStats`, `PaginatedPosts`, `DiscoveryRunResponse`, `PIPELINE_STEPS`)
- `frontend/src/api/client.ts` — Base API wrapper (`api.get/post/patch/delete`)
- `frontend/src/api/catalog.ts` — `catalogApi` with `list(filters)`, `get(postId)`, `stats()`, `importCatalog()`; `CatalogFilters` interface
- `frontend/src/api/queue.ts` — `queueApi` with `list`, `add`, `remove`, `updatePriority`, `reorder`, `start`, `pause`, `clear`
- `frontend/src/api/watcher.ts` — `watcherApi` with `status`, `start`, `stop`, `updateConfig`
- `frontend/src/api/discovery.ts` — `discoveryApi` with `trigger`, `history`, `newPosts`
- `frontend/src/api/agent.ts` — `agentApi` with `health`, `status`
- `frontend/src/stores/catalog.ts` — `useCatalogStore` with `posts`, `total`, `page`, `perPage`, `stats`, `loading`, `currentPost`, `fetchPosts`, `fetchStats`, `fetchPost`
- `frontend/src/stores/agent.ts` — `useAgentStore` with polling
- `frontend/src/stores/websocket.ts` — `useWebSocketStore` with auto-connect, exponential backoff reconnect, `recentEvents`
- `frontend/src/components/shared/` — `StatusBadge`, `PostTypeIcon`, `DurationDisplay`, `DateDisplay`, `LoadingSpinner`, `EmptyState`
- `frontend/src/components/AppLayout.vue` — Sidebar nav + main content
- `frontend/src/router.ts` — Routes (catalog/queue/watcher already registered as lazy imports)
- `frontend/src/views/DashboardView.vue` — Reference for view composition patterns
- `frontend/src/components/dashboard/` — Reference for component patterns (StatsCards, AgentHealthBadge, etc.)
- `frontend/package.json` — Current deps (vue 3.5, vue-router 4, pinia 4, @vueuse/core 14, tailwindcss 4)

### New Files

#### Catalog Browser Components
- `frontend/src/views/CatalogView.vue` — **(replace stub)** Catalog browser view composing FilterBar, CatalogTable, PaginationBar, PostDetailModal
- `frontend/src/components/catalog/FilterBar.vue` — Filter controls: type dropdown, status dropdown, step+status dropdown, search input, date range, tag input
- `frontend/src/components/catalog/CatalogTable.vue` — Sortable table of posts; columns: title, type, published date, overall status, 7 step badges
- `frontend/src/components/catalog/CatalogRow.vue` — Single table row with inline StepBadge instances for all 7 pipeline steps
- `frontend/src/components/catalog/StepBadge.vue` — Colored dot/badge per step status (gray=pending, blue=queued, yellow+pulse=running, green=completed, red=failed, gray+line-through=skipped)
- `frontend/src/components/catalog/PostDetailModal.vue` — Modal overlay with full post detail: metadata, step timeline, error messages, action buttons
- `frontend/src/components/catalog/StepTimeline.vue` — Vertical timeline of all 7 steps with timestamps, durations, output paths, errors
- `frontend/src/components/catalog/PaginationBar.vue` — Page numbers, per-page selector (25/50/100), total count

#### Queue View Components
- `frontend/src/views/QueueView.vue` — **(replace stub)** Queue manager composing QueueControls, QueueList, AddToQueuePanel
- `frontend/src/components/queue/QueueControls.vue` — Start/Pause/Clear buttons + processing status indicator
- `frontend/src/components/queue/QueueList.vue` — Draggable queue list using `vue-draggable-plus`
- `frontend/src/components/queue/QueueItem.vue` — Single queue entry with title, priority badge, status, remove button, drag handle
- `frontend/src/components/queue/AddToQueuePanel.vue` — Search catalog posts + bulk add to queue

#### Watcher View Components
- `frontend/src/views/WatcherView.vue` — **(replace stub)** Watcher dashboard composing status, controls, timeline, discovery feed
- `frontend/src/components/watcher/WatcherStatus.vue` — Running/stopped indicator, PID, interval, cycle count, next run countdown
- `frontend/src/components/watcher/WatcherControls.vue` — Start/Stop toggle, interval selector, max-per-run input, step checkboxes
- `frontend/src/components/watcher/WatcherTimeline.vue` — History table of watcher cycles with found/recorded/failed counts
- `frontend/src/components/watcher/DiscoveryFeed.vue` — Grid of discovery cards for recently discovered posts
- `frontend/src/components/watcher/DiscoveryCard.vue` — Post card with thumbnail placeholder, title, date, type icon, "Add to Queue" button

#### New Stores
- `frontend/src/stores/queue.ts` — Queue state, entries, processing status, actions for CRUD + reorder
- `frontend/src/stores/watcher.ts` — Watcher status, config, discovery results, cycle history

#### Toast System
- `frontend/src/components/shared/ToastContainer.vue` — Fixed-position container rendering active toasts
- `frontend/src/components/shared/ToastItem.vue` — Individual toast with icon, message, auto-dismiss, close button
- `frontend/src/stores/toast.ts` — Toast state management (add/remove toasts with type, message, duration)

---

## Implementation Phases

### Phase 1: Foundation (Steps 1–3)
Install `vue-draggable-plus`. Create `queue.ts` and `watcher.ts` Pinia stores. Create toast system. Extend `websocket.ts` with event dispatch and connection indicator.

### Phase 2: Core Views (Steps 4–8)
Build all catalog components (FilterBar, CatalogTable, CatalogRow, StepBadge, PaginationBar, PostDetailModal, StepTimeline), then queue components (QueueControls, QueueList, QueueItem, AddToQueuePanel), then watcher components (WatcherStatus, WatcherControls, WatcherTimeline, DiscoveryFeed, DiscoveryCard).

### Phase 3: Integration & Polish (Steps 9–10)
Wire WebSocket events to update stores and trigger toasts. Add connection indicator to sidebar. Validate with `npm run build`.

---

## Step by Step Tasks

IMPORTANT: Execute every step in order, top to bottom.

### 1. Install vue-draggable-plus

- Run: `cd frontend && npm install vue-draggable-plus`
- This provides `<VueDraggable>` component for drag-to-reorder in the queue view

### 2. Create Toast System

Create the toast notification infrastructure used by WebSocket events and action feedback.

- Create `frontend/src/stores/toast.ts`:
  ```typescript
  import { defineStore } from 'pinia'
  import { ref } from 'vue'

  export interface Toast {
    id: number
    type: 'success' | 'error' | 'info' | 'warning'
    message: string
  }

  export const useToastStore = defineStore('toast', () => {
    const toasts = ref<Toast[]>([])
    let nextId = 0

    function add(type: Toast['type'], message: string, durationMs = 5000) {
      const id = nextId++
      toasts.value.push({ id, type, message })
      if (durationMs > 0) {
        setTimeout(() => remove(id), durationMs)
      }
    }

    function remove(id: number) {
      toasts.value = toasts.value.filter(t => t.id !== id)
    }

    return { toasts, add, remove }
  })
  ```

- Create `frontend/src/components/shared/ToastItem.vue`:
  - Renders a single toast with colored left border (green=success, red=error, blue=info, yellow=warning)
  - Close button (X) calls `remove(id)` from toast store
  - Small text, compact design consistent with existing card pattern

- Create `frontend/src/components/shared/ToastContainer.vue`:
  - Fixed position `bottom-4 right-4` z-50
  - Renders `ToastItem` for each toast in the store
  - Stacks vertically with `space-y-2`
  - Transitions: slide-in from right, fade-out on dismiss

- Mount `<ToastContainer />` in `App.vue` (alongside `<AppLayout />`)

### 3. Create Queue Store (`stores/queue.ts`)

- Create `frontend/src/stores/queue.ts`:
  ```typescript
  import { defineStore } from 'pinia'
  import { ref } from 'vue'
  import type { QueueEntry } from '../types'
  import { queueApi } from '../api/queue'

  export const useQueueStore = defineStore('queue', () => {
    const entries = ref<QueueEntry[]>([])
    const loading = ref(false)
    const processing = ref(false) // true when pipeline is actively processing the queue

    async function fetchQueue() {
      loading.value = true
      try {
        entries.value = await queueApi.list()
        // Derive processing state from entries
        processing.value = entries.value.some(e => e.status === 'processing')
      } finally {
        loading.value = false
      }
    }

    async function addToQueue(postIds: string[], priority = 0) {
      const result = await queueApi.add(postIds, priority)
      await fetchQueue()
      return result
    }

    async function removeFromQueue(postId: string) {
      await queueApi.remove(postId)
      await fetchQueue()
    }

    async function reorder(postIds: string[]) {
      await queueApi.reorder(postIds)
      await fetchQueue()
    }

    async function startQueue() {
      const result = await queueApi.start()
      processing.value = true
      await fetchQueue()
      return result
    }

    async function pauseQueue() {
      await queueApi.pause()
      processing.value = false
      await fetchQueue()
    }

    async function clearCompleted() {
      await queueApi.clear()
      await fetchQueue()
    }

    return {
      entries, loading, processing,
      fetchQueue, addToQueue, removeFromQueue, reorder,
      startQueue, pauseQueue, clearCompleted,
    }
  })
  ```

### 4. Create Watcher Store (`stores/watcher.ts`)

- Create `frontend/src/stores/watcher.ts`:
  ```typescript
  import { defineStore } from 'pinia'
  import { ref } from 'vue'
  import type { WatcherStatus, DiscoveryRunResponse, PostSummary } from '../types'
  import { watcherApi } from '../api/watcher'
  import { discoveryApi } from '../api/discovery'

  export const useWatcherStore = defineStore('watcher', () => {
    const status = ref<WatcherStatus | null>(null)
    const discoveryHistory = ref<DiscoveryRunResponse[]>([])
    const newPosts = ref<PostSummary[]>([])
    const loading = ref(false)
    const discovering = ref(false)

    async function fetchStatus() {
      loading.value = true
      try {
        status.value = await watcherApi.status()
      } catch {
        status.value = null
      } finally {
        loading.value = false
      }
    }

    async function startWatcher(config: { interval_hours?: number; max_per_run?: number; steps?: string[] }) {
      await watcherApi.start(config)
      await fetchStatus()
    }

    async function stopWatcher() {
      await watcherApi.stop()
      await fetchStatus()
    }

    async function updateConfig(config: { interval_hours?: number; max_per_run?: number; steps?: string[] }) {
      await watcherApi.updateConfig(config)
      await fetchStatus()
    }

    async function fetchDiscoveryHistory() {
      discoveryHistory.value = await discoveryApi.history()
    }

    async function fetchNewPosts() {
      newPosts.value = await discoveryApi.newPosts()
    }

    async function triggerDiscovery(fullCatalog = false) {
      discovering.value = true
      try {
        const result = await discoveryApi.trigger(fullCatalog)
        await fetchNewPosts()
        await fetchDiscoveryHistory()
        return result
      } finally {
        discovering.value = false
      }
    }

    return {
      status, discoveryHistory, newPosts, loading, discovering,
      fetchStatus, startWatcher, stopWatcher, updateConfig,
      fetchDiscoveryHistory, fetchNewPosts, triggerDiscovery,
    }
  })
  ```

### 5. Build Catalog Browser Components

This is the most important view — must be polished.

#### 5a. Create `StepBadge.vue`

- Path: `frontend/src/components/catalog/StepBadge.vue`
- Props: `status: string`, `step: string` (for tooltip)
- Renders a small colored circle (12×12px) with a tooltip showing `"{Step}: {status}"`:
  - `pending` → `bg-gray-300` (muted gray)
  - `queued` → `bg-blue-400` (blue)
  - `running` → `bg-yellow-400 animate-pulse` (yellow with pulse animation)
  - `completed` → `bg-green-500` (green)
  - `failed` → `bg-red-500` (red)
  - `skipped` → `bg-gray-300 line-through` (gray with diagonal line overlay, use a CSS pseudo-element or SVG slash)
- **Accessibility**: Each status must be visually distinguishable by shape/animation, not only color:
  - `completed` gets a tiny checkmark SVG overlay
  - `failed` gets a tiny X SVG overlay
  - `running` uses pulse animation
  - `skipped` uses a diagonal line
  - `pending` and `queued` differ by color only (both static circles, but tooltips disambiguate)
- Uses `title` attribute for native tooltip: `"Record: completed"`
- Format step name for display: `find_gaps` → `Find Gaps` (replace underscores, title-case)

#### 5b. Create `FilterBar.vue`

- Path: `frontend/src/components/catalog/FilterBar.vue`
- Emits: `@update:filters` with a `CatalogFilters` object
- Layout: horizontal flex row wrapping on mobile, `gap-3`
- Filter controls:
  1. **Type dropdown** (`<select>`) — options: All, Video, Audio, Podcast, Text (values map to `post_type` query param)
  2. **Status dropdown** (`<select>`) — options: All, Discovered, Queued, In Progress, Partial, Completed, Failed
  3. **Step filter** (`<select>`) — combined step+status selector: "Any step", "Record: pending", "Record: completed", ..., etc. (generates `step=record:pending` query param). Build options dynamically from `PIPELINE_STEPS × ['pending','completed','failed','running']`
  4. **Search input** (`<input type="text">`) — text search on title, debounced 300ms using `@vueuse/core` `useDebounceFn`
  5. **Date range** — two date inputs (`from` / `to`), filtering `published_at`
  6. **Reset button** — clears all filters back to defaults
- Styling: each control uses `rounded-md border-gray-300 text-sm` consistent with Tailwind form styling
- On any filter change, emit the full `CatalogFilters` object
- Type the filters interface to extend `CatalogFilters` from `api/catalog.ts` with `date_from` and `date_to` fields (these get mapped to query params by the API client — if the backend doesn't support them yet, include the params anyway; the backend will ignore unknown query params)

#### 5c. Create `CatalogRow.vue`

- Path: `frontend/src/components/catalog/CatalogRow.vue`
- Props: `post: PostSummary`
- Emits: `@click` (opens detail modal)
- Table row (`<tr>`) with cells:
  1. **Title** — truncated, with `PostTypeIcon` inline before title text, `cursor-pointer hover:text-indigo-600` for click feedback
  2. **Type** — post_type as short label
  3. **Published** — `<DateDisplay :date="post.published_at" :relative="false" />`
  4. **Status** — `<StatusBadge :status="post.overall_status" />`
  5. **Steps** — 7 `<StepBadge>` instances in a flex row with `gap-1`, one for each `PIPELINE_STEPS` entry, reading status from `post.steps[step]?.status ?? 'pending'`
  6. **Duration** — `<DurationDisplay :seconds="post.duration_seconds" />`
- Row has `hover:bg-gray-50` and `cursor-pointer` for the click-to-detail interaction

#### 5d. Create `CatalogTable.vue`

- Path: `frontend/src/components/catalog/CatalogTable.vue`
- Props: `posts: PostSummary[]`, `sortField: string`, `sortOrder: 'asc' | 'desc'`
- Emits: `@sort(field, order)`, `@select(post)`
- Renders `<table>` with `<thead>` and `<tbody>`:
  - Column headers: Title, Type, Published, Status, Steps (spanning 7 sub-columns), Duration
  - Clicking a sortable header emits `@sort` with toggled order
  - Active sort column shows an arrow indicator (chevron up/down SVG)
- Renders `<CatalogRow>` for each post
- Shows `<EmptyState message="No posts match your filters" />` when empty
- Shows `<LoadingSpinner>` centered when catalog store is loading

#### 5e. Create `PaginationBar.vue`

- Path: `frontend/src/components/catalog/PaginationBar.vue`
- Props: `page: number`, `perPage: number`, `total: number`
- Emits: `@update:page(n)`, `@update:perPage(n)`
- Layout: flex row with space-between
  - Left: "Showing X–Y of Z posts"
  - Center: page number buttons (1, 2, ..., ellipsis, last) — show max 7 page buttons, with ellipsis for large ranges
  - Right: per-page selector dropdown (25, 50, 100)
- Current page button highlighted with `bg-indigo-600 text-white`
- Other page buttons: `bg-white border border-gray-300 hover:bg-gray-50`

#### 5f. Create `StepTimeline.vue`

- Path: `frontend/src/components/catalog/StepTimeline.vue`
- Props: `steps: Record<string, StepStatusResponse>`
- Renders a vertical timeline (left-aligned dots connected by a line):
  - For each of the 7 `PIPELINE_STEPS`:
    - Colored dot matching StepBadge colors (left side)
    - Step name (title-cased)
    - Status badge
    - If `completed`: show `started_at → completed_at` timestamps + `duration_seconds`
    - If `failed`: show `error` message in red text, `attempt` count
    - If `completed` and `output_path`: show output path as monospace text
    - Vertical connecting line between dots (gray solid for completed transitions, gray dashed for pending)
- Timeline dots connected with `border-l-2` on the left side, dots positioned on the border

#### 5g. Create `PostDetailModal.vue`

- Path: `frontend/src/components/catalog/PostDetailModal.vue`
- Props: `post: PostDetail | null` (null = closed), `open: boolean`
- Emits: `@close`, `@add-to-queue(postId)`
- Modal overlay: `fixed inset-0 z-40 bg-black/50` backdrop + centered content panel
- Content panel: `bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto`
- Sections:
  1. **Header**: Title, close button (X), post type icon, `StatusBadge`
  2. **Metadata grid**: Published date, duration, tags (as small badges), thumbnail URL (if available, show as `<img>`), like/comment counts
  3. **Step Timeline**: `<StepTimeline :steps="post.steps" />`
  4. **Actions**: "Add to Queue" button (disabled if already queued), "View on Patreon" link (opens `post.url` in new tab)
- Close on backdrop click or Escape key (use `@vueuse/core` `onKeyStroke`)
- Fetch full `PostDetail` via `catalogStore.fetchPost(id)` when modal opens (the list view only has `PostSummary`)

#### 5h. Assemble `CatalogView.vue`

- Path: `frontend/src/views/CatalogView.vue` — **replace the stub**
- Composition:
  ```
  <h2>Catalog</h2>
  <FilterBar @update:filters="onFilter" />
  <CatalogTable :posts="..." :sortField="..." :sortOrder="..." @sort="onSort" @select="onSelect" />
  <PaginationBar :page="..." :perPage="..." :total="..." @update:page="..." @update:perPage="..." />
  <PostDetailModal :post="..." :open="..." @close="..." @add-to-queue="..." />
  ```
- State management:
  - Local `filters` ref, `sortField` (default: `'published_at'`), `sortOrder` (default: `'desc'`)
  - Use `useCatalogStore()` for data
  - `watch` filters/sort/page → call `catalogStore.fetchPosts({ ...filters, sort, order, page, per_page })`
  - On mount: fetch initial page with default sort
  - On `@select(post)`: set `selectedPostId`, fetch detail, open modal
  - On `@add-to-queue`: import and use queue store `addToQueue([postId])`, show toast
- Loading state: show `LoadingSpinner` overlay on the table area while fetching

### 6. Build Queue View Components

#### 6a. Create `QueueItem.vue`

- Path: `frontend/src/components/queue/QueueItem.vue`
- Props: `entry: QueueEntry`
- Emits: `@remove(postId)`
- Layout: horizontal flex row inside a card-like container:
  - **Drag handle** — left side, 6-dot grip icon (two columns of 3 dots), `cursor-grab`
  - **Title** — truncated, main content
  - **Priority badge** — small `bg-indigo-100 text-indigo-700` badge if priority > 0
  - **Status** — `<StatusBadge :status="entry.status" />`
  - **Remove button** — trash icon, `text-gray-400 hover:text-red-500`, calls `@remove`
- Visual states:
  - `waiting` — default appearance
  - `processing` — blue left border + subtle blue background tint
  - `done` — green left border, slightly faded text
  - `cancelled` — gray, strikethrough title

#### 6b. Create `QueueList.vue`

- Path: `frontend/src/components/queue/QueueList.vue`
- Uses `VueDraggable` from `vue-draggable-plus` to wrap queue items
- Props: none (reads from queue store directly)
- On drag end: extract new order of `post_id`s from the reordered array, call `queueStore.reorder(newOrder)`
- Shows `<EmptyState message="Queue is empty" />` when no entries
- Shows `<LoadingSpinner>` while loading
- Drag animation: items should have a subtle lift shadow during drag (`shadow-lg` on the ghost/dragged element)
- Configure `VueDraggable` with:
  - `handle=".drag-handle"` — only drag from the grip icon
  - `animation="200"` — smooth 200ms transitions
  - `ghostClass="opacity-50"` — ghost element at 50% opacity

#### 6c. Create `QueueControls.vue`

- Path: `frontend/src/components/queue/QueueControls.vue`
- Reads from queue store for state
- Three buttons in a horizontal row:
  1. **Start Pipeline** — `bg-green-600 hover:bg-green-700 text-white`, disabled when queue is empty or already processing. Shows "Processing..." with `LoadingSpinner` when active.
  2. **Pause** — `bg-yellow-500 hover:bg-yellow-600 text-white`, only visible when processing
  3. **Clear Completed** — `bg-white border border-gray-300 text-gray-700`, disabled when no completed/cancelled entries
- Status indicator: text showing "Idle", "Processing (3/10)", or "Paused" with colored dot
- Error handling: wrap API calls in try/catch, show toast on error

#### 6d. Create `AddToQueuePanel.vue`

- Path: `frontend/src/components/queue/AddToQueuePanel.vue`
- Collapsible panel (toggle open/closed) below the queue list
- Contains:
  - Search input — searches catalog posts by title (uses `catalogApi.list({ search: query, per_page: 10 })`)
  - Results list — shows matching posts with title, type, status
  - Each result has an "Add" button that calls `queueStore.addToQueue([postId])`
  - Already-queued posts show "Queued" badge instead of "Add" button (check against `queueStore.entries`)
  - Debounced search (300ms) using `@vueuse/core` `useDebounceFn`
- Styling: `bg-gray-50 border border-gray-200 rounded-lg p-4`

#### 6e. Assemble `QueueView.vue`

- Path: `frontend/src/views/QueueView.vue` — **replace the stub**
- Composition:
  ```
  <h2>Queue</h2>
  <QueueControls />
  <QueueList />
  <AddToQueuePanel />
  ```
- On mount: `queueStore.fetchQueue()`
- The view is simple — most logic lives in the store and child components

### 7. Build Watcher View Components

#### 7a. Create `WatcherStatus.vue`

- Path: `frontend/src/components/watcher/WatcherStatus.vue`
- Reads from watcher store
- Card displaying:
  - **Running indicator** — large green "Running" or red "Stopped" badge
  - **Stats grid** (2×2):
    - PID (if running)
    - Current cycle number
    - Interval (e.g., "24h")
    - Total recorded count
  - **Timing**: Last run timestamp (`<DateDisplay>`), Next run timestamp with countdown (if running, compute time remaining and display as "in 2h 15m")
- Countdown: use `@vueuse/core` `useIntervalFn` to update every 60 seconds

#### 7b. Create `WatcherControls.vue`

- Path: `frontend/src/components/watcher/WatcherControls.vue`
- Card with controls:
  - **Start/Stop toggle button** — green "Start Watcher" when stopped, red "Stop Watcher" when running
  - **Interval input** — number input with label "Interval (hours)", min=12, step=1, default 24
  - **Max per run** — number input, min=1, max=20, default 3
  - **Steps checkboxes** — checkboxes for each `PIPELINE_STEPS` entry, defaulting to `['record', 'transcribe', 'correct']`
  - **Apply Config** button — calls `watcherStore.updateConfig(...)`, only enabled when values differ from current config
- Disabled state: inputs disabled while watcher is running (must stop first to change config)

#### 7c. Create `WatcherTimeline.vue`

- Path: `frontend/src/components/watcher/WatcherTimeline.vue`
- Card with a table of past discovery/watcher cycles:
  - Columns: Date, Source, Posts Found, New Posts, Status
  - Data from `watcherStore.discoveryHistory`
  - Shows `<EmptyState message="No watcher cycles yet" />` when empty
  - Most recent cycle first
  - Status column uses `<StatusBadge>`

#### 7d. Create `DiscoveryCard.vue`

- Path: `frontend/src/components/watcher/DiscoveryCard.vue`
- Props: `post: PostSummary`
- Emits: `@add-to-queue(postId)`
- Small card (not a table row):
  - Thumbnail: if `post.thumbnail_url`, show `<img>` with `rounded-lg object-cover h-24 w-full`; else show a gradient placeholder with `PostTypeIcon`
  - Title: truncated, `text-sm font-medium`
  - Published date: `<DateDisplay>`, `text-xs text-gray-500`
  - Post type icon: `<PostTypeIcon>`
  - "Add to Queue" button: small, `bg-indigo-600 text-white text-xs rounded px-2 py-1`
  - Overall status: `<StatusBadge>` in corner

#### 7e. Create `DiscoveryFeed.vue`

- Path: `frontend/src/components/watcher/DiscoveryFeed.vue`
- Card containing:
  - Header: "Recently Discovered" + count badge + "Discover Now" button
  - Grid of `<DiscoveryCard>` — `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4`
  - Data from `watcherStore.newPosts`
  - Shows `<EmptyState message="No new posts discovered" />` when empty
  - "Discover Now" triggers `watcherStore.triggerDiscovery()`, shows loading state

#### 7f. Assemble `WatcherView.vue`

- Path: `frontend/src/views/WatcherView.vue` — **replace the stub**
- Composition:
  ```
  <h2>Watcher</h2>
  <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
    <div class="lg:col-span-2"><WatcherStatus /></div>
    <div><WatcherControls /></div>
  </div>
  <DiscoveryFeed />
  <WatcherTimeline />
  ```
- On mount: fetch all watcher data in parallel:
  ```typescript
  onMounted(() => {
    watcherStore.fetchStatus()
    watcherStore.fetchDiscoveryHistory()
    watcherStore.fetchNewPosts()
  })
  ```

### 8. Upgrade WebSocket Store with Event Dispatch

- Modify `frontend/src/stores/websocket.ts`:
  - Import `useCatalogStore`, `useQueueStore`, `useWatcherStore`, `useToastStore`
  - In `onmessage` handler, after adding to `recentEvents`, dispatch by event type:
    ```typescript
    // In onmessage handler, after storing the event:
    const catalog = useCatalogStore()
    const queue = useQueueStore()
    const watcher = useWatcherStore()
    const toast = useToastStore()

    switch (data.type) {
      case 'step_started':
      case 'step_completed':
      case 'step_failed':
        // Refresh the affected post in-place if it's visible
        catalog.fetchPosts()  // lightweight: re-fetches current page
        if (data.type === 'step_failed') {
          toast.add('error', `Step "${data.data.step}" failed for "${data.data.title || data.data.post_id}"`)
        }
        if (data.type === 'step_completed') {
          toast.add('success', `Step "${data.data.step}" completed`)
        }
        break
      case 'queue_update':
        queue.fetchQueue()
        break
      case 'watcher_cycle':
        watcher.fetchStatus()
        watcher.fetchDiscoveryHistory()
        toast.add('info', `Watcher cycle ${data.data.cycle ?? ''} completed`)
        break
      case 'discovery_complete':
        watcher.fetchNewPosts()
        watcher.fetchDiscoveryHistory()
        catalog.fetchStats()
        toast.add('info', `Discovery found ${data.data.new_posts ?? 0} new posts`)
        break
      case 'pipeline_complete':
        catalog.fetchStats()
        queue.fetchQueue()
        toast.add('success', 'Pipeline run completed')
        break
    }
    ```
  - **Important**: Use lazy store initialization — call `useSomeStore()` inside the handler, not at module level, to avoid Pinia initialization order issues. Alternatively, accept store references as parameters or use `storeToRefs` pattern.

### 9. Add WebSocket Connection Indicator to Sidebar

- Modify `frontend/src/components/AppLayout.vue`:
  - Import `useWebSocketStore`
  - Add a small connection dot at the bottom of the sidebar nav:
    ```html
    <div class="px-6 py-4 border-t border-gray-800">
      <div class="flex items-center gap-2">
        <span :class="['h-2 w-2 rounded-full', wsStore.connected ? 'bg-green-500' : 'bg-red-500']" />
        <span class="text-xs text-gray-500">{{ wsStore.connected ? 'Live' : 'Disconnected' }}</span>
      </div>
    </div>
    ```
  - Position: at the bottom of the `<aside>` (after `<nav>`, using `mt-auto`)

### 10. Validate Build

- Run `cd frontend && npm run build` to ensure TypeScript compiles and Vite builds successfully
- Fix any type errors, missing imports, or build warnings
- Common issues to watch for:
  - Missing type exports from `types/index.ts`
  - Circular import between stores (websocket importing catalog/queue/watcher)
  - `vue-draggable-plus` types may need `@types` or `declare module` shim
  - TailwindCSS v4 uses `@import "tailwindcss"` not `@tailwind` directives — no changes needed, already set up correctly

---

## Testing Strategy

### Manual Testing Checklist

Since the backend API is not running locally, focus on:

1. **Build succeeds** — `npm run build` exits 0, no type errors
2. **Dev server starts** — `npm run dev` starts Vite, loads the app in browser
3. **Router navigation** — all 4 routes render without errors (Dashboard, Catalog, Queue, Watcher)
4. **Component rendering** — views render their structure (even if API calls fail, the layout and controls should appear)
5. **StepBadge accessibility** — verify all 6 states are visually distinguishable (check in browser dev tools)
6. **Drag-to-reorder** — verify `VueDraggable` initializes without errors
7. **Toast system** — manually trigger toasts via console to verify positioning and auto-dismiss

### Type Coverage

TypeScript strict mode will catch:
- Missing props
- Wrong event payloads
- Store action return types
- API response type mismatches

### Future: Integration Testing

When the backend is running:
- Filter + sort + paginate catalog posts
- Add/remove/reorder queue entries with drag
- Start/stop watcher and verify status updates
- Trigger discovery and verify new post cards appear
- Verify WebSocket events update stores in real-time

---

## Acceptance Criteria

1. **Catalog view renders** — FilterBar, CatalogTable, PaginationBar all render; stub data would show posts in rows with 7 StepBadge dots
2. **StepBadge colors** — all 6 statuses (pending/queued/running/completed/failed/skipped) have visually distinct colors and at least one non-color differentiator (animation, icon overlay, or line-through)
3. **Sort** — clicking table headers updates sort field/order and re-fetches
4. **Pagination** — page navigation and per-page selector work, "Showing X–Y of Z" updates
5. **Post detail modal** — clicking a row opens modal with full step timeline, close on backdrop/Escape
6. **Queue drag-to-reorder** — `vue-draggable-plus` renders, drag handle works, reorder calls API
7. **Queue controls** — Start/Pause/Clear buttons call correct API endpoints
8. **Add to queue** — search panel finds posts, "Add" button works, already-queued shows badge
9. **Watcher status** — displays running/stopped state, cycle count, interval, next run countdown
10. **Watcher controls** — Start/Stop toggle, config inputs for interval/max-per-run/steps
11. **Discovery feed** — shows new post cards with "Add to Queue" buttons
12. **WebSocket dispatch** — incoming events update catalog/queue/watcher stores and trigger toasts
13. **Connection indicator** — sidebar shows green/red dot for WebSocket status
14. **Toast notifications** — appear bottom-right, auto-dismiss after 5s, closeable
15. **Build passes** — `cd frontend && npm run build` exits 0
16. **No Python files modified** — all changes are in `frontend/`

## Validation Commands

Execute these commands to validate the task is complete:

- `cd frontend && npm install` — Verify deps install (including vue-draggable-plus)
- `cd frontend && npm run build` — Verify TypeScript compiles and Vite builds successfully
- `ls frontend/src/components/catalog/` — Verify all catalog components exist: FilterBar.vue, CatalogTable.vue, CatalogRow.vue, StepBadge.vue, PostDetailModal.vue, StepTimeline.vue, PaginationBar.vue
- `ls frontend/src/components/queue/` — Verify all queue components exist: QueueControls.vue, QueueList.vue, QueueItem.vue, AddToQueuePanel.vue
- `ls frontend/src/components/watcher/` — Verify all watcher components exist: WatcherStatus.vue, WatcherControls.vue, WatcherTimeline.vue, DiscoveryFeed.vue, DiscoveryCard.vue
- `ls frontend/src/stores/` — Verify stores exist: catalog.ts, agent.ts, websocket.ts, queue.ts, watcher.ts, toast.ts
- `grep -l 'vue-draggable-plus' frontend/src/components/queue/QueueList.vue` — Verify draggable integration
- `grep -c 'case.*step_completed\|case.*pipeline_complete\|case.*queue_update' frontend/src/stores/websocket.ts` — Verify WebSocket event dispatch

## Notes

### New Dependency

```bash
cd frontend && npm install vue-draggable-plus
```

`vue-draggable-plus` provides a `<VueDraggable>` component compatible with Vue 3 + Composition API. It wraps SortableJS. If TypeScript complains about missing types, add a `declare module 'vue-draggable-plus'` shim in `frontend/src/env.d.ts` or `frontend/src/vite-env.d.ts`.

### StepBadge Color Reference

| Status    | Background       | Extra                | WCAG Note                     |
|-----------|------------------|----------------------|-------------------------------|
| pending   | `bg-gray-300`    | none                 | Default, lowest visual weight |
| queued    | `bg-blue-400`    | none                 | Distinct from pending by hue  |
| running   | `bg-yellow-400`  | `animate-pulse`      | Animation differentiates      |
| completed | `bg-green-500`   | checkmark overlay    | Icon + color                  |
| failed    | `bg-red-500`     | X overlay            | Icon + color                  |
| skipped   | `bg-gray-300`    | diagonal line overlay | Pattern differentiates        |

### Circular Import Prevention

The WebSocket store dispatches to catalog/queue/watcher stores. To avoid circular imports:
- Import store hooks (`useCatalogStore`, etc.) **inside** the `onmessage` handler function, not at the top of the file
- This ensures Pinia is initialized before stores are accessed
- Alternative: create a separate `eventDispatcher.ts` module that imports all stores and exports a `dispatchEvent(event)` function

### File Count

This plan creates approximately:
- 7 catalog components
- 4 queue components
- 5 watcher components
- 2 toast components
- 2 new stores + 1 toast store
- 3 view rewrites
- 2 existing file modifications (websocket.ts, AppLayout.vue, App.vue)

Total: ~26 new/modified files, all within `frontend/src/`.
