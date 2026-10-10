<script setup lang="ts">
import { computed, ref } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import BomAttributesTooltip from '@/components/common/BomAttributesTooltip.vue'
import { confirmOutsourcingDispatch, confirmOutsourcingFlow, confirmOutsourcingReturn, fetchOutsourcingDispatchContext, fetchOutsourcingOptions, fetchOutsourcingReconciliation } from '@/api/outsourcing'
import type { OutsourcingDispatchContext, OutsourcingOptions, OutsourcingOrderDetail, OutsourcingReconciliation, OutsourcingReconciliationInput, VersionedOutsourcingOrder } from '@/types/outsourcing'
import { decimalUnits, outsourcingPlan } from '@/utils/outsourcingQuantities'
import { pipeMeters } from '@/utils/pipeQuantities'
import type { OutsourcingConversion } from '@/types/outsourcing'

const props = defineProps<{ detail: OutsourcingOrderDetail; etag: string }>()
const emit = defineEmits<{ updated: [value: VersionedOutsourcingOrder] }>()
const publicStock = computed(() => props.detail.stock_mode === 'PUBLIC_V2')
type Mode = 'dispatch' | 'return' | 'raw' | 'record' | 'complete'
const visible = ref(false)
const mode = ref<Mode>('complete')
const busy = ref(false)
const loading = ref(false)
const error = ref('')
const requestId = ref('')
const context = ref<OutsourcingDispatchContext | null>(null)
const state = ref<OutsourcingReconciliation | null>(null)
const options = ref<OutsourcingOptions | null>(null)
const factoryId = ref('')
const reason = ref('')
const kind = ref<OutsourcingReconciliationInput['kind']>('RAW_INPUT')
const quantities = ref<Record<string, string>>({})
const good = ref<Record<string, string>>({})
const defective = ref<Record<string, string>>({})
const defectReasons = ref<Record<string, string>>({})
const rawInputs = ref<Record<string, string>>({})
type DispatchMaterial = OutsourcingDispatchContext['materials'][number]
type DispatchRow = { row_key: string; material: DispatchMaterial; zone_id: string; quantity: string }
const dispatchRows = ref<DispatchRow[]>([])
const dispatchMaterials = computed(() => [...new Map(dispatchRows.value.map(row => [row.material.material_item_id, row.material] as const)).values()])
const receipt = ref({ date: '', receiver: '', goodZone: '', badZone: '', delivery: '' })
const titles: Record<Mode, string> = { dispatch: '仓库确认实际发料', return: '分批回货入库', raw: '原料退回', record: '投入与损耗登记', complete: '结清检查' }
const title = computed(() => titles[mode.value])
const factories = computed(() => Array.from(new Map((state.value?.outputs || []).map(row => [row.factory_id, { id: row.factory_id, name: row.factory_name }])).values()))
const rawRows = computed(() => (state.value?.raw_materials || []).filter(row => !factoryId.value || row.factory_id === factoryId.value))
const outputRows = computed(() => (state.value?.outputs || []).filter(row => !factoryId.value || row.factory_id === factoryId.value))
const positive = (value: string | undefined) => (decimalUnits(value) ?? 0n) > 0n
const integer = (value: string | undefined) => { const amount = decimalUnits(value || '0'); return amount !== null && amount % 10000n === 0n }
const quantityText = (value: string) => Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
const issuedTotal = (row: DispatchMaterial) => quantityText(String(Number(row.internal_issued_quantity) + Number(row.outsourcing_issued_quantity)))
const selectedZone = (row: DispatchRow) => row.material.zones.find(zone => zone.zone_id === row.zone_id)
const zoneRowCount = (materialId: string) => dispatchRows.value.filter(row => row.material.material_item_id === materialId).length
const pipeQuantityError = (row: DispatchRow) => row.material.conversion_snapshot.kind === 'PIPE' && row.quantity.trim()
  ? outsourcingPlan(row.quantity, row.material.conversion_snapshot).error : ''
