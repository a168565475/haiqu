<script setup lang="ts">
import { setPriceText, type SetPricingLine } from './purchaseSetPricing'

defineProps<{
  line: Pick<SetPricingLine, 'set_pricing' | 'purchase_group_line_id'> & { unit_price: string | null }
  unit: string
  disabled?: boolean
  allowSet?: boolean
  label?: string
}>()
const emit = defineEmits<{ input: [value: string]; editSet: [] }>()
</script>

<template>
  <button v-if="line.set_pricing" type="button" class="set-price-link" :disabled="disabled" @click="emit('editSet')">{{ setPriceText(line) }}</button>
  <ElInput v-else :model-value="line.unit_price" inputmode="decimal" maxlength="24" placeholder="请输入" :aria-label="label" :disabled="disabled" @update:model-value="emit('input', $event)">
    <template #append>
      <select v-if="allowSet" class="pricing-unit" aria-label="单价计价方式" :disabled="disabled" @keydown.stop @change="($event.target as HTMLSelectElement).value = 'UNIT'; emit('editSet')">
        <option value="UNIT">{{ unit }}</option>
        <option value="SET">按套</option>
      </select>
      <span v-else>{{ unit }}</span>
    </template>
  </ElInput>
</template>

<style scoped>
.pricing-unit { border: 0; background: transparent; color: inherit; font: inherit; cursor: pointer; }
.set-price-link { width: 100%; background: transparent; border: 0; color: var(--el-color-primary); font: inherit; cursor: pointer; }
.set-price-link:disabled { color: inherit; cursor: default; }
</style>
