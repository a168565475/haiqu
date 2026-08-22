<template>
  <div class="erp-layout">
    <aside class="erp-layout__sidebar" aria-label="ERP 侧边区域">
      <div class="erp-layout__brand" aria-label="haiqu ERP CRM">
        <span class="erp-layout__brand-name">haiqu</span>
        <span class="erp-layout__brand-context">ERP&nbsp; · &nbsp;CRM</span>
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

<style scoped>
.erp-layout {
  width: 100%;
  height: 100vh;
  height: 100dvh;
  display: flex;
  overflow: hidden;
  color: #202124;
  background: #f5f6f8;
}

.erp-layout__sidebar {
  width: 240px;
  min-width: 240px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid #dfe2e7;
  background: #fff;
}

.erp-layout__brand {
  height: 56px;
  min-height: 56px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 24px;
  white-space: nowrap;
}

.erp-layout__brand-name {
  color: #1d1e21;
  font-size: 24px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: 0.01em;
}

.erp-layout__brand-context {
  color: #5f636b;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.03em;
}

.erp-layout__sidebar-content {
  flex: 1;
  min-height: 0;
  overflow: hidden;
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
  height: 56px;
  min-height: 56px;
  overflow: hidden;
  border-bottom: 1px solid #dfe2e7;
  background: #fff;
}

.erp-layout__main {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  outline: none;
  background: #f5f6f8;
}

@media (max-width: 768px) {
  .erp-layout__sidebar {
    display: none;
  }
}
</style>
