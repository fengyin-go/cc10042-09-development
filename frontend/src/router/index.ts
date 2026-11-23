import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import PipelineView from '@/views/PipelineView.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/pipeline', name: 'pipeline', component: PipelineView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
