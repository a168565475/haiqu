<script setup lang="ts">
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { Check } from '@element-plus/icons-vue'

import { useThemeStore } from '@/stores/theme'
import type { EnabledThemeId } from '@/theme'

const themeStore = useThemeStore()
const { current, availableThemes } = storeToRefs(themeStore)

onMounted(() => {
  themeStore.initialize()
})

function selectTheme(theme: EnabledThemeId): void {
  themeStore.select(theme)
}
</script>

<template>
  <section class="theme-settings" data-testid="theme-settings-page">
    <header class="page-heading">
      <div>
        <h1>界面主题</h1>
      </div>
    </header>

    <div class="theme-settings__card" aria-labelledby="theme-options-title">
      <div class="theme-settings__intro">
        <h2 id="theme-options-title">主题方案</h2>
        <p>默认使用冷蓝银，也可选择暖色 ERP 或深海蓝。选择会保存在当前浏览器。</p>
      </div>

      <div class="theme-settings__options" role="list">
        <button
          v-for="theme in availableThemes"
          :key="theme.id"
          type="button"
          class="theme-option"
          :class="{ 'is-selected': current === theme.id }"
          :aria-pressed="current === theme.id"
          :data-theme-option="theme.id"
          @click="selectTheme(theme.id)"
        >
          <span class="theme-option__preview" :data-theme-preview="theme.id" aria-hidden="true">
            <span class="theme-option__preview-sidebar" />
            <span class="theme-option__preview-content">
              <span class="theme-option__preview-header" />
              <span class="theme-option__preview-lines">
                <span />
                <span />
                <span />
              </span>
            </span>
          </span>
          <span class="theme-option__copy">
            <strong>{{ theme.label }}</strong>
            <span>{{ theme.description }}</span>
          </span>
          <span v-if="current === theme.id" class="theme-option__check" aria-label="已选择">
            <el-icon><Check /></el-icon>
          </span>
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/theme/detail';
.theme-settings {
  min-width: 0;
  color: var(--erp-color-text-primary);
  font-family: var(--erp-font-body);
}

.page-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--erp-space-6);
  margin-bottom: var(--erp-space-6);
}

.page-heading h1 {
  margin: 0;
  color: var(--erp-color-text-primary);
  font-family: var(--erp-font-body);
  font-size: 36px;
  font-weight: 700;
  line-height: 44px;
}

.page-heading p {
  margin: 6px 0 0;
  color: var(--erp-color-text-secondary);
  font-size: 13px;
  line-height: 20px;
}

.theme-settings__card {
  @include detail.surface;
  max-width: 840px;
  padding: var(--erp-space-6);
}

.theme-settings__intro h2 {
  margin: 0;
  color: var(--erp-color-text-primary);
  font-size: 16px;
  font-weight: 600;
  line-height: 22px;
}

.theme-settings__intro p {
  margin: 6px 0 0;
  color: var(--erp-color-text-secondary);
  font-size: 13px;
  line-height: 20px;
}

.theme-settings__options {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--erp-space-3);
  margin-top: var(--erp-space-6);
}

.theme-option {
  @include detail.inset;
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--erp-space-4);
  width: 100%;
  min-height: 112px;
  padding: var(--erp-space-4);
  color: var(--erp-color-text-primary);
  text-align: left;
  cursor: pointer;
  transition: border-color 160ms ease, background-color 160ms ease, box-shadow 160ms ease;
}

.theme-option:hover {
  border-color: var(--erp-color-border-strong);
  background: var(--erp-color-hover);
}

.theme-option:focus-visible {
  outline: 2px solid var(--erp-color-focus);
  outline-offset: 2px;
}

.theme-option.is-selected {
  border-color: var(--erp-color-brand);
  background: var(--erp-color-selected);
  box-shadow: 0 0 0 1px var(--erp-color-brand);
}

.theme-option__preview {
  width: 148px;
  height: 76px;
  flex: none;
  display: flex;
  overflow: hidden;
  border: 1px solid var(--erp-color-border);
  border-radius: 4px;
  background: var(--erp-page-background);
}

.theme-option__preview-sidebar {
  width: 30px;
  flex: none;
  border-right: 1px solid var(--erp-glass-border);
  background: var(--erp-glass-background);
}

.theme-option__preview-content {
  flex: 1;
  padding: 8px;
}

.theme-option__preview-header {
  display: block;
  width: 68%;
  height: 8px;
  border-radius: 2px;
  background: var(--erp-color-brand);
}

.theme-option__preview-lines {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}

.theme-option__preview-lines span {
  display: block;
  height: 8px;
  border-radius: 2px;
  background: var(--erp-color-surface);
  box-shadow: inset 0 0 0 1px var(--erp-color-border);
}

.theme-option__copy {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.theme-option__copy strong {
  color: var(--erp-color-text-primary);
  font-size: 14px;
  font-weight: 600;
  line-height: 20px;
}

.theme-option__copy span {
  color: var(--erp-color-text-secondary);
  font-size: 13px;
  line-height: 20px;
}

.theme-option__check {
  width: 24px;
  height: 24px;
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-left: auto;
  border-radius: 50%;
  color: var(--erp-color-text-inverse);
  background: var(--erp-color-brand);
}

@media (max-width: 640px) {
  .theme-settings__card {
    padding: var(--erp-space-4);
  }

  .theme-option {
    align-items: flex-start;
  }

  .theme-option__preview {
    width: 112px;
  }
}
</style>