const pipeQuantityRule = (row: DispatchRow) => {
  const pieces = Number(row.material.conversion_snapshot.pieces_per_bar || 0)
  return pieces > 0 ? `每根可切 ${pieces} 支；本次发料须填写 ${pieces} 的正整数倍。` : '管材切割规则缺失，请先核对 BOM。'
}
const tooltipKeys = ['part_name', 'material', 'specification', 'hardware_color', 'plastic_color', 'fabric_color_name', 'accessory_color', 'packaging_color']
type BomAttributeRow = { bom_attributes?: Array<{ key: string; value: string }>; specification?: string }
const materialValue = (row: BomAttributeRow) => {
  const field = (row.bom_attributes || []).find(item => item.key === 'material' && item.value)
  return field?.value || '—'
}
const specificationValue = (row: BomAttributeRow) => {
  const field = (row.bom_attributes || []).find(item => item.key === 'specification' && item.value)
  return field?.value || row.specification || '—'
}
const colorValue = (row: BomAttributeRow & { color?: string }, preferActual = false) => {
  if (preferActual && String(row.color || '').trim()) return row.color
  const field = (row.bom_attributes || []).find(item => ['hardware_color', 'plastic_color', 'fabric_color_name', 'accessory_color', 'packaging_color'].includes(item.key) && item.value)
  return field?.value || (preferActual ? row.color : '') || '—'
}

function addZone(materialItemId: string) {
  const index = dispatchRows.value.findIndex(item => item.material.material_item_id === materialItemId)
  if (index < 0) return
  const row = dispatchRows.value[index]!
  dispatchRows.value.splice(index + 1, 0, { row_key: crypto.randomUUID(), material: row.material, zone_id: '', quantity: '' })
}

function removeZone(row: DispatchRow) {
  if (zoneRowCount(row.material.material_item_id) <= 1) return
  dispatchRows.value = dispatchRows.value.filter(item => item.row_key !== row.row_key)
}

function actionAllowed(next: Mode): boolean {
  if (props.detail.direct_handoff || props.detail.status === 'CANCELLED') return false
  return Boolean({
    dispatch: props.detail.can_confirm_dispatch, return: props.detail.can_confirm_return,
    raw: props.detail.can_return_raw, record: props.detail.can_reconcile,
    complete: props.detail.dispatch,
  }[next])
}

function rootNote(value: string | undefined, basis: OutsourcingConversion) {
  const amount = decimalUnits(value)
  if (amount === null || amount <= 0n || amount % 10000n) return '请填写正整数根数'
  const roots = amount / 10000n
  return `${mode.value === 'raw' ? '恢复' : '对应'} ${pipeMeters(String(roots), basis.raw_bar_length_m)} 米 / ${roots * BigInt(basis.pieces_per_bar || 0)} 支${mode.value === 'raw' ? '额度' : ''}`
}

function message(value: unknown) {
  if (value instanceof Error && !(value instanceof AxiosError)) return value.message
  if (value instanceof AxiosError) return value.response?.data?.error?.message || value.response?.data?.detail || '操作失败，请核对数量与最新单据状态。'
  return '请求失败，请重试。'
}

async function load() {
  if (!actionAllowed(mode.value)) {
    error.value = props.detail.direct_handoff_lock_reason || '当前单据不可执行此操作，请关闭后刷新核对。'
    return
  }
  loading.value = true
  error.value = ''
  try {
    if (mode.value === 'dispatch') {
      context.value = await fetchOutsourcingDispatchContext(props.detail.id)
      dispatchRows.value = [...context.value.materials]
        .sort((left, right) => left.factory_name.localeCompare(right.factory_name, 'zh-CN'))
        .map(material => ({
          row_key: crypto.randomUUID(), material,
          zone_id: material.zones.length === 1 ? material.zones[0]!.zone_id : '', quantity: '',
        }))
    } else {
      state.value = await fetchOutsourcingReconciliation(props.detail.id)
      factoryId.value = factories.value[0]?.id || ''
      if (mode.value === 'return') {
        options.value = await fetchOutsourcingOptions()
        receipt.value = { date: new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10),
          receiver: options.value.receivers?.[0]?.id || '', goodZone: options.value.semi_finished_zones?.[0]?.id || '',
          badZone: publicStock.value ? '' : options.value.defective_zones?.[0]?.id || '', delivery: '' }
      }
    }
  } catch (value) { error.value = message(value) } finally { loading.value = false }
}

async function open(next: Mode) {
  if (busy.value || loading.value) return
  if (!actionAllowed(next)) {
    error.value = props.detail.direct_handoff_lock_reason || '当前单据不可执行此操作，请刷新核对。'
    return
  }
  mode.value = next
  visible.value = true
  requestId.value = crypto.randomUUID()
  quantities.value = {}; rawInputs.value = {}; good.value = {}; defective.value = {}; defectReasons.value = {}
  reason.value = ''; kind.value = 'RAW_INPUT'; context.value = null; state.value = null
  await load()
}

