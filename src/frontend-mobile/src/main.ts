import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import 'virtual:uno.css'
import 'vant/es/toast/style'
import 'vant/es/dialog/style'
import './styles/app.css'

createApp(App).use(createPinia()).use(router).mount('#app')
