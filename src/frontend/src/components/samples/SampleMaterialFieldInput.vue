<script setup lang="ts">
import PinyinFilterSelect from '@/components/production/PinyinFilterSelect.vue'
import { computed } from 'vue'
import type { SampleMaterialOption, SampleMaterialReferences } from '@/types/sampleMaterial'
const props = defineProps<{ modelValue: string; options?: SampleMaterialOption[]; disabled?: boolean; label: string; placeholder: string; maxlength: number; selectionOnly?: boolean; tubeSpecification?: boolean; references?: SampleMaterialReferences | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const specifications = computed(() => {
  const options: Array<{ value: string; label: string; disabled?: boolean; children?: Array<{ value: string; label: string }> }> = (props.references?.tubeDiameters || []).map(diameter => ({
    value: `diameter:${diameter.label}`, label: diameter.label,
    children: (props.references?.tubeThicknesses || []).map(thickness => ({ value: `${diameter.label} × ${thickness.label}`, label: `${diameter.label} × ${thickness.label}` })),
  }))
  if (props.modelValue && !options.some(item => item.children?.some(child => child.value === props.modelValue))) options.unshift({ value: props.modelValue, label: props.modelValue, disabled: true })
  return options
})
</script>
<template>
  <ElCascader v-if="tubeSpecification" :model-value="modelValue || undefined" :options="specifications" :props="{ emitPath: false }" :show-all-levels="false" clearable filterable :disabled="disabled" :aria-label="label" placeholder="选择直径 / 厚度" @update:model-value="emit('update:modelValue', typeof $event === 'string' ? $event : '')" />
  <PinyinFilterSelect v-else-if="selectionOnly || options?.length" :model-value="modelValue" :options="options || []" label-key="label" :allow-create="!selectionOnly" :disabled="disabled" :aria-label="label" :placeholder="`选择${placeholder}`" @update:model-value="emit('update:modelValue', $event)" />
  <ElInput v-else :model-value="modelValue" :disabled="disabled" :aria-label="label" :placeholder="placeholder" :maxlength="maxlength" @update:model-value="emit('update:modelValue', $event)" />
</template>
<style scoped lang="scss">
.el-cascader { width: 100%; }
</style>
