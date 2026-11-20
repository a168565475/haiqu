<script setup lang="ts">
import { computed, ref } from 'vue'
import type { PurchaseOrderSupplierOption } from '@/types/purchaseOrder'
import { setAmount, type SetPricingChange, type SetPricingLine } from './purchaseSetPricing'

interface Candidate extends SetPricingLine {
  quantityText: string
  eligible: boolean
}

const props = defineProps<{ source: Candidate; lines: Candidate[]; suppliers: PurchaseOrderSupplierOption[] }>()
const emit = defineEmits<{ close: []; apply: [change: SetPricingChange] }>()
const current = props.source.set_pricing
const anchorId = current?.anchor_id ?? props.source.purchase_group_line_id!
const anchor = props.lines.find(line => line.purchase_group_line_id === anchorId)!
const members = ref(current
  ? props.lines.filter(line => line.set_pricing?.anchor_id === anchorId).map(line => line.purchase_group_line_id!)
  : [anchorId])
const suggested = Number(anchor.quantityText)
const quantity = ref(current ? String(current.quantity) : Number.isSafeInteger(suggested) && suggested > 0 ? String(suggested) : '')
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
  <ElDialog :model-value="true" title="按套计价" width="min(500px, 95vw)" append-to-body :close-on-click-modal="false" @close="emit('close')">
    <div class="set-form">
      <ElInput v-model="search" aria-label="搜索本单部件" placeholder="搜索本单材料的品名或规格" clearable />
      <div class="materials">
        <label v-for="line in matching" :key="line.purchase_group_line_id!">
          <input v-model="members" type="checkbox" :value="line.purchase_group_line_id"
            :disabled="line.purchase_group_line_id === anchorId || (!line.eligible && !members.includes(line.purchase_group_line_id!)) || Boolean(line.set_pricing && line.set_pricing.anchor_id !== anchorId)">
          <span>{{ materialName(line) }} <small>{{ line.specification }}</small></span>
          <small>{{ line.set_pricing && line.set_pricing.anchor_id !== anchorId ? '已在其他套餐' : (line.quantityText || '0') + ' ' + line.source_unit_text }}</small>
        </label>
        <span v-if="!matching.length">没有匹配的材料</span>
      </div>
      <div class="chosen">已选 {{ selected.length }} 项　{{ selected.map(materialName).join('、') }}</div>
      <div class="terms">
        <label>采购套数（套）<ElInput v-model="quantity" inputmode="numeric" maxlength="14" aria-label="采购套数" /></label>
        <label>每套单价（元）<ElInput v-model="price" inputmode="decimal" maxlength="19" aria-label="每套单价" /></label>
        <label>供应商<ElSelect v-model="supplierId" filterable clearable aria-label="套餐供应商" placeholder="请选择供应商"><ElOption v-for="supplier in suppliers" :key="supplier.id" :value="supplier.id" :label="supplier.supplier_name" /></ElSelect></label>
        <label>采购交期<ElDatePicker v-model="deliveryDate" type="date" value-format="YYYY-MM-DD" aria-label="套餐采购交期" placeholder="选择采购交期" /></label>
      </div>
      <small v-if="changingTerms">应用后，所选部件将统一使用这里的供应商和交期。</small>
    </div>
    <template #footer><div class="footer">
      <strong>套餐金额　{{ setAmount(Number(quantity), price) }} 元</strong>
      <ElButton v-if="current" @click="submit(true)">拆开计价</ElButton>
      <ElButton @click="emit('close')">取消</ElButton>
      <ElButton type="primary" :disabled="!valid" @click="submit(false)">应用套价</ElButton>
    </div></template>
  </ElDialog>
</template>

<style scoped>
.set-form { display: grid; gap: 10px; }
.materials { max-height: 160px; overflow-y: auto; border: 1px solid var(--el-border-color); border-radius: 4px; padding: 4px 8px; }
.materials label { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.materials label > small { margin-left: auto; white-space: nowrap; }
.chosen, small { color: var(--el-text-color-secondary); }
.terms { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px; }
.terms label { display: grid; gap: 4px; }
.terms :deep(.el-date-editor) { width: 100%; }
.footer { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.footer strong { margin-right: auto; }
.footer .el-button + .el-button { margin-left: 0; }
</style>
