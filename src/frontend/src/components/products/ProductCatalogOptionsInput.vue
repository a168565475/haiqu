<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { Delete, Plus } from '@element-plus/icons-vue'
const props = withDefaults(defineProps<{ modelValue: string[]; label: string; maxLength?: number; readonly?: boolean; disabled?: boolean }>(), { maxLength: 200 })
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()
const container = ref<HTMLElement>()
function update(index: number, event: Event) {
  if (props.readonly || props.disabled || !(event.target instanceof HTMLInputElement)) return
  const values = [...props.modelValue]
  values[index] = event.target.value
  emit('update:modelValue', values)
}
async function add() {
  if (props.readonly || props.disabled) return
  emit('update:modelValue', [...props.modelValue, ''])
  await nextTick()
  const inputs = container.value?.querySelectorAll('input')
  inputs?.[inputs.length - 1]?.focus()
}
function remove(index: number) {
  if (!props.readonly && !props.disabled) emit('update:modelValue', props.modelValue.filter((_, position) => position !== index))
}
</script>

<template>
  <div ref="container" class="product-options" :aria-label="label">
    <span v-for="(value, index) in modelValue" :key="index" class="product-option">
      <span v-if="readonly" class="option-value">{{ value }}</span>
      <template v-else>
        <input class="erp-list-control" :value="value" :aria-label="`${label}${index + 1}`" :placeholder="`输入${label}`" :maxlength="maxLength" autocomplete="off" :disabled="disabled" @input="update(index, $event)" @keydown.enter.prevent />
        <button class="erp-list-button erp-button-motion option-delete" type="button" :aria-label="`删除${label}${index + 1}`" :title="`删除${label}`" :disabled="disabled" @click="remove(index)"><Delete aria-hidden="true" /></button>
      </template>
    </span>
    <span v-if="readonly && !modelValue.length" class="empty-options">—</span>
    <button v-if="!readonly" class="erp-list-button erp-list-button--primary erp-button-motion add-option" type="button" :aria-label="`添加${label}`" :disabled="disabled" @click="add"><Plus aria-hidden="true" />添加</button>
  </div>
</template>

<style scoped>
.product-options { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; min-height: 32px; }
.product-option { position: relative; display: inline-flex; max-width: 100%; }
.product-option input { width: 132px; height: 28px; padding-right: 26px; font-size: 12px; }
.option-value { white-space: pre-wrap; overflow-wrap: anywhere; }
.option-delete { position: absolute; top: 1px; right: 1px; width: 24px; height: 26px; min-height: 0; padding: 0; opacity: 0; pointer-events: none; }
.product-option:hover .option-delete, .product-option:focus-within .option-delete, .option-delete:focus-visible { opacity: 1; pointer-events: auto; }
.add-option { height: 28px; min-height: 0; padding: 0 6px; font-size: 12px; }
svg { width: 14px; height: 14px; }
.empty-options { color: var(--erp-color-text-secondary); }
@media (hover: none) { .option-delete { opacity: 1; pointer-events: auto; } }
</style>