function entries(inputOnly = false): OutsourcingReconciliationInput[] {
  if (!inputOnly && !reason.value.trim()) throw new Error('请填写登记原因。')
  if (!inputOnly && kind.value === 'OUTPUT_SCRAP') return outputRows.value.filter(row => positive(quantities.value[row.allocation_id])).map(row => ({
    allocation_id: row.allocation_id, dispatch_line_id: null, kind: 'OUTPUT_SCRAP', quantity: quantities.value[row.allocation_id]!, reason: reason.value.trim(),
  }))
  const values = inputOnly ? rawInputs.value : quantities.value
  return rawRows.value.filter(row => positive(values[row.dispatch_line_id])).map(row => ({
    allocation_id: row.allocation_id, dispatch_line_id: row.dispatch_line_id, kind: inputOnly ? 'RAW_INPUT' : kind.value,
    quantity: values[row.dispatch_line_id]!, reason: inputOnly ? (reason.value.trim() || '随本次回货确认实际投入') : reason.value.trim(),
  }))
}

async function submit() {
  if (busy.value || loading.value || !props.etag) return
  if (!actionAllowed(mode.value) || (mode.value === 'complete' && !props.detail.can_complete)) {
    error.value = props.detail.direct_handoff_lock_reason || '当前单据不可执行此操作，请关闭后刷新核对。'
    return
  }
  busy.value = true; error.value = ''
  try {
    // 非空错误输入必须逐项提示，不能在筛选正数时被悄悄忽略。
    const activeValues = mode.value === 'return'
      ? [...outputRows.value.flatMap(row => publicStock.value ? [good.value[row.allocation_id]] : [good.value[row.allocation_id], defective.value[row.allocation_id]]), ...rawRows.value.map(row => rawInputs.value[row.dispatch_line_id])]
      : mode.value === 'dispatch'
        ? dispatchRows.value.map(row => row.quantity)
      : mode.value === 'record' && kind.value === 'OUTPUT_SCRAP'
        ? outputRows.value.map(row => quantities.value[row.allocation_id])
        : rawRows.value.map(row => quantities.value[row.dispatch_line_id])
    if (activeValues.some(value => value?.trim() && decimalUnits(value) === null)) throw new Error('数量不能为负数、非数字或超过四位小数，请逐项检查。')
    let result: VersionedOutsourcingOrder
    if (mode.value === 'dispatch') {
      const lines: Array<{ material_item_id: string; zone_id: string; requested_quantity: string }> = []
      const stockByZone = new Map<string, { requested: bigint; available: bigint }>()
      for (const material of context.value?.materials || []) {
        const selected = dispatchRows.value.filter(row => row.material.material_item_id === material.material_item_id && row.quantity.trim())
        if (!selected.length) {
          if ((decimalUnits(material.max_issue_quantity) || 0n) > 0n) throw new Error(`${material.material_name}：本次可领 ${material.max_issue_quantity} ${material.unit}，请填写发料数量。`)
          continue
        }
        if (material.quota_error) throw new Error(`${material.material_name}：${material.quota_error}`)
        const usedZones = new Set<string>()
        let total = 0n
        for (const row of selected) {
          const zone = selectedZone(row)
          if (!zone) throw new Error(`${material.material_name}：请选择发料库区。`)
          if (usedZones.has(zone.zone_id)) throw new Error(`${material.material_name}：同一库区只能填写一行。`)
          usedZones.add(zone.zone_id)
          const plan = outsourcingPlan(row.quantity, material.conversion_snapshot)
          if (plan.error) throw new Error(`${material.material_name}：${plan.error}`)
          const requested = decimalUnits(row.quantity)!
          const stockQuantity = decimalUnits(plan.raw)!
          if (requested > (decimalUnits(zone.available_input_quantity) || 0n)) throw new Error(`${material.material_name}：所选库区可用库存不足。`)
          total += requested
          const stockKey = `${material.conversion_snapshot.raw_material_id}|${zone.zone_id}|${material.conversion_snapshot.kind === 'PIPE' ? material.conversion_snapshot.raw_bar_length_m : ''}`
          const stock = stockByZone.get(stockKey) || { requested: 0n, available: decimalUnits(zone.available_quantity) || 0n }
          stock.requested += stockQuantity
          stockByZone.set(stockKey, stock)
          lines.push({ material_item_id: material.material_item_id, zone_id: zone.zone_id, requested_quantity: row.quantity })
        }
        if (total > (decimalUnits(material.planned_issue_quantity) || 0n)) throw new Error(`${material.material_name} 的发料合计不能超过计划 ${material.planned_issue_quantity} ${material.unit}。`)
        if (total > (decimalUnits(material.max_issue_quantity) || 0n)) throw new Error(`${material.material_name} 当前最多还可领 ${material.max_issue_quantity} ${material.unit}。`)
      }
      if ([...stockByZone.values()].some(stock => stock.requested > stock.available)) throw new Error('同一库区的原料合计超过可用库存，请调整发料库区。')
      if (!lines.length) throw new Error('没有可发料的明细。')
      result = await confirmOutsourcingDispatch(props.detail.id, { request_id: requestId.value, remark: reason.value, lines }, props.etag)
    } else if (mode.value === 'return') {
      const lines = outputRows.value.filter(row => positive(good.value[row.allocation_id]) || (!publicStock.value && positive(defective.value[row.allocation_id]))).map(row => {
        if (!integer(good.value[row.allocation_id]) || (!publicStock.value && !integer(defective.value[row.allocation_id]))) throw new Error('回货支数和套数须为整数。')
        return { allocation_id: row.allocation_id, good_quantity: good.value[row.allocation_id] || '0',
          defective_quantity: publicStock.value ? '0' : defective.value[row.allocation_id] || '0',
          defect_reason: publicStock.value ? '' : defectReasons.value[row.allocation_id] || '' }
      })
      if (!lines.length || !factoryId.value || !receipt.value.receiver) throw new Error('请填写本厂回货数量和接收人。')
      result = await confirmOutsourcingReturn(props.detail.id, { request_id: requestId.value, factory_id: factoryId.value,
        good_zone_id: receipt.value.goodZone || null, defective_zone_id: publicStock.value ? null : receipt.value.badZone || null,
        received_by_employee_id: receipt.value.receiver, return_date: receipt.value.date, delivery_note_number: receipt.value.delivery,
        lines, raw_inputs: entries(true), remark: reason.value }, props.etag)
    } else if (mode.value === 'raw') {
      const lines = rawRows.value.filter(row => positive(quantities.value[row.dispatch_line_id])).map(row => ({ dispatch_line_id: row.dispatch_line_id, quantity: quantities.value[row.dispatch_line_id]! }))
      if (!lines.length || !reason.value.trim()) throw new Error('请填写退料数量和原因。')
      result = await confirmOutsourcingFlow(props.detail.id, 'confirm-raw-return', { request_id: requestId.value, factory_id: factoryId.value, lines, reason: reason.value.trim() }, props.etag)
    } else if (mode.value === 'record') {
      const rows = entries()
      if (!rows.length) throw new Error('请填写本次投入或损耗数量。')
      result = await confirmOutsourcingFlow(props.detail.id, 'confirm-reconciliation', { request_id: requestId.value, entries: rows }, props.etag)
    } else {
      if (!state.value?.can_complete) throw new Error('仍有未处理差额，不能结清。')
      result = await confirmOutsourcingFlow(props.detail.id, 'complete', { request_id: requestId.value }, props.etag)
    }
    emit('updated', result); visible.value = false; ElMessage.success(`${title.value}已确认。`)
  } catch (value) { error.value = message(value) } finally { busy.value = false }
}
</script>

