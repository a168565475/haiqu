import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import zhCn from '../../../src/frontend/node_modules/element-plus/es/locale/lang/zh-cn.mjs'
import '../../../src/frontend/node_modules/element-plus/dist/index.css'
import '@fontsource-variable/noto-sans-sc'
import '@fontsource-variable/noto-serif-sc'
import App from './D3ReviewApp.vue'
import './design.scss'
import './d3-design.scss'

createApp(App).use(ElementPlus, { locale: zhCn }).mount('#app')
