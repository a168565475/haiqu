<script setup lang="ts">
defineProps<{ label: string; value?: string | number | null }>()
</script>

<template>
  <div class="sample-readonly-field"><span class="field-label">{{ label }}</span><span class="field-value" :title="String(value ?? '—')">{{ value === '' || value == null ? '—' : value }}</span></div>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/crm/mixins' as mixin;
.sample-readonly-field { display: flex; min-width: 0; height: 60px; flex-direction: column; gap: 6px; font-size: 14px; line-height: 22px; }
.field-label { color: token.$crm-text-primary; font-weight: 500; }
.field-value { @include mixin.text-ellipsis; display: block; min-height: 32px; padding: 5px 12px; border-radius: 4px; color: token.$crm-text-primary; background: token.$crm-color-page; box-shadow: inset 0 0 0 1px token.$crm-border-subtle; line-height: 22px; }
</style>
