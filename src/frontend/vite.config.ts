import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    // Windows 挂载目录需要轮询；排除测试产物，避免文件检查挤占接口代理的 DNS 解析线程。
    watch: {
      usePolling: true,
      interval: 1000,
      binaryInterval: 2000,
      ignored: ['**/.tmp/**', '**/qa/**', '**/outputs/**', '**/logs/**', '**/dist-*/**'],
    },
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://backend:8000',
      },
      '/media': {
        target: process.env.VITE_PROXY_TARGET || 'http://backend:8000',
      },
    },
  },
})
