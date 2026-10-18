<script setup lang="ts">
withDefaults(defineProps<{
  tone?: 'brand' | 'info' | 'success' | 'warning' | 'danger' | 'neutral'
}>(), {
  tone: 'neutral',
})
</script>

<template>
  <span class="quotation-status-tag is-strong" :class="`is-${tone}`">
    <slot />
  </span>
</template>

<style scoped lang="scss">
.quotation-status-tag {
  display: inline-flex;
  min-width: 56px;
  height: 24px;
  box-sizing: border-box;
  align-items: center;
  justify-content: center;
  flex: none;
  padding: 0 8px;
  border: 0;
  border-radius: 999px;
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
  font-size: 12px;
  font-weight: 500;
  line-height: 18px;
  white-space: nowrap;
}

.is-strong { color: var(--erp-tag-neutral-text); }
.is-strong.is-brand { background: var(--erp-tag-brand-background); }
.is-strong.is-info { background: var(--erp-tag-info-background); }
.is-strong.is-success { background: var(--erp-tag-success-background); }
.is-strong.is-warning { background: var(--erp-tag-warning-background); }
.is-strong.is-danger { background: var(--erp-tag-danger-background); }
.is-strong.is-neutral { background: var(--erp-tag-neutral-background); }

</style>
