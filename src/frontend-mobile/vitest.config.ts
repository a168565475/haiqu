import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: {
    environment: 'jsdom', include: ['src/**/*.test.ts'], clearMocks: true,
    // Vant 的 ESM 样式入口需要经 Vite 转换，不能交给 Node 原生加载 CSS。
    server: { deps: { inline: ['vant'] } },
  },
})
