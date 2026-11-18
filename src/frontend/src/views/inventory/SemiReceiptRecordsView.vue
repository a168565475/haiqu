<script setup lang="ts">
import ProcessingMaterialDetails from '@/components/inventory/ProcessingMaterialDetails.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { vHorizontalOverflow } from '@/directives/horizontalOverflow'
import { confirmInternalReceiptRecord, deleteInternalReceiptRecord, fetchSemiReceiptRecord, fetchSemiReceiptRecords } from '@/api/internalReceipts'
import { useAuthStore } from '@/stores/auth'
import { materialAttributeFields } from '@/utils/materialAttributes'
import type { SemiReceiptLine, SemiReceiptRecord, ReceiptAttributes } from '@/types/internalReceipt'
import '@/styles/internalReceipt.scss'
const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const canConfirm = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.confirm_internalsemifinishedreceipt'))
const outgoing = computed(() => route.name === 'semi-outbound-records' || route.query.direction === 'OUT')
const direction = computed(() => outgoing.value ? 'OUT' as const : 'IN' as const)
const actionLabel = computed(() => outgoing.value ? '出库' : '入库')
const pageSize = 20
const rows = ref<SemiReceiptRecord[]>([]), total = ref(0), page = ref(1), source = ref(''), search = ref('')
const loading = ref(false), error = ref(''), detailLoading = ref(false), detailError = ref(''), visible = ref(false)
const detail = ref<SemiReceiptRecord | null>(null), dates = ref<string[] | null>([])
const confirming = ref<string | null>(null)
const deleting = ref<string | null>(null)
const number = (value:string) => Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
const specification = (value:ReceiptAttributes) => value.specification || (value.tube_diameter ? `${value.tube_diameter} × ${value.cutting_length_mm}mm` : '—')
const rowQuantity = (row: SemiReceiptRecord) => row.quantity_totals && row.quantity_totals.length > 1
  ? row.quantity_totals.map(item => `${number(item.quantity)} ${item.unit}`).join('、') : number(row.quantity)
