<script setup lang="ts">
import railBrand from '@/assets/navigation/hitree-rail-mark.png'
</script>

<template>
  <div class="erp-layout erp-layout--crm-v2">
    <aside class="erp-layout__sidebar" aria-label="ERP 侧边区域">
      <div class="erp-layout__brand">
        <img :src="railBrand" class="erp-layout__brand-mark" alt="HiTree" width="64" height="72" />
      </div>
      <div class="erp-layout__sidebar-content">
        <slot name="sidebar" />
      </div>
    </aside>

    <div class="erp-layout__workspace">
      <header class="erp-layout__header" aria-label="ERP 顶部区域">
        <slot name="header" />
      </header>
      <main id="erp-main-content" class="erp-layout__main" tabindex="-1">
        <slot />
      </main>
    </div>
  </div>
</template>

<style scoped lang="scss">
.erp-layout {
  --erp-sidebar-width: 80px;
  width: 100%;
  height: 100vh;
  height: 100dvh;
  display: flex;
  overflow: hidden;
  color: #1f1d18;
  background: var(--erp-page-background);
  font-family: var(--erp-font-body, 'Noto Sans SC', 'Microsoft YaHei', sans-serif);
}

.erp-layout__sidebar {
  position: relative;
  z-index: 60;
  flex: 0 0 80px;
  width: 80px;
  min-width: 80px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: visible;
  background: #1e1e1c;
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
}

.erp-layout__brand {
  height: 96px;
  min-height: 96px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.erp-layout__brand-mark {
  display: block;
  width: 64px;
  height: 72px;
  object-fit: contain;
  filter: brightness(0) invert(1);
}

.erp-layout__sidebar-content {
  flex: 1;
  min-height: 0;
  overflow: visible;
}

.erp-layout__workspace {
  flex: 1;
  min-width: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.erp-layout__header {
  width: 100%;
  height: 64px;
  min-height: 64px;
  overflow: hidden;
  border-bottom: 0;
  background: var(--erp-surface-background);
}

.erp-layout__main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  outline: none;
  background: var(--erp-page-background);
}
</style>
