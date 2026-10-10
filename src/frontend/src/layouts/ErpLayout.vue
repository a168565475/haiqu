<script setup lang="ts">
import inquiryBrand from '@/assets/crm-v2/hitree-inquiry.svg'
withDefaults(
  defineProps<{
    compactSidebar?: boolean
    sidebarExpanded?: boolean
  }>(),
  {
    compactSidebar: false,
    sidebarExpanded: false,
  },
)
</script>

<template>
  <div
    class="erp-layout"
    :class="{
      'erp-layout--compact': compactSidebar,
      'erp-layout--sidebar-expanded': sidebarExpanded,
      'erp-layout--sidebar-v2': true,
      'erp-layout--crm-v2': true,
    }"
  >
    <aside class="erp-layout__sidebar" aria-label="ERP 侧边区域">
      <div class="erp-layout__brand" aria-label="HiTree ERP CRM">
        <img :src="inquiryBrand" class="erp-layout__brand-name erp-layout__brand-inquiry" alt="HiTree" />
        <span class="erp-layout__brand-short" aria-hidden="true">HT</span>
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
  --erp-sidebar-width: 230px;
  width: 100%;
  height: 100vh;
  height: 100dvh;
  display: flex;
  overflow: hidden;
  color: #202124;
  background: var(--erp-page-background);
}

.erp-layout__sidebar {
  width: 230px;
  min-width: 230px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid #263449;
  background: #0f1b2d;
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
  color: #f8fafc;
  font-size: 26px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: 0.01em;
}

.erp-layout__brand-context {
  color: #94a3b8;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.03em;
}

.erp-layout__brand-short {
  display: none;
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
  overflow: auto;
  outline: none;
  background: var(--erp-page-background);
}

.erp-layout--compact .erp-layout__sidebar {
  width: 64px;
  min-width: 64px;
}

.erp-layout--compact {
  --erp-sidebar-width: 64px;
}

.erp-layout--compact .erp-layout__brand {
  justify-content: center;
  padding: 0;
}

.erp-layout--compact .erp-layout__brand-name,
.erp-layout--compact .erp-layout__brand-context {
  display: none;
}

.erp-layout--compact .erp-layout__brand-short {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: #0f172a;
  background: #f8fafc;
  font-size: 18px;
  font-weight: 700;
}

@media (max-width: 768px) {
  .erp-layout {
    --erp-sidebar-width: 0px;
  }

  .erp-layout__sidebar {
    display: none;
  }
}

@media (max-width: 1440px) and (min-width: 769px) {
  .erp-layout {
    --erp-sidebar-width: 64px;
  }

  .erp-layout__sidebar {
    width: 64px;
    min-width: 64px;
  }

  .erp-layout__brand {
    justify-content: center;
    padding: 0;
  }

  .erp-layout__brand-name {
    display: none;
  }

  .erp-layout__brand-short {
    width: 32px;
    height: 32px;
    display: grid;
    place-items: center;
    border-radius: 8px;
    color: #0f172a;
    background: #f8fafc;
    font-size: 18px;
    font-weight: 700;
  }

  .erp-layout__brand-context {
    display: none;
  }
}

.erp-layout--sidebar-expanded {
  --erp-sidebar-width: 230px;
}

.erp-layout--sidebar-expanded .erp-layout__sidebar {
  width: 230px;
  min-width: 230px;
}

.erp-layout--sidebar-expanded .erp-layout__brand {
  justify-content: flex-start;
  padding: 0 24px;
}

.erp-layout--sidebar-expanded .erp-layout__brand-name {
  display: block;
}

.erp-layout--sidebar-expanded .erp-layout__brand-short {
  display: none;
}

.erp-layout--crm-v2 {
  color: #1f1d18;
  background: var(--erp-page-background);
  font-family: var(--erp-font-body, 'Noto Sans SC', 'Microsoft YaHei', sans-serif);
}

.erp-layout--sidebar-v2 .erp-layout__sidebar {
  border-right: 0;
  background: #1c1c1a;
  color: #1f1d18;
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
}

.erp-layout--sidebar-v2 .erp-layout__brand {
  height: 70px;
  min-height: 70px;
  display: flex;
  align-items: center;
  box-sizing: border-box;
  padding: 0 24px;
}

.erp-layout--sidebar-v2 .erp-layout__brand-name {
  display: block;
  color: #faf8f2;
  font-family: 'Trebuchet MS', Inter, sans-serif;
  font-size: 29px;
  font-weight: 700;
  line-height: 34px;
  letter-spacing: -2px;
  transform: skewX(-4deg);
  transform-origin: left center;
}

.erp-layout--sidebar-v2 .erp-layout__brand-inquiry {
  width: 88px;
  height: 22px;
  transform: none;
}

.erp-layout--crm-v2 .erp-layout__header {
  height: 64px;
  min-height: 64px;
  border-bottom: 0;
  background: var(--erp-surface-background);
}

.erp-layout--crm-v2 .erp-layout__main {
  overflow: hidden;
  background: var(--erp-page-background);
}

@media (max-width: 1440px) and (min-width: 769px) {
  .erp-layout--sidebar-v2 .erp-layout__brand {
    height: 70px;
    min-height: 70px;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0;
  }

  .erp-layout--sidebar-v2 .erp-layout__brand-name,
  .erp-layout--sidebar-v2 .erp-layout__brand-context {
    display: none;
  }

  .erp-layout--sidebar-v2 .erp-layout__brand-short {
    color: #1f1d18;
    background: var(--erp-surface-background);
    font-family: 'Trebuchet MS', Inter, sans-serif;
    font-size: 14px;
    font-style: italic;
    font-weight: 800;
    letter-spacing: -1px;
  }
}

.erp-layout--sidebar-v2.erp-layout--sidebar-expanded .erp-layout__brand {
  justify-content: flex-start;
  padding: 0 24px;
}

.erp-layout--sidebar-v2.erp-layout--sidebar-expanded .erp-layout__brand-name {
  display: block;
}

.erp-layout--sidebar-v2.erp-layout--sidebar-expanded .erp-layout__brand-context,
.erp-layout--sidebar-v2.erp-layout--sidebar-expanded .erp-layout__brand-short {
  display: none;
}
</style>
