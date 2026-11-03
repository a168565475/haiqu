import { createRouter, createWebHistory } from 'vue-router'
import { handleHotUpdate, routes } from 'vue-router/auto-routes'
import { mobileAuthGuard } from './authGuard'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL), routes,
  scrollBehavior: () => ({ top: 0 }),
})
if (import.meta.hot) handleHotUpdate(router)

router.beforeEach(mobileAuthGuard)

export default router
