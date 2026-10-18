<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'

withDefaults(defineProps<{
  title: string
  subtitle?: string
  demo?: boolean
  state?: 'READY' | 'LOADING' | 'EMPTY' | 'ERROR'
  errorMessage?: string
}>(), {
  demo: false,
  state: 'READY',
  errorMessage: '数据加载失败，请稍后重试',
  subtitle: '',
})

defineEmits<{ retry: [] }>()
</script>

<template>
  <section v-glass-spotlight.tilt class="workbench-section">
    <header class="workbench-section__header" :class="{ 'has-subtitle': subtitle }">
      <div class="workbench-section__title">
        <div class="workbench-section__title-line">
          <h2>{{ title }}</h2>
          <span v-if="demo" class="workbench-section__demo">演示数据</span>
        </div>
        <p v-if="subtitle">{{ subtitle }}</p>
      </div>
      <slot name="actions" />
    </header>

    <div v-if="state === 'LOADING'" class="workbench-section__state" aria-busy="true">
      <span class="workbench-section__spinner" />
      <span>数据加载中…</span>
    </div>
    <div v-else-if="state === 'ERROR'" class="workbench-section__state workbench-section__state--error">
      <strong>数据暂时不可用</strong>
      <span>{{ errorMessage }}</span>
      <button type="button" @click="$emit('retry')">重新加载</button>
    </div>
    <div v-else-if="state === 'EMPTY'" class="workbench-section__state">
      <span class="workbench-section__empty-icon">—</span>
      <span>暂无数据</span>
    </div>
    <div v-else class="workbench-section__body">
      <slot />
    </div>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/workbench' as workbench;

.workbench-section {
  @include workbench.glass-card;
  min-width: 0;
}

.workbench-section__header {
  height: 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 16px;
  border-bottom: 1px solid var(--erp-color-border-subtle);
}

.workbench-section__header.has-subtitle {
  height: 82px;
}

.workbench-section__title {
  min-width: 0;
  display: flex;
  align-items: flex-start;
  flex-direction: column;
  gap: 5px;
}

.workbench-section__title-line {
  display: flex;
  align-items: center;
  gap: 8px;
}

.workbench-section__title p {
  margin: 0;
  color: var(--erp-color-text-muted);
  font-size: 12px;
  line-height: 18px;
}

.workbench-section h2 {
  margin: 0;
  color: var(--erp-color-text-primary);
  font-size: 15px;
  font-weight: 600;
  line-height: 22px;
}

.workbench-section__demo {
  padding: 1px 7px;
  border-radius: 999px;
  color: var(--erp-tag-extension-2-text);
  background: var(--erp-tag-extension-2-background);
  font-size: 10px;
  line-height: 16px;
}

.workbench-section__body {
  height: calc(100% - 52px);
  overflow: auto;
  border-radius: 0 0 calc(var(--erp-glass-radius) - 1px) calc(var(--erp-glass-radius) - 1px);
}

.workbench-section__header.has-subtitle + .workbench-section__body,
.workbench-section__header.has-subtitle ~ .workbench-section__state {
  height: calc(100% - 82px);
}

.workbench-section__state {
  height: calc(100% - 52px);
  min-height: 120px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--erp-color-text-secondary);
  font-size: 13px;
}

.workbench-section__state--error strong { color: var(--erp-color-text-primary); font-size: 14px; }
.workbench-section__state--error button {
  @include workbench.secondary-button;
  height: 28px;
  padding: 0 10px;
  border-width: 1px;
  border-style: solid;
  cursor: pointer;
}

.workbench-section__spinner {
  width: 22px;
  height: 22px;
  border: 2px solid var(--erp-color-border);
  border-top-color: var(--erp-color-brand);
  border-radius: 50%;
  animation: section-loading .8s linear infinite;
}

.workbench-section__empty-icon {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--erp-color-subtle);
}

@keyframes section-loading { to { transform: rotate(360deg); } }

@media (prefers-reduced-motion: reduce), print {
  .workbench-section__spinner { animation: none; }
}
</style>
