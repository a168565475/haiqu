<script setup lang="ts">
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'

import { useHealthStore } from '@/stores/health'

const store = useHealthStore()
const { health, loading, error, isHealthy } = storeToRefs(store)

onMounted(() => {
  void store.refresh()
})
</script>

<template>
  <div class="environment-page">
    <div class="app-main">
      <ElAlert
        v-if="error"
        :title="`后端连接失败：${error}`"
        type="error"
        show-icon
        :closable="false"
        class="status-alert"
      />

      <section class="hero">
        <p class="eyebrow">ENVIRONMENT READY CHECK</p>
        <h1>haiqu ERP 开发环境</h1>
        <p>Vue 3 通过 Axios 调用 Django REST Framework，并实时检查 PostgreSQL 与 Redis。</p>
        <ElButton type="primary" :loading="loading" @click="store.refresh">
          重新检查系统状态
        </ElButton>
      </section>

      <div class="status-grid">
        <ElCard shadow="hover">
          <template #header><strong>Frontend</strong></template>
          <p>Vue 3 + TypeScript + Vite</p>
          <ElTag type="success">Element Plus</ElTag>
        </ElCard>

        <ElCard shadow="hover">
          <template #header><strong>Backend</strong></template>
          <p>Python 3.13 + Django 5.2 LTS</p>
          <ElTag :type="health?.status === 'ok' ? 'success' : 'info'">
            {{ health?.status === 'ok' ? 'DRF 正常' : '等待响应' }}
          </ElTag>
        </ElCard>

        <ElCard shadow="hover">
          <template #header><strong>Database</strong></template>
          <p>PostgreSQL</p>
          <ElTag :type="health?.database === 'ok' ? 'success' : 'danger'">
            {{ health?.database === 'ok' ? '连接正常' : '未确认' }}
          </ElTag>
        </ElCard>

        <ElCard shadow="hover">
          <template #header><strong>Cache</strong></template>
          <p>Redis</p>
          <ElTag :type="health?.redis === 'ok' ? 'success' : 'danger'">
            {{ health?.redis === 'ok' ? '连接正常' : '未确认' }}
          </ElTag>
        </ElCard>
      </div>

      <ElCard class="api-result" shadow="never">
        <template #header>
          <div class="result-header">
            <strong>GET /api/health/</strong>
            <ElTag :type="isHealthy ? 'success' : 'info'">
              {{ isHealthy ? 'HTTP 200' : '等待验证' }}
            </ElTag>
          </div>
        </template>
        <pre>{{ health ?? { status: 'checking' } }}</pre>
      </ElCard>
    </div>
  </div>
</template>
