import vue from '@vitejs/plugin-vue'
import UnoCSS from 'unocss/vite'
import { VantResolver } from '@vant/auto-import-resolver'
import Components from 'unplugin-vue-components/vite'
import VueRouter from 'unplugin-vue-router/vite'

// 保留所选模板的文件路由、Vant 按需引入和 UnoCSS 插件组织。
export function createVitePlugins() {
  return [
    VueRouter({ routesFolder: 'src/pages', dts: 'src/types/typed-router.d.ts' }),
    vue(),
    Components({ resolvers: [VantResolver()], dts: 'src/types/components.d.ts' }),
    UnoCSS(),
  ]
}
