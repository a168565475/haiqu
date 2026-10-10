<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

function returnToWorkbench() {
  void router.replace({ name: 'home' })
}
</script>

<template>
  <section class="not-found-page" aria-labelledby="not-found-title">
    <ElResult
      icon="warning"
      title="页面不存在"
      sub-title="当前地址没有对应页面，请检查链接或返回业务工作台。"
    >
      <template #title>
        <h1 id="not-found-title">页面不存在</h1>
      </template>
      <template #extra>
        <ElButton type="primary" @click="returnToWorkbench">返回业务工作台</ElButton>
      </template>
    </ElResult>
  </section>
</template>

<style lang="scss" scoped>
.not-found-page {
  min-height: 420px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid #e2e4e8;
  border-radius: 12px;
  background: var(--erp-surface-background);
}

.not-found-page h1 {
  margin: 0;
  color: #25272b;
  font-size: 24px;
  line-height: 1.4;
}
</style>
