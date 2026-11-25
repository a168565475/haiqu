<script setup lang="ts">
import { computed, ref } from 'vue'
import { Cell as VanCell, Icon as VanIcon, Popup as VanPopup } from 'vant'
import 'vant/es/cell/style'
import 'vant/es/icon/style'
import 'vant/es/popup/style'

const props = defineProps<{
  label: string
  modelValue: string
  choices: { value: string; label: string }[]
  disabled?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const show = ref(false)
const trigger = ref<HTMLButtonElement>()
const selectedLabel = computed(() => props.choices.find(option => option.value === props.modelValue)?.label)

function close() {
  show.value = false
  trigger.value?.focus()
}

function select(value: string) {
  close()
  if (value !== props.modelValue) emit('update:modelValue', value)
}

function keepFocus(event: KeyboardEvent) {
  const panel = event.currentTarget as HTMLElement
  const buttons = panel.querySelectorAll<HTMLButtonElement>('button')
  const first = buttons[0]!
  const last = buttons[buttons.length - 1]!
  const active = document.activeElement
  if (event.shiftKey && (active === first || active === panel)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first.focus()
  }
}
</script>

<template>
  <div>
    <button ref="trigger" type="button" class="wage-option-trigger" :disabled="disabled || !choices.length"
      aria-haspopup="dialog" :aria-expanded="show" @click="show = true">
      <span>{{ label }}</span>
      <span class="wage-option-value" :class="{ 'is-placeholder': !selectedLabel }">{{ selectedLabel || `请选择${label}` }}</span>
      <VanIcon name="arrow" size="16" aria-hidden="true" />
    </button>
    <VanPopup :show="show" class="wage-picker" position="bottom" round teleport="body" safe-area-inset-bottom close-on-popstate
      :aria-label="`选择${label}`" aria-modal="true" :tabindex="0"
      @update:show="close" @keydown.esc.stop.prevent="close" @keydown.tab="keepFocus">
      <div class="wage-picker-heading">
        <h2>选择{{ label }}</h2>
        <button type="button" class="wage-picker-close" aria-label="关闭选项" @click="close">
          <VanIcon name="cross" size="20" aria-hidden="true" />
        </button>
      </div>
      <div class="wage-picker-options">
        <VanCell v-for="option in choices" :key="option.value" tag="button" type="button" clickable center
          class="wage-picker-option" :title="option.label" :aria-pressed="option.value === modelValue" @click="select(option.value)">
          <template v-if="option.value === modelValue" #right-icon><VanIcon name="success" aria-hidden="true" /></template>
        </VanCell>
      </div>
    </VanPopup>
  </div>
</template>

<style scoped>
.wage-option-trigger { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 48px; padding: 8px 0; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.wage-option-trigger > span:first-child { flex-shrink: 0; font-weight: 600; }
.wage-option-value { flex: 1; min-width: 0; text-align: right; overflow-wrap: anywhere; }
.wage-option-trigger .van-icon { flex-shrink: 0; color: var(--mobile-muted); }
.is-placeholder, .wage-option-trigger:disabled { color: var(--mobile-muted); }
.wage-picker { width: min(100%, 640px); right: 0; left: 0; margin-inline: auto; }
.wage-picker-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 4px 8px 4px 16px; border-bottom: 1px solid var(--mobile-border); }
.wage-picker-heading h2 { margin: 0; font-size: 18px; }
.wage-picker-close { display: grid; place-items: center; width: 44px; height: 44px; padding: 0; border: 0; background: transparent; color: var(--mobile-muted); cursor: pointer; }
.wage-picker-options { max-height: 60dvh; overflow-y: auto; overscroll-behavior: contain; }
.wage-picker-option { min-height: 48px; border: 0; text-align: left; overflow-wrap: anywhere; }
.wage-picker-option[aria-pressed="true"] { background: var(--mobile-primary-soft); color: var(--mobile-primary); font-weight: 600; }
.wage-picker-option:focus-visible { outline-offset: -3px; }
</style>