<template>
  <div v-if="!detail.direct_handoff && detail.status !== 'CANCELLED'" class="flow-actions">
    <ElButton v-if="detail.can_confirm_dispatch" type="primary" @click="open('dispatch')">确认外发</ElButton>
    <ElButton v-if="detail.can_confirm_return" type="primary" @click="open('return')">登记回货</ElButton>
    <ElButton v-if="detail.can_return_raw" @click="open('raw')">原料退回</ElButton>
    <ElButton v-if="detail.can_reconcile" @click="open('record')">投入与损耗</ElButton>
    <ElButton v-if="detail.dispatch" @click="open('complete')">结清检查</ElButton>
  </div>
  <AppWindowDialog v-model="visible" :title="title" :width="mode === 'dispatch' ? 1700 : 1320" :height="820" :close-on-click-modal="false" :close-on-press-escape="!busy" :before-close="done => { if (!busy) done() }" destroy-on-close>
    <div v-loading="loading" class="flow-body" :class="{ 'flow-body--dispatch': mode === 'dispatch' }">
      <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon><ElButton v-if="!context && !state" @click="load">重试</ElButton></ElAlert>
      <template v-if="mode === 'dispatch' && context">
        <ElAlert v-for="material in context.materials.filter(item => item.quota_error || !item.zones.length)" :key="material.material_item_id" :title="`${material.material_name}：${material.quota_error || '当前没有匹配的可用库区，请先完成入库。'}`" type="warning" :closable="false" />
        <div class="dispatch-toolbar">
          <ElDropdown trigger="click" placement="bottom-end" :disabled="!dispatchMaterials.length" @command="addZone">
            <ElButton>加库区</ElButton>
            <template #dropdown>
              <ElDropdownMenu style="max-height: 360px; overflow-y: auto;">
                <ElDropdownItem v-for="material in dispatchMaterials" :key="material.material_item_id" :command="material.material_item_id">
                  {{ material.factory_name }} · {{ material.material_name }} · {{ material.specification }}
                </ElDropdownItem>
              </ElDropdownMenu>
            </template>
          </ElDropdown>
        </div>
        <ElTable :data="dispatchRows" row-key="row_key" border max-height="540" scrollbar-always-on empty-text="当前没有可发料明细" class="dispatch-table">
          <ElTableColumn label="加工厂" width="200" show-overflow-tooltip><template #default="{ row }">{{ row.material.factory_name }}</template></ElTableColumn>
          <ElTableColumn label="原料" width="130" show-overflow-tooltip><template #default="{ row }"><BomAttributesTooltip :fields="row.material.bom_attributes" :hide-keys="tooltipKeys">{{ row.material.material_name }}</BomAttributesTooltip></template></ElTableColumn>
          <ElTableColumn label="材质" width="110" show-overflow-tooltip><template #default="{ row }">{{ materialValue(row.material) }}</template></ElTableColumn>
          <ElTableColumn label="规格" width="140" show-overflow-tooltip><template #default="{ row }">{{ specificationValue(row.material) }}</template></ElTableColumn>
          <ElTableColumn label="颜色" width="100" show-overflow-tooltip><template #default="{ row }">{{ colorValue(row.material) }}</template></ElTableColumn>
          <ElTableColumn label="单位" width="60"><template #default="{ row }">{{ row.material.unit }}</template></ElTableColumn>
          <ElTableColumn label="计划外发" width="100"><template #default="{ row }">{{ quantityText(row.material.planned_issue_quantity) }}</template></ElTableColumn>
          <ElTableColumn label="已领" width="85"><template #default="{ row }"><span :title="`厂内 ${quantityText(row.material.internal_issued_quantity)} / 委外 ${quantityText(row.material.outsourcing_issued_quantity)}`">{{ issuedTotal(row.material) }}</span></template></ElTableColumn>
          <ElTableColumn label="本次可领" width="100"><template #default="{ row }"><span :class="{ 'flow-error': Number(row.material.max_issue_quantity) < Number(row.material.planned_issue_quantity) }" :title="`订单剩余 ${quantityText(row.material.order_remaining)}，可用库存 ${quantityText(row.material.available_stock)}`">{{ quantityText(row.material.max_issue_quantity) }}</span></template></ElTableColumn>
          <ElTableColumn label="发料库区" width="170"><template #default="{ row }"><ElSelect v-model="row.zone_id" :aria-label="`${row.material.material_name}发料库区`" placeholder="选择库区" filterable><ElOption v-for="zone in row.material.zones" :key="zone.zone_id" :value="zone.zone_id" :label="`${zone.zone_name} / ${zone.warehouse_name}`" /></ElSelect></template></ElTableColumn>
          <ElTableColumn label="库区可用" width="225"><template #default="{ row }"><template v-if="selectedZone(row)">{{ quantityText(selectedZone(row)!.available_input_quantity) }}<template v-if="row.material.conversion_snapshot.kind === 'PIPE'"> / {{ quantityText(selectedZone(row)!.available_quantity) }} {{ row.material.procurement_unit }} / {{ selectedZone(row)!.available_meters === null ? '—' : quantityText(selectedZone(row)!.available_meters!) }} 米</template></template><span v-else>—</span></template></ElTableColumn>
          <ElTableColumn label="本次发料" width="115"><template #default="{ row }"><ElTooltip :disabled="!pipeQuantityError(row)" :content="pipeQuantityRule(row)" placement="top" effect="light" popper-class="dispatch-pipe-rule-tooltip"><ElInput v-model="row.quantity" class="dispatch-quantity-input" :class="{ 'is-rule-error': Boolean(pipeQuantityError(row)) }" :aria-invalid="Boolean(pipeQuantityError(row))" :aria-label="`${row.material.material_name}本次发料数量`" :inputmode="row.material.conversion_snapshot.kind === 'PIPE' ? 'numeric' : 'decimal'" /></ElTooltip></template></ElTableColumn>
          <ElTableColumn label="预计扣库" width="180"><template #default="{ row }"><span v-if="row.quantity && outsourcingPlan(row.quantity, row.material.conversion_snapshot).error" class="flow-error" :title="outsourcingPlan(row.quantity, row.material.conversion_snapshot).error">{{ outsourcingPlan(row.quantity, row.material.conversion_snapshot).error }}</span><span v-else-if="row.quantity">{{ row.material.conversion_snapshot.kind === 'PIPE' ? `${outsourcingPlan(row.quantity, row.material.conversion_snapshot).raw} ${row.material.procurement_unit} / ${outsourcingPlan(row.quantity, row.material.conversion_snapshot).meters} 米` : outsourcingPlan(row.quantity, row.material.conversion_snapshot).raw }}</span><span v-else>—</span></template></ElTableColumn>
          <ElTableColumn v-if="dispatchRows.length > context.materials.length" label="操作" width="80" fixed="right"><template #default="{ row }"><ElButton v-if="zoneRowCount(row.material.material_item_id) > 1" link type="danger" @click="removeZone(row)">移除</ElButton></template></ElTableColumn>
        </ElTable>
      </template>
      <template v-else-if="state">
        <div v-if="mode !== 'complete'" class="flow-toolbar">
          <label>加工厂<ElSelect v-model="factoryId" aria-label="加工厂"><ElOption v-for="factory in factories" :key="factory.id" :value="factory.id" :label="factory.name" /></ElSelect></label>
          <label v-if="mode === 'record'">登记类型<ElSelect v-model="kind" aria-label="登记类型" @change="quantities = {}"><ElOption label="投入加工" value="RAW_INPUT" /><ElOption label="原料损失" value="RAW_LOSS" /><ElOption label="加工报废" value="OUTPUT_SCRAP" /></ElSelect></label>
        </div>
        <template v-if="mode === 'return'">
          <ElAlert :title="publicStock ? '只填写本次新增投入，已经登记的投入不重复填写。合格回货按产物单位进入公共半成品库存，不再次扣原材料。' : '只填写本次新增投入，已经登记的投入不重复填写。合格与不良按支/套入库，不再次扣原材料。'" :closable="false" type="info" />
          <div class="flow-toolbar receipt-fields">
            <label>回货日期<ElDatePicker v-model="receipt.date" type="date" value-format="YYYY-MM-DD" /></label>
            <label>接收人<ElSelect v-model="receipt.receiver"><ElOption v-for="person in options?.receivers || []" :key="person.id" :value="person.id" :label="person.name" /></ElSelect></label>
            <label>合格品库区<ElSelect v-model="receipt.goodZone" clearable><ElOption v-for="zone in options?.semi_finished_zones || []" :key="zone.id" :value="zone.id" :label="zone.name" /></ElSelect></label>
            <label v-if="!publicStock">不良品库区<ElSelect v-model="receipt.badZone" clearable><ElOption v-for="zone in options?.defective_zones || []" :key="zone.id" :value="zone.id" :label="zone.name" /></ElSelect></label>
            <label>送货单号<ElInput v-model="receipt.delivery" /></label>
          </div>
          <h3>本次回货</h3>
          <ElTable :data="outputRows" border empty-text="本厂没有加工明细">
            <ElTableColumn label="部位" min-width="180"><template #default="{ row }"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys">{{ row.component }}</BomAttributesTooltip></template></ElTableColumn>
            <ElTableColumn label="材质" min-width="110"><template #default="{ row }">{{ materialValue(row) }}</template></ElTableColumn>
            <ElTableColumn label="规格" min-width="140"><template #default="{ row }">{{ specificationValue(row) }}</template></ElTableColumn>
            <ElTableColumn label="颜色" min-width="110"><template #default="{ row }">{{ colorValue(row, true) }}</template></ElTableColumn>
            <ElTableColumn prop="unit" label="单位" width="70" />
            <ElTableColumn prop="remaining" label="已投入待回/报废" width="150" />
            <ElTableColumn label="合格数量" width="150"><template #default="{ row }"><ElInput v-model="good[row.allocation_id]" aria-label="合格数量" /></template></ElTableColumn>
            <ElTableColumn v-if="!publicStock" label="不良数量" width="150"><template #default="{ row }"><ElInput v-model="defective[row.allocation_id]" aria-label="不良数量" /></template></ElTableColumn>
            <ElTableColumn v-if="!publicStock" label="不良原因" min-width="210"><template #default="{ row }"><ElInput v-model="defectReasons[row.allocation_id]" /></template></ElTableColumn>
          </ElTable>
        </template>
        <h3>{{ mode === 'return' ? '本次新增实际投入（可选）' : '原材料去向' }}</h3>
        <ElTable :data="mode === 'complete' ? state.raw_materials : rawRows" border empty-text="暂无已发原料记录">
          <ElTableColumn :label="detail.stock_mode === 'PUBLIC_V2' ? '加工厂 / 部位 / 库区' : '加工厂 / 部位 / 批次'" min-width="245"><template #default="{ row }">{{ row.factory_name }} / <BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys">{{ row.component }}</BomAttributesTooltip><small class="flow-sub">{{ detail.stock_mode === 'PUBLIC_V2' ? row.zone_name : `${row.inbound_number} · ${row.zone_name}` }}</small></template></ElTableColumn>
          <ElTableColumn label="材质" width="110"><template #default="{ row }">{{ materialValue(row) }}</template></ElTableColumn>
          <ElTableColumn label="规格" width="140"><template #default="{ row }">{{ specificationValue(row) }}</template></ElTableColumn>
          <ElTableColumn label="颜色" width="105"><template #default="{ row }">{{ colorValue(row) }}</template></ElTableColumn>
          <ElTableColumn prop="unit" label="单位" width="64" /><ElTableColumn prop="dispatched" label="已发" width="100" /><ElTableColumn prop="returned" label="已退" width="90" /><ElTableColumn prop="input" label="已投入" width="100" /><ElTableColumn prop="loss" label="损失" width="90" /><ElTableColumn prop="remaining" label="未处理" width="110" />
          <ElTableColumn v-if="mode === 'return' || mode === 'raw' || (mode === 'record' && kind !== 'OUTPUT_SCRAP')" :label="mode === 'raw' ? '本次退回' : mode === 'record' && kind === 'RAW_LOSS' ? '本次原料损失' : '本次投入'" width="160"><template #default="{ row }"><ElInput v-if="mode === 'return'" v-model="rawInputs[row.dispatch_line_id]" aria-label="本次新增投入" /><ElInput v-else v-model="quantities[row.dispatch_line_id]" aria-label="本次原料数量" /><small v-if="row.conversion_snapshot.kind === 'PIPE'" class="flow-sub">整根 · {{ row.conversion_snapshot.raw_bar_length_m }} 米/根<br>{{ rootNote(mode === 'return' ? rawInputs[row.dispatch_line_id] : quantities[row.dispatch_line_id], row.conversion_snapshot) }}</small></template></ElTableColumn>
        </ElTable>
        <template v-if="mode === 'complete' || (mode === 'record' && kind === 'OUTPUT_SCRAP')">
          <h3>加工产出去向</h3>
          <ElTable :data="mode === 'complete' ? state.outputs : outputRows" border>
            <ElTableColumn prop="factory_name" label="加工厂" min-width="150" /><ElTableColumn label="部位" min-width="170"><template #default="{ row }"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys">{{ row.component }}</BomAttributesTooltip></template></ElTableColumn><ElTableColumn label="材质" width="110"><template #default="{ row }">{{ materialValue(row) }}</template></ElTableColumn><ElTableColumn label="规格" width="140"><template #default="{ row }">{{ specificationValue(row) }}</template></ElTableColumn><ElTableColumn label="颜色" width="110"><template #default="{ row }">{{ colorValue(row, true) }}</template></ElTableColumn><ElTableColumn prop="unit" label="单位" width="64" /><ElTableColumn prop="capacity" label="实际投入可产出" width="140" /><ElTableColumn prop="good" label="合格回库" width="105" /><ElTableColumn prop="defective" label="不良回库" width="105" /><ElTableColumn prop="scrap" label="加工报废" width="105" /><ElTableColumn prop="remaining" label="未处理" width="105" />
            <ElTableColumn v-if="mode === 'record'" label="本次加工报废" width="155"><template #default="{ row }"><ElInput v-model="quantities[row.allocation_id]" aria-label="本次加工报废" /></template></ElTableColumn>
          </ElTable>
          <ElAlert v-if="mode === 'record'" title="仅登记未回库加工报废，已入库不良不能再次报废回货。" type="warning" :closable="false" />
        </template>
        <template v-if="mode === 'complete'">
          <ElAlert v-for="text in state.blockers" :key="text" :title="text" type="warning" :closable="false" />
          <ElAlert v-if="!state.blockers.length" :title="detail.status === 'COMPLETED' ? '本单已结清' : '原料与产出均已对清，可确认结清。'" type="success" :closable="false" />
          <h3>投入与损耗记录</h3><ElTable :data="state.records" border empty-text="暂无登记"><ElTableColumn label="类型" width="120"><template #default="{ row }">{{ ({ RAW_INPUT: '投入加工', RAW_LOSS: '原料损失', OUTPUT_SCRAP: '加工报废' } as Record<string, string>)[row.kind] }}</template></ElTableColumn><ElTableColumn prop="quantity" label="数量" width="120" /><ElTableColumn prop="unit" label="单位" width="70" /><ElTableColumn prop="reason" label="原因" /><ElTableColumn prop="actor" label="确认人" width="120" /><ElTableColumn prop="confirmed_at" label="确认时间" width="240" /></ElTable>
          <h3>原料退回记录</h3><ElTable :data="state.raw_returns" border empty-text="暂无退料"><ElTableColumn prop="factory_name" label="加工厂" width="150" /><ElTableColumn prop="component" label="部位" width="130" /><ElTableColumn prop="quantity" label="原单位数量" width="130" /><ElTableColumn prop="unit" label="单位" width="70" /><ElTableColumn prop="meters" label="管材/面料米数" width="140" /><ElTableColumn prop="reason" label="原因" /><ElTableColumn prop="actor" label="确认人" width="120" /><ElTableColumn prop="confirmed_at" label="确认时间" width="240" /></ElTable>
        </template>
      </template>
      <ElForm v-if="mode !== 'complete'" label-width="100px"><ElFormItem :label="mode === 'raw' || mode === 'record' ? '原因（必填）' : '备注'"><ElInput v-model="reason" maxlength="1000" /></ElFormItem></ElForm>
    </div>
    <template #footer><ElButton :disabled="busy" @click="visible = false">关闭</ElButton><ElButton v-if="mode !== 'complete' || detail.can_complete" type="primary" :loading="busy" :disabled="loading || (!context && !state) || (mode === 'complete' && !state?.can_complete)" @click="submit">{{ mode === 'dispatch' ? '确认扣库并发料' : mode === 'return' ? '确认回货入库' : mode === 'raw' ? '确认退料入库' : mode === 'record' ? '确认登记' : '确认结清' }}</ElButton></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.flow-actions { display:flex; gap:8px; flex-wrap:wrap; }
