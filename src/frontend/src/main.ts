import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'

import App from './App.vue'
import { router } from './router'
import { initializeTheme } from './theme'
import { useAuthStore } from '@/stores/auth'
import { apiClient } from '@/api/request'
import { installIdentityRequestGuard } from '@/api/identityGuard'
import './styles/theme.scss'
import './styles/main.scss'
import './styles/crm/_task-complaint-overlays.scss'
import './styles/crm/customer-management-tables.scss'
import './styles/crm/operational-management-density.scss'
import './styles/crm/procurement-inventory-density.scss'
import './styles/settings-theme.scss'
import './styles/scrollActions.scss'

initializeTheme()

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
const auth = useAuthStore(pinia)
// 必须先于 router 首次导航和 App 的企微响应处理安装，避免旧401/403产生身份副作用。
const removeIdentityGuard = installIdentityRequestGuard(apiClient, () => ({
  generation: auth.identityRequestGeneration,
  version: auth.identityVersion,
  blocked: !auth.identityReady,
}), () => auth.requireIdentityRevalidation())
app.onUnmount(removeIdentityGuard)
if (import.meta.hot) import.meta.hot.dispose(removeIdentityGuard)
app.use(router).use(ElementPlus, { locale: zhCn }).mount('#app')
