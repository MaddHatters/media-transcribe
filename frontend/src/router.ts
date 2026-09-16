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
