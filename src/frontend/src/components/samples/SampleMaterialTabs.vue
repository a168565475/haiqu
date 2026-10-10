<script setup lang="ts">
import { sampleMaterialCategories, type SampleMaterialCategory } from '@/types/sampleMaterial'
defineProps<{ modelValue: SampleMaterialCategory; counts: Partial<Record<SampleMaterialCategory, number>> }>()
const emit = defineEmits<{ 'update:modelValue': [value: SampleMaterialCategory] }>()
</script>

<template>
  <nav class="material-tabs" aria-label="材料分区">
    <button v-for="category in sampleMaterialCategories" :key="category.key" type="button" :aria-pressed="modelValue === category.key" :class="{ active: modelValue === category.key }" @click="emit('update:modelValue', category.key)">{{ category.label }} {{ counts[category.key] ?? '—' }}</button>
    <slot />
  </nav>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.material-tabs { display: flex; height: 32px; flex: none; gap: 8px; overflow: hidden; }
button { display: flex; width: auto; min-width: 0; height: 32px; flex: 1 1 0; align-items: flex-start; justify-content: center; padding: 0 8px 8px; border: 0; border-bottom: 2px solid transparent; box-sizing: border-box; color: token.$crm-text-secondary; background: transparent; font: inherit; font-size: 13px; line-height: 20px; cursor: pointer; }
button.active { border-bottom-color: token.$crm-primary; color: token.$crm-primary; }
button:hover { background: token.$crm-color-page; }
button:focus-visible { border-radius: 2px; outline: 2px solid token.$crm-focus; outline-offset: 2px; }
</style>
