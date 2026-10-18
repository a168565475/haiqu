<script setup lang="ts">
defineProps<{ title: string; subtitle: string }>()
defineEmits<{ exit: [] }>()
</script>
<template><header class="fullscreen-header"><strong>haiqu</strong><div><h1>{{ title }}</h1><p>{{ subtitle }}</p></div><div class="fullscreen-actions"><slot name="actions" /><ElButton @click="$emit('exit')">退出全屏</ElButton></div></header></template>
<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.fullscreen-header { display: flex; height: 112px; flex: none; align-items: center; gap: 24px; padding: 28px; background: token.$crm-color-surface; }
strong { width: 144px; flex: none; font-size: 32px; font-weight: 500; line-height: 40px; }
.fullscreen-header > div { flex: 1; min-width: 0; }
h1 { margin: 0; font-family: token.$crm-font-display; font-size: 32px; line-height: 40px; }
p { margin: 4px 0 0; overflow: hidden; color: token.$crm-text-secondary; font-size: 12px; line-height: 22px; text-overflow: ellipsis; white-space: nowrap; }
.fullscreen-actions { display: flex; flex: none !important; align-items: center; gap: 10px; }
.fullscreen-header.fullscreen-header :deep(.el-button) { width: auto; min-width: 96px; height: 32px !important; min-height: 32px !important; padding: 0 16px; border-radius: 5px; background: var(--erp-color-surface); font-size: 13px; }
</style>
