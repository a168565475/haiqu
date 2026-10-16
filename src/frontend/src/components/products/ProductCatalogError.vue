<script lang="ts">
import { shallowRef } from 'vue'

// 同模块只允许一个错误气泡，不由每个 ElTooltip 各自保留展开状态。
const activeProductCatalogError = shallowRef<symbol | null>(null)
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { WarningFilled } from '@element-plus/icons-vue'
import { ElTooltip } from 'element-plus'

defineProps<{ message: string }>()
const identity = Symbol('product-catalog-error')
const visible = computed(() => activeProductCatalogError.value === identity)
const trigger = ref<HTMLElement>()
const content = ref<HTMLElement>()
const hovered = ref(false)
const focused = ref(false)
const contentHovered = ref(false)
let closeTimer: ReturnType<typeof setTimeout> | undefined
function clearCloseTimer() { clearTimeout(closeTimer); closeTimer = undefined }
function open() { clearCloseTimer(); activeProductCatalogError.value = identity }
function close() { clearCloseTimer(); if (visible.value) activeProductCatalogError.value = null }
function enterTrigger() {
  if (hovered.value) return
  hovered.value = true
  open()
}
function focusTrigger() {
  if (focused.value) return
  focused.value = true
  open()
}
function scheduleClose() {
  clearCloseTimer()
  closeTimer = setTimeout(() => { if (!hovered.value && !focused.value && !contentHovered.value) close() }, 120)
}
function outsideClick(event: Event) {
  if (!visible.value || !(event.target instanceof Node)) return
  const popper = content.value?.closest('.product-catalog-error-popper')
  if (!trigger.value?.contains(event.target) && !popper?.contains(event.target)) close()
}
function escape(event: KeyboardEvent) { if (event.key === 'Escape') close() }
watch(visible, value => { if (!value) { contentHovered.value = false; clearCloseTimer() } })
onMounted(() => {
  document.addEventListener('pointerdown', outsideClick, true)
  document.addEventListener('click', outsideClick, true)
  document.addEventListener('keydown', escape, true)
})
onBeforeUnmount(() => {
  close()
  document.removeEventListener('pointerdown', outsideClick, true)
  document.removeEventListener('click', outsideClick, true)
  document.removeEventListener('keydown', escape, true)
})
</script>

<template>
  <ElTooltip :visible="visible" :persistent="false" :show-after="0" :hide-after="0" placement="top" popper-class="product-catalog-error-popper">
    <template #content><div ref="content" data-error-content @mouseenter="contentHovered = true; clearCloseTimer()" @mouseleave="contentHovered = false; scheduleClose()">{{ message }}</div></template>
    <span ref="trigger" class="product-catalog-field-error" role="alert" :aria-label="message" tabindex="0"
      @mouseenter="enterTrigger" @mouseleave="hovered = false; scheduleClose()" @focus="focusTrigger" @blur="focused = false; scheduleClose()" @click="open"
      @keydown.enter.prevent="open" @keydown.space.prevent="open"><WarningFilled aria-hidden="true" /><span class="error-announcement">{{ message }}</span></span>
  </ElTooltip>
</template>

<style scoped lang="scss">
.product-catalog-field-error { position: absolute; right: 0; top: -6px; z-index: 1; display: flex; color: #b53333; background: #fcfbf7; border-radius: 5px; }
svg { width: 16px; height: 16px; }
.product-catalog-field-error:focus-visible { outline: 2px solid #3898ec; outline-offset: 2px; }
.error-announcement { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
</style>
<style lang="scss">
.product-catalog-error-popper.el-popper { max-width: min(300px, calc(100vw - 16px)); padding: 8px 12px; border: 1px solid #b53333; border-radius: 5px; color: #b53333; background: #fcfbf7; box-shadow: none; font-size: 12px; line-height: 18px; }
.product-catalog-error-popper.el-popper .el-popper__arrow::before { border-color: #b53333; background: #fcfbf7; }
</style>