.flow-actions :deep(.el-button + .el-button) { margin-left:0; }
.flow-body { display:flex; flex-direction:column; gap:14px; height:100%; overflow:auto; padding:16px; background:#f6f3ec; }
.flow-body--dispatch { overflow:hidden; }
.flow-body h3 { margin:4px 0 0; font-size:15px; }
.flow-card { padding:12px; background:#fcfbf7; border:1px solid #ddd6c9; border-radius:5px; }
.flow-card header { display:flex; align-items:center; gap:18px; margin-bottom:10px; }
.flow-card header .el-button { margin-left:auto; }
.flow-toolbar { display:flex; flex-wrap:wrap; gap:12px 20px; }
.flow-toolbar label { display:flex; align-items:center; gap:10px; }
.flow-toolbar .el-select, .flow-toolbar .el-input { width:200px; }
.flow-sub { display:block; color:#6f6a61; font-size:12px; }
.flow-error { color:#a94624; }
.flow-body :deep(.el-table) { flex-shrink:0; }
.flow-body--dispatch :deep(.dispatch-table) { flex:1 1 auto; min-height:0; }
.dispatch-toolbar { display:flex; justify-content:flex-end; }
.dispatch-table :deep(.cell) { white-space:nowrap; }
.dispatch-quantity-input.is-rule-error :deep(.el-input__wrapper) { box-shadow:0 0 0 1px #e5484d inset; }
.dispatch-quantity-input.is-rule-error :deep(.el-input__inner) { color:#c93439; }
:global(.dispatch-pipe-rule-tooltip.el-popper.is-light) { max-width:280px; padding:7px 10px; border-color:#efb2b4; background:#fff2f2; color:#c93439; font-size:12px; line-height:18px; }
:global(.dispatch-pipe-rule-tooltip.el-popper.is-light .el-popper__arrow::before) { border-color:#efb2b4; background:#fff2f2; }
</style>