const mixedQuantityColumn = computed(() => !outgoing.value && rows.value.some(row => (row.quantity_totals?.length || 0) > 1))
const detailLines = computed<SemiReceiptLine[]>(() => detail.value?.lines?.length ? detail.value.lines : detail.value ? [detail.value] : [])
const multipleDetailLines = computed(() => detailLines.value.length > 1)
const receiptAttributeLabels: Record<string, string> = {
  category: '品类', material: '材质', shape: '截面形状', section_size: '截面尺寸',
  thickness: '厚度', length: '长度', hardness: '硬度', specification: '规格',
  color: '颜色', color_card: '色卡', color_code: '色号', model: '型号/图号', size: '尺寸', process: '工艺版本',
}
function receiptLineAttributes(line: SemiReceiptLine) {
  const attributes = line.attributes
  const snapshot = line.output_material_selection_snapshot?.schema_version === 1
    ? line.output_material_selection_snapshot : attributes.material_selection_snapshot
  const fields = new Map<string, { label: string; value: string }>()
  function add(key: string, value: string | number | null | undefined, label = receiptAttributeLabels[key] || key) {
    const text = String(value ?? '').trim()
    if (text && !fields.has(key)) fields.set(key, { label, value: text })
  }
  const length = String(attributes.cutting_length_mm ?? '').trim()
  const physicalFields = {
    category: attributes.category, material: attributes.material, shape: attributes.tube_shape,
    section_size: attributes.tube_diameter, thickness: attributes.tube_thickness || attributes.thickness,
    length: length && `${length} mm`, hardness: attributes.hardness, specification: attributes.specification,
    color: attributes.color || snapshot?.color_name, color_card: snapshot?.color_card, color_code: snapshot?.color_code,
  }
  for (const [key, value] of Object.entries(physicalFields)) add(key, value, key === 'length' ? '下料长度' : undefined)
  if (snapshot?.schema_version === 1) {
    for (const { key, label, value } of materialAttributeFields({ material_selection_snapshot: snapshot })) {
      if (key !== 'part_name' && key !== 'unit') add(key, value, receiptAttributeLabels[key] || label)
    }
  }
  for (const [key, value] of Object.entries({ ...line.component_material_selection_snapshot?.attributes, ...attributes.component_attributes })) {
    add(`component:${key}`, value, `部位${receiptAttributeLabels[key] || key}`)
  }
  return fields
}
const detailTableRows = computed(() => detailLines.value.map(line => ({
  line, fields: outgoing.value ? null : receiptLineAttributes(line),
})))
const detailAttributeColumns = computed(() => {
  const columns = new Map<string, string>()
  for (const { fields } of detailTableRows.value) {
    fields?.forEach(({ label }, key) => { if (!columns.has(key)) columns.set(key, label) })
  }
  return Array.from(columns, ([key, label]) => ({ key, label }))
})
function detailQuantity(row: SemiReceiptRecord) {
  if (row.quantity_totals && row.quantity_totals.length > 1) return rowQuantity(row)
  if (row.lines && row.lines.length > 1) return `${number(row.quantity)} ${row.unit}`
  return `${number(row.source_detail?.received_quantity || row.quantity)} ${row.source_detail?.output_unit || row.unit}`
}
let sequence = 0, detailSequence = 0
function message(cause:unknown) { return cause instanceof AxiosError ? cause.response?.data?.error?.message || '请求失败，请重试。' : '请求失败，请重试。' }
async function confirm(row: SemiReceiptRecord) {
  if (confirming.value || deleting.value || row.status !== 'PENDING' || !canConfirm.value) return
  const fromDetail = visible.value && detail.value?.id === row.id
  if (fromDetail) detailError.value = ''
  confirming.value = row.id
  try {
    await confirmInternalReceiptRecord(row.receipt_id || row.id, row.etag)
    if (visible.value && detail.value?.id === row.id) { detailSequence++; visible.value = false; detail.value = null }
    await load()
  } catch (cause) {
    if (visible.value && detail.value?.id === row.id) detailError.value = message(cause)
    else error.value = message(cause)
  }
  finally { confirming.value = null }
}
async function remove(row: SemiReceiptRecord) {
  if (confirming.value || deleting.value || outgoing.value || row.status !== 'PENDING' || !row.can_delete) return
  deleting.value = row.id
  try {
    await ElMessageBox.confirm(`确定删除待入库单“${row.receipt_number}”？本单全部明细将删除，可重新提交入库。`, '删除待入库记录', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    if (!row.etag) {
      await load()
      error.value = '记录版本缺失，请刷新后重试。'
      return
    }
    await deleteInternalReceiptRecord(row.receipt_id || row.id, row.etag)
    if (detail.value?.id === row.id) { detailSequence++; visible.value = false; detail.value = null }
    if (rows.value.length === 1 && page.value > 1) page.value--
    await load()
  } catch (cause) {
    if (cause === 'cancel' || cause === 'close') return
    const failure = message(cause)
    if (cause instanceof AxiosError && [404, 409, 412, 428].includes(cause.response?.status || 0)) {
      if (detail.value?.id === row.id) { detailSequence++; visible.value = false; detail.value = null }
      await load()
      error.value = error.value ? `${failure} ${error.value}` : failure
    } else error.value = failure
  } finally { deleting.value = null }
}
async function load(reset=false) {
  if (reset) page.value=1
  const current=++sequence
  loading.value=true; error.value=''
  try {
    const result=await fetchSemiReceiptRecords({direction:direction.value,page:page.value,page_size:pageSize,source:source.value,search:search.value.trim(),date_from:dates.value?.[0],date_to:dates.value?.[1],product_line_id:route.query.product_line_id || undefined})
    if (current!==sequence) return
    rows.value=result.items; total.value=result.total
  } catch (cause) { if (current===sequence) { error.value=message(cause); rows.value=[] } }
  finally { if (current===sequence) loading.value=false }
}
async function open(row:SemiReceiptRecord) {
  const current=++detailSequence
  visible.value=true; detailLoading.value=true; detail.value=null; detailError.value=''
  try { const result=await fetchSemiReceiptRecord(row.id, direction.value); if(current===detailSequence) detail.value=result }
  catch(cause) { if(current===detailSequence) detailError.value=message(cause) }
  finally { if(current===detailSequence) detailLoading.value=false }
}
watch(() => [direction.value, route.query.product_line_id], () => { visible.value=false; detail.value=null; source.value=''; void load(true) }, { immediate: true })
</script>

<template>
  <section class="internal-receipt-page erp-glass-list">
    <section v-glass-spotlight class="erp-list-filter">
    <header class="receipt-heading erp-list-heading">
      <h1>{{ outgoing ? '半成品出库记录' : '车间入库' }}</h1>
      <span v-if="outgoing" class="muted">共 {{ total }} 条{{ actionLabel }}明细</span>
      <ElButton v-if="outgoing" class="erp-button-motion" @click="router.push({name:'material-inventory'})">材料库存</ElButton>
    </header>
    <div class="receipt-filters erp-list-filters"><ElInput v-model="search" clearable :placeholder="`搜索${actionLabel}单号、生产订单、产品或部位`" @keyup.enter="load(true)" @clear="load(true)" /><ElSelect v-model="source" placeholder="全部来源" aria-label="入库来源" @change="load(true)"><ElOption label="全部来源" value=""/><ElOption :label="outgoing ? '生产领用出库' : '厂内入库'" value="INTERNAL"/><ElOption :label="outgoing ? '其他出库' : '外发入库'" value="EXTERNAL"/></ElSelect><ElDatePicker v-model="dates" type="daterange" value-format="YYYY-MM-DD" :start-placeholder="`${actionLabel}开始日期`" :end-placeholder="`${actionLabel}结束日期`" @change="load(true)"/><ElButton class="erp-button-motion" @click="load()">刷新</ElButton><div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="search=''; source=''; dates=[]; load(true)">重置</ElButton><ElButton class="erp-button-motion" type="primary" :loading="loading" @click="load(true)">应用筛选</ElButton></div></div>
    <ElPagination v-if="!outgoing && !error && total > pageSize" v-model:current-page="page" class="receipt-page-controls" :page-size="pageSize" :total="total" :disabled="loading" layout="prev, pager, next" @current-change="load()" />
    </section>
    <section class="erp-list-data">
      <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <div class="erp-list-table-frame">
        <div v-horizontal-overflow class="receipt-records-table receipt-table-scroll erp-list-table-scroll scroll-actions-container" v-loading="loading">
          <table class="receipt-table erp-list-native-table erp-list-native-table--nowrap">
            <colgroup>
              <col style="width:178px"><col style="width:96px"><col style="width:144px"><col style="width:128px">
              <col v-if="outgoing" style="width:96px"><col style="width:80px"><col style="width:80px"><col style="width:128px">
              <col style="width:86px"><col v-if="outgoing" style="width:76px"><col style="width:100px"><col :style="{ width: mixedQuantityColumn ? '132px' : '82px' }">
              <col style="width:58px"><col v-if="!outgoing" style="width:96px"><col style="width:106px"><col style="width:82px">
              <col :style="{ width: outgoing ? '190px' : '80px' }">
            </colgroup>
            <thead>
              <tr>
                <th>{{ actionLabel }}单号</th><th>{{ actionLabel }}来源</th><th>生产订单</th><th>产品</th>
                <th v-if="outgoing">部位</th><th>品类</th><th>材质</th><th>规格</th><th>颜色</th><th v-if="outgoing">厚度</th>
                <th>加工阶段</th><th class="number">数量</th><th>单位</th><th v-if="!outgoing">提交人</th>
                <th>{{ actionLabel }}日期</th><th>状态</th><th class="scroll-actions-cell">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.id">
                <td :title="row.receipt_number" class="primary-text">{{ row.receipt_number }}</td>
                <td><span class="erp-list-tag" :class="row.source==='EXTERNAL' ? 'erp-list-tag--info' : 'erp-list-tag--brand'">{{ row.source_display }}</span></td>
                <td :title="row.production_order">{{ row.production_order }}</td>
                <td :title="row.product">{{ row.product }}</td>
                <td v-if="outgoing" :title="row.attributes.part_name" class="primary-text"><ProcessingMaterialDetails :materials="row">{{ row.attributes.part_name }}</ProcessingMaterialDetails></td>
                <td>{{ row.attributes.category }}</td><td>{{ row.attributes.material }}</td>
                <td :title="specification(row.attributes)">{{ specification(row.attributes) }}</td>
                <td :title="row.attributes.color">{{ row.attributes.color }}</td>
                <td v-if="outgoing">{{ row.attributes.tube_thickness || row.attributes.thickness || '—' }}</td>
                <td>{{ row.stage }}</td>
                <td class="number" :class="{ 'receipt-mixed-quantity': mixedQuantityColumn && (row.quantity_totals?.length || 0) > 1 }" :title="rowQuantity(row)">{{ rowQuantity(row) }}</td>
                <td>{{ row.unit }}</td>
                <td v-if="!outgoing" :title="row.submitted_by">{{ row.submitted_by || '—' }}</td>
                <td>{{ row.receipt_date }}</td>
                <td><span class="erp-list-tag" :class="row.status === 'PENDING' ? 'erp-list-tag--warning' : 'erp-list-tag--success'">{{ row.status === 'PENDING' ? '待入库' : `已${actionLabel}` }}</span></td>
                <td class="scroll-actions-cell">
                  <template v-if="outgoing">
                    <button class="receipt-link" @click="open(row)">查看</button>
                    <button v-if="row.status === 'PENDING' && canConfirm" class="receipt-link receipt-confirm-link" :disabled="Boolean(confirming || deleting)" data-testid="confirm-semi-receipt" @click="confirm(row)">{{ confirming === row.id ? '确认中…' : '确认入库' }}</button>
                  </template>
                  <ElDropdown v-else trigger="click" placement="bottom-end" :persistent="false">
                    <ElButton link type="primary" :loading="confirming === row.id || deleting === row.id">更多</ElButton>
                    <template #dropdown>
                      <ElDropdownMenu>
                        <ElDropdownItem data-testid="view-semi-receipt" @click="open(row)">查看</ElDropdownItem>
                        <ElDropdownItem v-if="row.status === 'PENDING' && canConfirm" :disabled="Boolean(confirming || deleting)" data-testid="confirm-semi-receipt" @click="open(row)">确认入库</ElDropdownItem>
                        <ElDropdownItem v-if="row.status === 'PENDING' && row.can_delete" :disabled="Boolean(confirming || deleting)" data-testid="delete-semi-receipt" divided @click="remove(row)">删除</ElDropdownItem>
                      </ElDropdownMenu>
                    </template>
                  </ElDropdown>
                </td>
              </tr>
              <tr v-if="!rows.length && !loading"><td :colspan="outgoing ? 16 : 15" class="empty">{{ error ? '加载失败，请重试' : `暂无${actionLabel}记录` }}</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      <footer v-if="outgoing" class="receipt-pagination erp-list-footer"><span class="muted">按{{ actionLabel }}流水展示，保留生产任务与产品来源</span><ElPagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next" @current-change="load()" /></footer>
    </section>
    <AppWindowDialog v-model="visible" :title="detail ? `${detail.source_display} · 来源详情` : `${actionLabel}来源详情`" :width="outgoing ? 1180 : '80vw'" :height="660" :min-width="760" :min-height="440" class="semi-receipt-source-dialog" :close-on-click-modal="false">
      <div v-loading="detailLoading" class="receipt-detail-body"><ElAlert v-if="detailError" :title="detailError" type="error" :closable="false"/><template v-if="detail">
        <div class="receipt-detail-title"><h2>{{ detail.receipt_number }}</h2><span class="receipt-tag" :class="{external:detail.source==='EXTERNAL'}">{{ detail.source_display }}</span><span class="receipt-tag" :class="detail.status === 'PENDING' ? 'warning' : 'success'">{{ detail.status === 'PENDING' ? '待入库' : `已${actionLabel}` }}</span></div>
        <div class="receipt-detail-grid"><label>生产订单<strong>{{ detail.production_order }}</strong></label><label>产品<strong>{{ detail.product }}</strong></label><label v-if="!outgoing">{{ detail.source==='INTERNAL' ? '厂内工序' : '加工厂' }}<strong>{{ detail.source_detail?.workshop || detail.source_detail?.factory || '—' }}</strong></label><label v-if="!outgoing && detail.source === 'EXTERNAL'">{{ detail.source_detail?.is_plan ? '委外总单' : '原外发单' }}<strong>{{ detail.source_detail?.source_number || '—' }}</strong></label><label>{{ actionLabel }}日期<strong>{{ detail.receipt_date }}</strong></label><label>材料仓 / 库区<strong>{{ detail.warehouse }} / {{ detail.zone }}</strong></label><label>{{ actionLabel }}人<strong>{{ detail.actor }}</strong></label></div>
        <template v-if="detail.source === 'EXTERNAL' && detail.source_detail?.source_type === 'TUBE_OUTSOURCING_RETURN'">
          <h3>{{ detail.source_detail.is_plan ? '委外总单入库' : '外发回货' }}</h3>
          <div class="receipt-detail-grid receipt-detail-progress">
            <label v-if="!detail.source_detail.is_plan">材料来源<strong>{{ detail.source_detail.source_kind_label || '—' }}</strong></label>
            <label>{{ detail.source_detail.is_plan ? '入库单号' : '回货单号' }}<strong>{{ detail.source_detail.receipt_number || detail.receipt_number }}</strong></label>
            <label>{{ detail.source_detail.is_plan ? '本次实收' : '实收数量' }}<strong>{{ detailQuantity(detail) }}</strong></label>
            <template v-if="!detail.source_detail.is_plan && !multipleDetailLines">
              <label>原料颜色<strong>{{ detail.source_detail.raw_color || '—' }}</strong></label>
              <label>喷塑颜色<strong>{{ detail.source_detail.spray_color || detail.attributes.color || '—' }}</strong></label>
              <label>实发数量<strong>{{ number(detail.source_detail.dispatched_quantity || '0') }} {{ detail.source_detail.output_unit || detail.unit }}</strong></label>
              <label>少回数量<strong>{{ number(detail.source_detail.shortage_quantity || '0') }} {{ detail.source_detail.output_unit || detail.unit }}</strong></label>
              <label>少回原因<strong>{{ detail.source_detail.shortage_reason || '—' }}</strong></label>
            </template>
          </div>
        </template>
        <h3>{{ actionLabel }}明细</h3>
        <div class="receipt-table-scroll">
          <table class="receipt-table" :style="outgoing ? undefined : { minWidth: `${360 + detailAttributeColumns.length * 108}px` }">
            <thead><tr>
              <th>部位</th>
              <template v-if="outgoing"><th>品类</th><th>材质</th><th>规格</th><th>颜色</th><th>厚度</th></template>
              <template v-else><th v-for="column in detailAttributeColumns" :key="column.key" class="receipt-attribute-cell">{{ column.label }}</th></template>
              <th>加工阶段</th><th class="number">数量</th><th>单位</th>
            </tr></thead>
            <tbody><tr v-for="{ line, fields } in detailTableRows" :key="line.id">
              <td><ProcessingMaterialDetails :materials="line">{{ line.attributes.part_name }}</ProcessingMaterialDetails></td>
              <template v-if="outgoing">
                <td>{{ line.attributes.category }}</td><td>{{ line.attributes.material }}</td><td>{{ specification(line.attributes) }}</td>
                <td>{{ line.attributes.color }}</td><td>{{ line.attributes.tube_thickness || line.attributes.thickness || '—' }}</td>
              </template>
              <template v-else>
                <td v-for="column in detailAttributeColumns" :key="column.key" class="receipt-attribute-cell">{{ fields?.get(column.key)?.value || '—' }}</td>
              </template>
              <td>{{ line.stage }}</td><td class="number">{{ number(line.quantity) }}</td><td>{{ line.unit }}</td>
            </tr></tbody>
          </table>
        </div>
        <template v-if="multipleDetailLines && detailLines.some(line => line.return_detail)">
          <h3>部位回货差额</h3>
          <div class="receipt-table-scroll"><table class="receipt-table">
            <thead><tr><th>部位</th><th>原料颜色</th><th>喷塑颜色</th><th>实发数量</th><th>少回数量</th><th>少回原因</th></tr></thead>
            <tbody><tr v-for="line in detailLines" :key="line.id"><td>{{ line.attributes.part_name }}</td>
              <td>{{ line.return_detail?.raw_color || '—' }}</td>
              <td>{{ line.return_detail?.spray_color || line.attributes.color || '—' }}</td>
              <td>{{ line.return_detail?.dispatched_quantity == null ? '—' : `${number(line.return_detail.dispatched_quantity)} ${line.unit}` }}</td>
              <td>{{ line.return_detail?.shortage_quantity == null ? '—' : `${number(line.return_detail.shortage_quantity)} ${line.unit}` }}</td>
              <td>{{ line.return_detail?.shortage_reason || '—' }}</td>
            </tr></tbody>
          </table></div>
        </template>
        <div v-if="outgoing" class="receipt-detail-grid"><label>出库前库存<strong>{{ detail.source_detail?.before_quantity }}</strong></label><label>出库后库存<strong>{{ detail.source_detail?.after_quantity }}</strong></label></div><p class="receipt-detail-remark">备注：{{ detail.source_detail?.remark || detail.remark || '—' }}</p>
      </template></div>
      <template #footer>
        <ElButton @click="visible=false">关闭</ElButton>
        <ElButton v-if="!outgoing && canConfirm && detail?.status === 'PENDING'" type="primary"
          data-testid="confirm-receipt-in-detail" :loading="confirming === detail.id"
          :disabled="!detail.etag || Boolean(confirming || deleting)" @click="confirm(detail)">确认入库</ElButton>
      </template>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
.receipt-heading > .el-button { margin-left: auto; }
.receipt-filters > :deep(.el-input) { width: min(100%, 320px); }
.receipt-filters > :deep(.el-select) { width: 140px; }
.receipt-filters > :deep(.el-date-editor) { width: 270px; flex: none; }
.receipt-page-controls { justify-content: flex-end; margin-top: 8px; }
.receipt-records-table .receipt-table { min-width: 1500px; }
.receipt-table .receipt-attribute-cell { white-space: normal; overflow-wrap: anywhere; }
.receipt-records-table td.receipt-mixed-quantity { white-space: normal; overflow-wrap: anywhere; padding-block: 4px; }
.receipt-link { border: 0; padding: 0; background: none; color: var(--erp-color-brand); cursor: pointer; font: inherit; }
.receipt-confirm-link { margin-left: 10px; color: var(--erp-color-success); }
.receipt-link:disabled { cursor: not-allowed; opacity: .6; }
</style>
