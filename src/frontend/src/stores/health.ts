import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { fetchHealth } from '@/api/health'
import type { HealthResponse } from '@/types/health'

export const useHealthStore = defineStore('health', () => {
  const health = ref<HealthResponse | null>(null)
  const loading = ref(false)
  const error = ref('')

  const isHealthy = computed(() => health.value?.status === 'ok')

  async function refresh() {
    loading.value = true
    error.value = ''
    try {
      health.value = await fetchHealth()
    } catch (reason) {
      health.value = null
      error.value = reason instanceof Error ? reason.message : '无法连接后端服务'
    } finally {
      loading.value = false
    }
  }

  return { health, loading, error, isHealthy, refresh }
})
