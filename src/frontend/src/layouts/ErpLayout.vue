<template>
  <div class="erp-layout erp-layout--crm-v2">
    <header class="erp-layout__header" aria-label="ERP 顶部区域">
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
  color: #1f1d18;
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
  border-radius: 10px;
  background: #fafaf7;
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
  flex: none;
  width: 100%;
  height: 48px;
  min-height: 48px;
  overflow: hidden;
  border-radius: 10px;
  background: #fafaf7;
}

.erp-layout__main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  outline: none;
  background: var(--erp-page-background);
}
</style>
