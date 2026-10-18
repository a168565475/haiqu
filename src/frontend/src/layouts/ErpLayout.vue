<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
</script>

<template>
  <div class="erp-layout erp-layout--crm-v2">
    <header v-glass-spotlight class="erp-layout__header" aria-label="ERP 顶部区域">
      <slot name="header" />
    </header>
    <div class="erp-layout__body">
      <aside class="erp-layout__sidebar" aria-label="ERP 侧边区域">
        <div class="erp-layout__sidebar-content">
          <slot name="sidebar" />
        </div>
      </aside>
      <div class="erp-layout__workspace">
        <main id="erp-main-content" class="erp-layout__main" tabindex="-1">
          <slot />
        </main>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.erp-layout {
  --erp-sidebar-width: 80px;
  box-sizing: border-box;
  width: 100%;
  height: 100vh;
  height: 100dvh;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 0 14px 14px;
  overflow: hidden;
  color: var(--erp-color-text-primary);
  background: var(--erp-page-background);
  font-family: var(--erp-font-body, 'Noto Sans SC', 'Microsoft YaHei', sans-serif);
}

.erp-layout__body {
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
  gap: 14px;
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
  border-radius: var(--erp-glass-radius);
  background: transparent;
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
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
  box-sizing: border-box;
  flex: none;
  width: 100%;
  height: 48px;
  min-height: 48px;
  overflow: visible;
  border: 1px solid var(--erp-glass-border);
  border-radius: var(--erp-glass-radius);
  background: var(--erp-glass-surface);
  box-shadow: var(--erp-glass-shadow);
  -webkit-backdrop-filter: var(--erp-glass-backdrop);
  backdrop-filter: var(--erp-glass-backdrop);
}

.erp-layout__main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  outline: none;
  background: transparent;
}

@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .erp-layout__header { background: var(--erp-color-surface); }
}

@media print {
  .erp-layout,
  .erp-layout__header,
  .erp-layout__main {
    background: #fff;
    box-shadow: none;
    -webkit-backdrop-filter: none;
    backdrop-filter: none;
  }
}
</style>
