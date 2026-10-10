<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { isNavigationFailure, useRoute, useRouter } from 'vue-router'

import { resolveRefreshTarget } from '@/utils/pageRefresh'

const route = useRoute()
const router = useRouter()
const errorMessage = ref('')
const returning = ref(false)

async function returnToWorkbench() {
  if (returning.value) return
  returning.value = true
  try {
    const failure = await router.replace('/')
    if (isNavigationFailure(failure)) errorMessage.value = '返回工作台未成功，请重试。'
  } catch {
    errorMessage.value = '返回工作台失败，请检查网络后重试。'
  } finally {
    returning.value = false
  }
}

onMounted(async () => {
  try {
    const failure = await router.replace(resolveRefreshTarget(router, route.query.target))
    if (isNavigationFailure(failure)) errorMessage.value = '页面刷新未成功，请返回工作台后重试。'
  } catch {
    errorMessage.value = '页面刷新失败，请返回工作台后重试。'
  }
})
</script>

<template>
  <section class="page-refresh" :aria-busy="!errorMessage">
    <template v-if="errorMessage">
      <p role="alert">{{ errorMessage }}</p>
      <button type="button" :disabled="returning" @click="returnToWorkbench">
        {{ returning ? '正在返回…' : '返回工作台' }}
      </button>
    </template>
    <p v-else role="status">正在刷新页面…</p>
  </section>
</template>

<style lang="scss" scoped>
.page-refresh {
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: #1c1c1a;
  background: var(--erp-page-background);
}

.page-refresh p { margin: 0; }
.page-refresh button {
  height: 32px;
  padding: 0 16px;
  border: 1px solid #c84e28;
  border-radius: 5px;
  color: #fcfbf7;
  background: #c84e28;
  font: inherit;
  cursor: pointer;
}
.page-refresh button:disabled { cursor: wait; opacity: 0.6; }
.page-refresh button:focus-visible { outline: 2px solid #c84e28; outline-offset: 3px; }
</style>
