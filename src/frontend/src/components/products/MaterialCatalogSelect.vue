<script setup lang="ts">
import { ref, watchEffect } from 'vue'
import { ElOption, ElSelect, type SelectInstance } from 'element-plus'
import { Check } from '@element-plus/icons-vue'
import type { Modifier } from '@popperjs/core'

const props = withDefaults(defineProps<{
  modelValue: string
  options: { value: string; label: string; disabled?: boolean }[]
  placeholder?: string
  disabled?: boolean
  invalid?: boolean
  ariaLabel: string
}>(), { placeholder: '请选择', disabled: false, invalid: false })

const emit = defineEmits<{
  'update:modelValue': [value: string]
  change: [value: string]
}>()
const select = ref<SelectInstance>()

// ElSelect 的 aria-label 原生传给输入；错误状态也应落在同一个组合框上。
watchEffect(() => select.value?.inputRef?.setAttribute('aria-invalid', String(props.invalid)))

// 上下两侧都不足 240px 时，让列表在可用高度内滚动，不遮住触发控件。
const availableHeight: Modifier<'catalogAvailableHeight', Record<string, never>> = {
  name: 'catalogAvailableHeight', enabled: true, phase: 'beforeWrite', requires: ['computeStyles'],
  fn({ state }) {
    const rect = state.elements.reference.getBoundingClientRect()
    const height = state.placement.startsWith('top') ? rect.top : document.documentElement.clientHeight - rect.bottom
    Object.assign(state.styles.popper, { '--material-catalog-list-max-height': `${Math.max(32, Math.min(240, height - 14))}px` })
  },
}
const popperOptions = {
  modifiers: [availableHeight, { name: 'preventOverflow', options: { padding: 8 } }, { name: 'flip', options: { padding: 8 } }],
}

function updateValue(value: unknown) {
  if (typeof value === 'string') emit('update:modelValue', value)
}
function changeValue(value: unknown) {
  if (typeof value === 'string') emit('change', value)
}
function focus() {
  if (!props.disabled) select.value?.focus()
}
defineExpose({ focus })
</script>

<template>
  <ElSelect
    ref="select"
    class="material-catalog-select"
    :class="{ 'is-invalid': invalid, 'is-empty': modelValue === '' }"
    :data-model-value="modelValue"
    :model-value="modelValue"
    :aria-label="ariaLabel"
    :placeholder="placeholder"
    :disabled="disabled"
    :tabindex="disabled ? -1 : 0"
    :show-arrow="false"
    :offset="4"
    :teleported="true"
    :popper-options="popperOptions"
    :fallback-placements="['top-start', 'bottom-start']"
    popper-class="material-catalog-select-popper"
    no-data-text="暂无可选项"
    @update:model-value="updateValue"
    @change="changeValue"
  >
    <ElOption
      v-for="option in options"
      :key="option.value"
      :value="option.value"
      :label="option.label"
      :disabled="option.disabled"
      :data-value="option.value"
      :title="option.label"
    >
      <slot name="option" :option="option" :selected="option.value === modelValue">
        <span class="material-catalog-select-option-label">{{ option.label }}<span v-if="option.disabled">（不可选）</span></span>
        <Check v-if="option.value === modelValue" class="material-catalog-select-check" aria-hidden="true" />
      </slot>
    </ElOption>
  </ElSelect>
</template>

<style scoped>
.material-catalog-select { width: 100%; min-width: 0; font-size: 13px; }
.material-catalog-select :deep(.el-select__wrapper) {
  box-sizing: border-box; height: 32px; min-height: 32px; padding: 0 10px;
  border: 1px solid #ddd6c9; border-radius: 5px; background: #fcfbf7;
  color: #1f1d18; box-shadow: none; font-size: 13px; line-height: 20px;
}
.material-catalog-select :deep(.el-select__wrapper.is-hovering:not(.is-focused)) { box-shadow: none; }
.material-catalog-select :deep(.el-select__wrapper.is-focused) { border-color: #3898ec; box-shadow: none; }
.material-catalog-select :deep(.el-select__wrapper:has(.el-select__input:focus-visible)) { outline: 2px solid #3898ec; outline-offset: 2px; }
.material-catalog-select.is-invalid :deep(.el-select__wrapper) { border-color: #b53333; }
.material-catalog-select :deep(.el-select__placeholder) { color: #1f1d18; }
.material-catalog-select.is-empty :deep(.el-select__wrapper:not(.is-disabled) .el-select__placeholder) { color: #968f84; }
.material-catalog-select :deep(.el-select__caret) { color: #6f6a61; font-size: 16px; }
.material-catalog-select :deep(.el-select__input) {
  height: 20px; min-height: 0; padding: 0; border: 0; border-radius: 0;
  color: #1f1d18; background: transparent; box-shadow: none; outline: none; font: inherit;
}
.material-catalog-select :deep(.el-select__wrapper.is-disabled),
.material-catalog-select :deep(.el-select__wrapper.is-disabled:hover) {
  border-color: #ddd6c9; background: #e8e1d5; color: #6f6a61; opacity: 1; box-shadow: none; outline: none;
}
.material-catalog-select :deep(.el-select__wrapper.is-disabled .el-select__selected-item) { color: #6f6a61; }
</style>

<style>
/* 弹层挂到 body；专用类将这些规范限定在原料管理的选择器。 */
.material-catalog-select-popper.el-popper {
  box-sizing: border-box; max-width: calc(100vw - 16px); padding: 0; overflow: hidden;
  border: 1px solid #ddd6c9; border-radius: 5px; background: #fcfbf7; box-shadow: none;
  color: #1f1d18; font-family: inherit; font-size: 13px;
}
.material-catalog-select-popper .el-select-dropdown { border: 0; border-radius: 5px; background: transparent; box-shadow: none; }
.material-catalog-select-popper .el-select-dropdown__wrap { max-height: var(--material-catalog-list-max-height, 240px); }
.material-catalog-select-popper .el-select-dropdown__list { padding: 0; }
.material-catalog-select-popper .el-select-dropdown__item {
  display: flex; align-items: center; gap: 8px; box-sizing: border-box; height: 32px;
  padding: 0 10px; border: 0; color: #1f1d18; background: #fcfbf7;
  font-size: 13px; font-weight: 400; line-height: 20px;
}
.material-catalog-select-popper .el-select-dropdown__item:hover,
.material-catalog-select-popper .el-select-dropdown__item.is-hovering { background: #fff6ea; }
.material-catalog-select-popper .el-select-dropdown__item.is-selected,
.material-catalog-select-popper .el-select-dropdown__item.is-selected:hover,
.material-catalog-select-popper .el-select-dropdown__item.is-selected.is-hovering { background: #fff4e6; color: #c84e28; font-weight: 400; }
.material-catalog-select-popper .el-select-dropdown__item.is-disabled,
.material-catalog-select-popper .el-select-dropdown__item.is-disabled.is-hovering,
.material-catalog-select-popper .el-select-dropdown__item.is-disabled:hover { color: #6f6a61; background: #fcfbf7; cursor: not-allowed; }
.material-catalog-select-popper .material-catalog-select-option-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.material-catalog-select-popper .material-catalog-select-check { flex: 0 0 16px; width: 16px; height: 16px; }
.material-catalog-select-popper .el-select-dropdown__empty { color: #6f6a61; font-size: 13px; }
</style>
