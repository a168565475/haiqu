<script setup lang="ts">
import { computed } from 'vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
const props = withDefaults(defineProps<{
  modelValue: boolean; title: string; subtitle?: string; width: number; height: number
  confirmLabel?: string; cancelLabel?: string; confirmWidth?: number; cancelWidth?: number; busy?: boolean; loading?: boolean; disabled?: boolean; danger?: boolean; error?: string
}>(), { subtitle: '', confirmLabel: '确认', cancelLabel: '取消', confirmWidth: 96, cancelWidth: 92, busy: false, loading: false, disabled: false, danger: false, error: '' })
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; confirm: [] }>()
const visible = computed({ get: () => props.modelValue, set: value => { if (!props.busy) emit('update:modelValue', value) } })
</script>

<template>
  <AppWindowDialog v-model="visible" :title="title" :width="width" :height="height" destroy-on-close
    class="inquiry-action-dialog"
    :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy">
    <div v-loading="loading" class="inquiry-dialog-content" :aria-busy="busy || loading">
      <p v-if="subtitle" class="inquiry-dialog-subtitle">{{ subtitle }}</p>
      <p v-if="error" class="inquiry-dialog-error" role="alert">{{ error }}</p>
      <slot />
    </div>
    <template #footer>
      <el-button :style="{ minWidth: `${cancelWidth}px` }" :disabled="busy" @click="visible = false">{{ cancelLabel }}</el-button>
      <el-button :style="{ minWidth: `${confirmWidth}px` }" :type="danger ? 'danger' : 'primary'" :loading="busy" :disabled="disabled || loading" @click="!busy && emit('confirm')">{{ confirmLabel }}</el-button>
    </template>
  </AppWindowDialog>
</template>

<style lang="scss">
@use '@/styles/crm/tokens' as token;
// INQ-V4-03/04 使用 Warm ERP 弹层变量，与详情页卡片样式分别作用于各自容器。
$surface: var(--erp-color-subtle);
$border: var(--erp-color-border);
$primary: var(--erp-color-brand);
.el-overlay.inquiry-v4-overlay { background: color-mix(in srgb, var(--erp-overlay-scrim-color) 38%, transparent); }
.inquiry-v4-select {
  --el-color-primary: var(--erp-color-brand); --el-fill-color-light: var(--erp-color-subtle); --el-border-color-light: var(--erp-color-border);
  font-family: token.$crm-font-body;
  &.el-popper { border-color: var(--erp-color-border); border-radius: 6px; box-shadow: 0 6px 24px color-mix(in srgb, var(--erp-shadow-color) 8%, transparent); }
  .el-dropdown-menu { background: var(--erp-color-subtle); }
  .el-dropdown-menu__item,.el-select-dropdown__item { font-size: 13px; }
  .el-dropdown-menu__item:not(.is-disabled):focus,.el-dropdown-menu__item:not(.is-disabled):hover { background: var(--erp-dropdown-hover-background); color: var(--erp-dropdown-selected-text); }
}
.el-dialog.inquiry-action-dialog {
  --el-color-primary: #{$primary}; --el-color-primary-light-9: var(--erp-color-selected); --el-border-color: #{$border};
  --el-border-color-hover: var(--erp-color-border); --el-border-radius-base: 6px; --el-text-color-primary: var(--erp-color-text-primary);
  --el-text-color-regular: var(--erp-color-text-primary); --el-fill-color-blank: var(--erp-color-surface);
  display: flex; flex-direction: column; max-height: calc(100dvh - 32px);
  padding: 0; margin: 0; overflow: hidden; color: var(--erp-color-text-primary); font: 13px/20px var(--erp-font-body);
  .el-dialog__header { flex: 0 0 44px; min-height: 44px; box-sizing: border-box; padding: 0 104px 0 16px; margin: 0; border-bottom: 1px solid $border; }
  .el-dialog__title { font: 600 16px/24px var(--erp-font-body); }
  .inquiry-dialog-subtitle { margin: 0 0 14px; color: var(--erp-color-text-regular); font-size: 12px; line-height: 20px; }
  .el-dialog__body { flex: 1; min-height: 0; padding: 18px 23px; overflow-y: auto; color: inherit; font: inherit; }
  .inquiry-dialog-content { min-height: 100%; }
  .el-dialog__footer { flex: 0 0 56px; display: flex; align-items: center; justify-content: flex-end; gap: 12px; padding: 12px 23px; border-top: 1px solid $border; }
  .el-button { min-width: 92px; height: 32px; margin: 0; padding: 0 18px; border-radius: 8px; border-color: $border; background: var(--erp-button-secondary-surface); color: var(--erp-color-text-primary); font: 500 13px/22px token.$crm-font-body; }
  .el-button--primary { background: var(--erp-button-primary-surface); border-color: var(--erp-button-primary-border); color: var(--erp-button-primary-text); }
  .el-button--danger { background: token.$crm-danger; border-color: token.$crm-danger; color: var(--erp-color-text-inverse); }
  .el-button:hover:not(:disabled) { filter: brightness(.96); }
  .el-button:active:not(:disabled) { filter: brightness(.91); }
  .el-button.is-disabled { opacity: .5; cursor: not-allowed; }
  button:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 2px; }
  .el-form { margin-top: 14px; }
  .el-form-item { margin: 0 0 14px; }
  .el-form-item__label { height: auto; margin: 0; padding: 0 0 7px; font: 500 12px/20px token.$crm-font-body; color: var(--erp-color-text-primary); }
  .el-form-item.is-required:not(.is-no-asterisk) > .el-form-item__label::before { display: none; }
  .el-form-item.is-required:not(.is-no-asterisk) > .el-form-item__label::after { content: ' *'; margin-left: 3px; }
  .el-form-item__content { line-height: 22px; }
  .el-input__wrapper, .el-select__wrapper { min-height: 32px; box-shadow: 0 0 0 1px $border inset; border-radius: 8px; padding: 1px 12px; background: var(--erp-input-background); }
  .el-input__wrapper.is-focus, .el-select__wrapper.is-focused { box-shadow: 0 0 0 1px token.$crm-focus inset; }
  .el-input__inner, .el-select__selected-item { font: 13px token.$crm-font-body; color: var(--erp-color-text-primary); }
  .el-textarea__inner { padding: 10px 12px; border-radius: 8px; box-shadow: 0 0 0 1px $border inset; font: 13px/22px token.$crm-font-body; resize: none; }
  .el-input, .el-select, .el-date-editor { width: 100%; }
  .inquiry-form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .inquiry-dialog-hint { margin: 0; color: var(--erp-color-text-regular); font-size: 12px; line-height: 20px; }
  .inquiry-dialog-error { padding: 10px 12px; margin: 0 0 14px; color: token.$crm-danger; background: token.$crm-danger-soft; border: 1px solid token.$crm-danger-border; border-radius: 8px; overflow-wrap: anywhere; }
  .inquiry-check-list { display: grid; gap: 14px; margin: 14px 0 0; padding: 0; list-style: none; font-size: 13px; line-height: 26px;
    li { display: flex; gap: 18px; align-items: center; }
    b { color: token.$crm-success; font-size: 18px; font-weight: 400; }
    .incomplete b { color: token.$crm-warning; }
  }
}
</style>
