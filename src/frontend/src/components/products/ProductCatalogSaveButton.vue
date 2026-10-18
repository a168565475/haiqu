<script setup lang="ts">
import { ref } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { ElTooltip } from 'element-plus'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{
  label: string
  ariaLabel: string
  loading?: boolean
  disabled?: boolean
  type?: 'button' | 'submit'
}>(), { loading: false, disabled: false, type: 'button' })
const emit = defineEmits<{ click: [event: MouseEvent] }>()
const hovered = ref(false)
const focused = ref(false)
function click(event: MouseEvent) {
  if (props.loading || props.disabled) { event.preventDefault(); event.stopPropagation(); return }
  emit('click', event)
}
function keydown(event: KeyboardEvent) {
  if ((props.loading || props.disabled) && ['Enter', ' '].includes(event.key)) event.preventDefault()
}
</script>

<template>
  <ElTooltip :visible="loading && (hovered || focused)" :persistent="false" :show-after="0" :hide-after="0" content="处理中…" placement="top" popper-class="product-catalog-saving-popper">
    <button v-bind="$attrs" class="erp-list-button erp-button-motion erp-list-button--primary catalog-save-button" :type="type" :aria-label="loading ? `${ariaLabel}，处理中…` : ariaLabel" :aria-busy="loading" :aria-disabled="loading || disabled" :disabled="disabled && !loading"
      @mouseenter="hovered = true" @mouseleave="hovered = false" @focus="focused = true" @blur="focused = false" @click="click" @keydown="keydown">
      <span data-save-label :class="{ 'label-placeholder': loading }">{{ label }}</span>
      <Loading v-if="loading" data-save-spinner class="save-spinner" aria-hidden="true" />
      <span v-if="loading" class="save-status" role="status">处理中…</span>
    </button>
  </ElTooltip>
</template>

<style scoped lang="scss">
.catalog-save-button { position: relative; min-width: 48px; flex-shrink: 0; padding: 0 8px; }
.catalog-save-button[aria-busy='true'] { cursor: progress; }
.label-placeholder { visibility: hidden; }
.save-spinner { position: absolute; top: calc(50% - 8px); left: calc(50% - 8px); width: 16px; height: 16px; animation: product-catalog-save-spin 1s linear infinite; }
.save-status { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
@keyframes product-catalog-save-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .save-spinner { animation: none; } }
</style>
<style lang="scss">
.product-catalog-saving-popper.el-popper { padding: 8px 12px; border: 1px solid var(--erp-tooltip-border); border-radius: var(--erp-radius-control); color: var(--erp-color-text-primary); background: var(--erp-tooltip-background); box-shadow: var(--erp-overlay-shadow); font-size: 12px; line-height: 18px; }
.product-catalog-saving-popper.el-popper .el-popper__arrow::before { border-color: var(--erp-tooltip-border); background: var(--erp-tooltip-background); }
</style>
