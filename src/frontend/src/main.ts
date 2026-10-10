import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'

import App from './App.vue'
import { router } from './router'
import { initializeTheme } from './theme'
import './styles/theme.scss'
import './styles/main.scss'
import './styles/crm/_task-complaint-overlays.scss'
import './styles/crm/customer-management-tables.scss'
import './styles/crm/operational-management-density.scss'
import './styles/crm/procurement-inventory-density.scss'
import './styles/settings-theme.scss'

initializeTheme()

createApp(App).use(createPinia()).use(router).use(ElementPlus, { locale: zhCn }).mount('#app')
