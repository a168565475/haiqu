import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import { createVitePlugins } from './build/vite'

export default defineConfig({
  base: '/m/',
  plugins: createVitePlugins(),
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    host: '127.0.0.1', port: 8082, strictPort: true,
    proxy: {
      '/api': { target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000' },
      '/media': { target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000' },
    },
  },
  preview: { host: '127.0.0.1', port: 8082, strictPort: true },
})
