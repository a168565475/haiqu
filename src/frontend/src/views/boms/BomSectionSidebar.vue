<script setup lang="ts">
interface SectionNavigationGroup {
  label: string
  indexes: number[]
  count: number
}

defineProps<{
  groups: SectionNavigationGroup[]
  activeLabel: string
  hasSections: boolean
}>()

const emit = defineEmits<{
  select: [indexes: number[]]
}>()
</script>

<template>
  <aside class="card section-sidebar">
    <h2>物料分类</h2>
    <div v-if="hasSections" class="section-tabs">
      <button
        v-for="group in groups"
        :key="group.label"
        type="button"
        :class="{ active: group.label === activeLabel }"
        :disabled="!group.indexes.length"
        @click="emit('select', group.indexes)"
      >
        <span>{{ group.label }}</span><b>{{ group.count }}</b>
      </button>
    </div>
  </aside>
</template>

<style scoped lang="scss">
@use '@/styles/theme/detail' as detail;

.section-sidebar { @include detail.surface; min-width: 0; padding: 10px 0; overflow: hidden; }
.section-sidebar h2 { margin: 0; padding: 0 16px 10px; border-bottom: 1px solid var(--erp-color-border); font-size: 14px; line-height: 22px; white-space: nowrap; }
.section-sidebar .section-tabs { display: grid; min-height: 0; gap: 0; overflow: visible; border: 0; }
.section-sidebar .section-tabs button { display: flex; width: calc(100% - 12px); height: 46px; align-items: center; justify-content: space-between; margin: 0 6px; padding: 0 12px; border: 0; border-left: 3px solid transparent; background: transparent; color: var(--erp-color-text-secondary); font-size: 13px; text-align: left; cursor: pointer; white-space: nowrap; }
.section-sidebar .section-tabs button b { color: var(--erp-color-text-muted); font-size: 12px; font-weight: 500; }
.section-sidebar .section-tabs button.active { border-bottom: 0; border-left-color: var(--erp-color-brand); color: var(--erp-color-brand); background: var(--erp-color-selected); }
.section-sidebar .section-tabs button.active b { color: var(--erp-color-brand); }
.section-sidebar .section-tabs button:disabled { cursor: default; opacity: 1; }
</style>
