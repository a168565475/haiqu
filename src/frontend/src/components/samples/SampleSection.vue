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
@use '@/styles/theme/detail';
.sample-section { @include detail.surface; padding: 16px; }
h2 { min-height: 30px; margin: 0 0 14px; padding-bottom: 7px; border-bottom: 1px solid token.$crm-border-subtle; color: token.$crm-text-primary; font-family: token.$crm-font-body; font-size: 18px; font-weight: 700; line-height: 26px; }
h2 { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.section-actions { display: flex; min-width: 0; align-items: center; gap: 8px; font-family: token.$crm-font-body; font-size: 12px; font-weight: 400; }
</style>
