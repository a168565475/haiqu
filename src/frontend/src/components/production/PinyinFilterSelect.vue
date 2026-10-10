<script setup lang="ts">
import { computed, ref } from 'vue'

import { matchesPinyinSearch } from '@/utils/pinyinSearch'

defineOptions({ inheritAttrs: false })

const props = defineProps<{
  modelValue: string
  options: unknown[]
  labelKey: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const query = ref('')

function optionRecord(option: unknown): Record<string, unknown> {
  return option && typeof option === 'object' ? option as Record<string, unknown> : {}
}

function optionLabel(option: unknown): string {
  return String(optionRecord(option)[props.labelKey] ?? '')
}

function optionKey(option: unknown, index: number): string {
  return String(optionRecord(option).id ?? `${optionLabel(option)}-${index}`)
}

const visibleOptions = computed(() => props.options.filter((option) => {
  const record = optionRecord(option)
  return matchesPinyinSearch(record[props.labelKey], record.pinyin_search, query.value)
}))

function filterOptions(value: string): void {
  query.value = value
}

function updateModelValue(value: unknown): void {
  emit('update:modelValue', typeof value === 'string' ? value : '')
  query.value = ''
}

function handleVisibleChange(visible: boolean): void {
  if (!visible) query.value = ''
}
</script>

<template>
  <ElSelect
    class="pinyin-filter-select"
    v-bind="$attrs"
    :model-value="modelValue"
    filterable
    clearable
    default-first-option
    :value-on-clear="''"
    :filter-method="filterOptions"
    @update:model-value="updateModelValue"
    @visible-change="handleVisibleChange"
  >
    <ElOption
      v-for="(option, index) in visibleOptions"
      :key="optionKey(option, index)"
      :label="optionLabel(option)"
      :value="optionLabel(option)"
    />
  </ElSelect>
</template>

<style scoped lang="scss">
.pinyin-filter-select {
  width: 100%;
}
</style>
