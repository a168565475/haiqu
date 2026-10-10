<script setup lang="ts">
withDefaults(defineProps<{ title: string; tone?: 'info' | 'warning' | 'danger' | 'success' }>(), { tone: 'info' })
</script>
<template><section class="inquiry-notice" :class="`inquiry-notice--${tone}`"><strong>{{ title }}</strong><div class="inquiry-notice-body"><slot /></div></section></template>
<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.inquiry-notice { box-sizing: border-box; min-height: 66px; padding: 9px 13px; border: 1px solid token.$crm-info; border-radius: 6px; background: token.$crm-info-soft; color: token.$crm-info;
  strong { display: block; font-size: 13px; line-height: 22px; font-weight: 700; }
  .inquiry-notice-body { margin: 4px 0 0; font-size: 12px; line-height: 20px; color: token.$crm-text-regular; }
  &--warning { background: token.$crm-warning-soft; border-color: token.$crm-warning; color: token.$crm-warning; }
  &--danger { background: token.$crm-danger-soft; border-color: token.$crm-danger; color: token.$crm-danger; }
  &--success { background: token.$crm-success-soft; border-color: token.$crm-success; color: token.$crm-success; }
}
</style>
