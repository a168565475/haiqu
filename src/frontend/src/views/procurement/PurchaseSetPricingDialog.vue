<script setup lang="ts">
import { computed, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { PurchaseOrderSupplierOption } from '@/types/purchaseOrder'
import { setAmount, type SetPricingChange, type SetPricingLine } from './purchaseSetPricing'

interface Candidate extends SetPricingLine {
  quantityText: string
  eligible: boolean
}

const props = defineProps<{ source: Candidate; lines: Candidate[]; suppliers: PurchaseOrderSupplierOption[]; defaultQuantity: string }>()
const emit = defineEmits<{ close: []; apply: [change: SetPricingChange] }>()
const current = props.source.set_pricing
const anchorId = current?.anchor_id ?? props.source.purchase_group_line_id!
const anchor = props.lines.find(line => line.purchase_group_line_id === anchorId)!
const members = ref(current
  ? props.lines.filter(line => line.set_pricing?.anchor_id === anchorId).map(line => line.purchase_group_line_id!)
  : [anchorId])
const quantity = ref(current ? String(current.quantity) : props.defaultQuantity)
const price = ref(current?.unit_price ?? '')
const supplierId = ref<string | null>(anchor.supplier_id)
const deliveryDate = ref(anchor.delivery_date || '')
const search = ref('')
const materialName = (line: Candidate) => line.part_name || line.material || line.raw_material
const matching = computed(() => {
  const key = search.value.trim().toLowerCase()
  return props.lines.filter(line => line.purchase_group_line_id && [materialName(line), line.specification].join(' ').toLowerCase().includes(key))
})
const selected = computed(() => props.lines.filter(line => members.value.includes(line.purchase_group_line_id || '')))
const valid = computed(() => selected.value.length >= 2 && selected.value.every(line => line.eligible)
  && /^\d{1,14}$/.test(quantity.value) && Number(quantity.value) > 0
  && /^\d{1,14}(\.\d{1,4})?$/.test(price.value) && Number(price.value) > 0)
const changingTerms = computed(() => selected.value.some(line =>
  (line.supplier_id && line.supplier_id !== supplierId.value) || (line.delivery_date && line.delivery_date !== deliveryDate.value)))
function submit(split: boolean) {
  if (!split && !valid.value) return
  emit('apply', {
    anchorId, members: split ? [] : members.value,
    pricing: split ? null : { anchor_id: anchorId, quantity: Number(quantity.value), unit_price: price.value },
    supplierId: supplierId.value || null, deliveryDate: deliveryDate.value || '',
  })
}
</script>

<template>
  <AppWindowDialog :model-value="true" title="按套计价" :width="900" :min-width="280" :minimizable="false"
    :close-on-click-modal="false" @update:model-value="value => { if (!value) emit('close') }">
    <div class="set-form">
      <section class="part-selection" aria-label="关联部件">
        <div class="selection-heading"><strong>关联部件</strong><span>已选 {{ selected.length }} 项</span></div>
        <ElInput v-model="search" :prefix-icon="Search" aria-label="搜索本单部件" placeholder="搜索品名或规格" clearable />
        <ElCheckboxGroup v-model="members" class="materials" aria-label="可选部件">
          <ElCheckbox v-for="line in matching" :key="line.purchase_group_line_id!" :value="line.purchase_group_line_id!"
            :disabled="line.purchase_group_line_id === anchorId || (!line.eligible && !members.includes(line.purchase_group_line_id!)) || Boolean(line.set_pricing && line.set_pricing.anchor_id !== anchorId)">
            <span class="part-description"><strong>{{ materialName(line) }}</strong><small v-if="line.specification">{{ line.specification }}</small></span>
            <span class="part-quantity">{{ line.set_pricing && line.set_pricing.anchor_id !== anchorId ? '已在其他套餐' : (line.quantityText || '0') + ' ' + line.source_unit_text }}</span>
          </ElCheckbox>
          <div v-if="!matching.length" class="empty">没有匹配的材料</div>
        </ElCheckboxGroup>
        <div v-if="search && selected.length" class="chosen">已选部件：{{ selected.map(materialName).join('、') }}</div>
      </section>
      <ElForm class="terms" label-position="top" @submit.prevent>
        <ElFormItem label="采购套数">
          <ElInput v-model="quantity" inputmode="numeric" maxlength="14" aria-label="采购套数"><template #suffix>套</template></ElInput>
        </ElFormItem>
        <ElFormItem label="每套单价">
          <ElInput v-model="price" inputmode="decimal" maxlength="19" aria-label="每套单价"><template #suffix>元/套</template></ElInput>
        </ElFormItem>
        <ElFormItem class="full-field" label="供应商">
          <ElSelect v-model="supplierId" filterable clearable aria-label="套餐供应商" placeholder="请选择供应商">
            <ElOption v-for="supplier in suppliers" :key="supplier.id" :value="supplier.id" :label="supplier.supplier_name" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem class="full-field" label="采购交期">
          <ElDatePicker v-model="deliveryDate" type="date" value-format="YYYY-MM-DD" aria-label="套餐采购交期" placeholder="选择采购交期" />
        </ElFormItem>
        <small v-if="changingTerms" class="full-field">应用后，所选部件将统一使用这里的供应商和交期。</small>
      </ElForm>
    </div>
    <template #footer><div class="footer">
      <span class="set-total">套餐金额 <strong>{{ setAmount(Number(quantity), price) }}</strong> 元</span>
      <ElButton v-if="current" @click="submit(true)">拆开计价</ElButton>
      <ElButton @click="emit('close')">取消</ElButton>
      <ElButton type="primary" :disabled="!valid" @click="submit(false)">应用套价</ElButton>
    </div></template>
  </AppWindowDialog>
</template>

<style scoped>
.set-form { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr); gap: 24px; align-items: start; }
.part-selection { display: grid; gap: 10px; min-width: 0; }
.selection-heading, .footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.selection-heading strong, .part-description strong { font-weight: 600; }
.selection-heading span, .part-description small, .chosen, .terms small, .empty { color: var(--el-text-color-secondary); font-size: 12px; }
.materials { border: 1px solid var(--erp-color-border); border-radius: var(--erp-radius-control); max-height: clamp(200px, 39vh, 360px); overflow: auto; }
.materials .el-checkbox { display: flex; margin: 0; height: auto; min-height: 43px; padding: 6px 12px; box-sizing: border-box; white-space: normal; }
.materials .el-checkbox + .el-checkbox { border-top: 1px solid var(--el-border-color-lighter); }
.materials .el-checkbox:not(.is-disabled):hover, .materials .el-checkbox.is-checked { background: var(--el-color-primary-light-9); }
.materials :deep(.el-checkbox__label) { display: flex; align-items: center; justify-content: space-between; flex: 1; gap: 8px; min-width: 0; }
.part-description { display: grid; gap: 2px; min-width: 0; overflow-wrap: anywhere; }
.materials .is-checked .part-description { color: var(--el-text-color-primary); }
.part-quantity { font-size: 12px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.empty { padding: 20px 12px; text-align: center; }
.chosen { max-height: 3.4em; overflow: auto; line-height: 1.6; }
.terms { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 12px; }
.terms .el-form-item { min-width: 0; margin: 0; }
.terms :deep(.el-select), .terms :deep(.el-date-editor) { width: 100%; }
.terms :deep(.el-input__suffix) { white-space: nowrap; }
.full-field { grid-column: 1 / -1; }
.footer { flex-wrap: wrap; width: 100%; justify-content: flex-end; }
.set-total { margin-right: auto; font-size: 13px; }
.set-total strong { margin-inline: 4px; font-size: 16px; font-variant-numeric: tabular-nums; }
.footer .el-button + .el-button { margin-left: 0; }
@media (max-width: 720px) {
  .set-form { grid-template-columns: minmax(0, 1fr); gap: 18px; }
  .materials { max-height: min(210px, 32vh); }
}
</style>
