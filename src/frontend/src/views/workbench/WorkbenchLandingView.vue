<script setup lang="ts">
defineOptions({ name: 'WorkbenchLandingView' })
</script>

<template>
  <section class="workbench-landing" aria-labelledby="workbench-landing-title">
    <h1 id="workbench-landing-title">工作台</h1>
    <p>请选择左侧菜单，开始处理业务。</p>
    <span>当前账号暂无可访问的生产工作台，已授权的业务模块仍可正常使用。</span>
  </section>
</template>

<style scoped>
.workbench-landing {
  min-height: 320px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 32px;
  border: 1px solid var(--erp-glass-border);
  border-radius: var(--erp-glass-radius);
  background: var(--erp-glass-background);
  color: var(--erp-color-text-primary);
  text-align: center;
}
.workbench-landing h1 { margin: 0; font-size: 24px; }
.workbench-landing p { margin: 0; font-size: 16px; }
.workbench-landing span { color: var(--erp-color-text-secondary); font-size: 13px; line-height: 1.7; }
</style>
