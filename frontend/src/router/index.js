import { createRouter, createWebHistory } from 'vue-router'
// The research flow is the product: keep it in the entry chunk.
import ResearchView from '../views/ResearchView.vue'

const routes = [
  {
    path: '/',
    name: 'Research',
    component: ResearchView
  },
  {
    path: '/research',
    redirect: '/'
  },
  {
    // Removed legacy MiroFish routes (/legacy, /process, /simulation,
    // /report, /interaction) fall through to the research flow here.
    path: '/:pathMatch(.*)*',
    redirect: '/'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 })
})

export default router
