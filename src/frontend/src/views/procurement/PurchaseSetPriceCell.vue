<script setup lang="ts">
import { ArrowDown, Check } from '@element-plus/icons-vue'
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
      <ElDropdown v-if="allowSet" trigger="click" placement="bottom-end" :persistent="false" :disabled="disabled"
        @command="$event === 'SET' && emit('editSet')">
        <button type="button" class="pricing-unit" aria-label="单价计价方式" :disabled="disabled">
          {{ unit }}<ElIcon><ArrowDown /></ElIcon>
        </button>
        <template #dropdown>
          <ElDropdownMenu class="pricing-menu">
            <ElDropdownItem command="UNIT" class="pricing-current">{{ unit }}<ElIcon><Check /></ElIcon></ElDropdownItem>
            <ElDropdownItem command="SET" data-testid="purchase-pricing-by-set">按套</ElDropdownItem>
          </ElDropdownMenu>
        </template>
      </ElDropdown>
      <span v-else>{{ unit }}</span>
    </template>
  </ElInput>
</template>

<style scoped>
.pricing-unit { display: inline-flex; align-items: center; justify-content: center; gap: 4px; min-height: 30px; padding: 0; border: 0; background: transparent; color: var(--erp-color-primary); font: inherit; font-size: 12px; white-space: nowrap; cursor: pointer; }
.pricing-unit:hover { color: var(--el-color-primary-dark-2); }
.pricing-unit:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 1px; border-radius: var(--erp-radius-control); }
.pricing-unit:disabled { color: var(--el-disabled-text-color); cursor: default; }
.pricing-menu { min-width: 114px; }
.pricing-current { justify-content: space-between; gap: 12px; color: var(--erp-color-primary); }
.pricing-current .el-icon { margin: 0; }
.set-price-link { width: 100%; background: transparent; border: 0; color: var(--el-color-primary); font: inherit; cursor: pointer; }
.set-price-link:disabled { color: inherit; cursor: default; }
</style>
