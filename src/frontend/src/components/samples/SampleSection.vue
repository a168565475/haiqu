<script setup lang="ts">
defineProps<{ title: string }>()
</script>

<template>
  <section class="sample-section" :aria-label="title">
    <h2><span>{{ title }}</span><span v-if="$slots.actions" class="section-actions"><slot name="actions" /></span></h2>
    <slot />
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.sample-section { min-width: 0; padding: 24px; border-radius: 4px; background: token.$crm-color-surface; box-shadow: inset 0 0 0 1px token.$crm-border-subtle; }
h2 { height: 38px; margin: 0 0 16px; padding-bottom: 7px; border-bottom: 1px solid token.$crm-border-subtle; color: token.$crm-text-primary; font-family: token.$crm-font-display; font-size: 22px; font-weight: 700; line-height: 30px; }
h2 { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.section-actions { display: flex; min-width: 0; align-items: center; gap: 8px; font-family: token.$crm-font-body; font-size: 12px; font-weight: 400; }
</style>
