import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'
import { createDevelopmentProxy } from './devProxy'

const proxyTransport = createDevelopmentProxy(process.env.VITE_PROXY_TARGET)

export default defineConfig({
  plugins: [vue(), {
    name: 'development-proxy-connections',
    configureServer(server) {
      server.httpServer?.once('close', () => proxyTransport.agent.destroy())
    },
  }],
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
        target: proxyTransport.target,
        agent: proxyTransport.agent,
      },
      '/media': {
        target: proxyTransport.target,
        agent: proxyTransport.agent,
      },
    },
  },
})
