<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Document, Refresh } from '@element-plus/icons-vue'
import MetalReceiptTable from '@/components/inventory/MetalReceiptTable.vue'
import { fetchReceiptPreview, confirmInternalReceipt } from '@/api/internalReceipts'
import type { ReceiptPayload, ReceiptPreview } from '@/types/internalReceipt'
import '@/styles/metalInternalReceipt.scss'

const route = useRoute(), router = useRouter()
const preview = ref<ReceiptPreview | null>(null), loading = ref(false), saving = ref(false), error = ref('')
const previewReady = ref(false)
const zoneId = ref(''), receiptDate = ref(''), remark = ref('')
const quantities = ref<Record<string,string | number>>({}), selected = ref<Record<string,boolean>>({})
const pending = ref<{payload:ReceiptPayload; etag:string} | null>(null)
const pendingKey = `internal-receipt-pending:${String(route.query.schedule_product_id)}:${String(route.query.plan_category)}`
const isSewing = computed(() => (preview.value?.plan_category || route.query.plan_category) === 'SEWING')
const selection = computed(() => (preview.value?.lines || []).filter(line => isSewing.value
  ? Number(quantities.value[line.bom_line_id]) > 0
  : selected.value[line.bom_line_id]))
const quantityTotal = computed(() => selection.value.reduce((sum,line) => sum + (Number(quantities.value[line.bom_line_id]) || 0),0))
const warehouses = computed(() => [...new Set(preview.value?.zones.map(zone => zone.warehouse) || [])])
const warehouse = ref('')
const zones = computed(() => preview.value?.zones.filter(zone => zone.warehouse === warehouse.value) || [])
const number = (value:string) => Number(value).toLocaleString('zh-CN')
const info = computed(() => [
  ['生产任务单号', preview.value?.production_order], ['产品名称', preview.value?.product],
  ['工序', isSewing.value ? '车缝' : '金工'], ['订单数量', preview.value ? number(preview.value.order_quantity) : '—'],
  ['入库来源', isSewing.value ? '厂内车缝' : '厂内金工'],
])
const columns = computed(() => [
  ...(!isSewing.value ? [{ key: 'selected', label: '选择', width: 56 }] : []),
  { key: 'part', label: '部位', width: 110 }, { key: 'material', label: '材质', width: 90 },
  { key: 'specification', label: '规格', width: 140 }, { key: 'color', label: '颜色', width: 100 },
  { key: 'stage', label: '加工阶段', width: 100 }, { key: 'unit', label: '单位', width: 60 },
  { key: 'usage', label: '单个用量', width: 100, num: true },
  { key: 'required', label: '应入库', width: 100, num: true },
  { key: 'received', label: '已入库', width: 100, num: true },
  { key: 'can_receive', label: '剩余可入', width: 100, num: true },
  { key: 'quantity', label: `本次入库（${isSewing.value ? '套' : '支'}）`, width: 160 },
])
function resetQuantities() {
  if (saving.value || pending.value) return
  quantities.value = {}; selected.value = {}
}
function errorText(cause:unknown) {
  if (cause instanceof AxiosError) return cause.response?.data?.error?.message || '请求未完成，请重试。'
  return '页面加载失败，请重试。'
}
async function load() {
  loading.value = true; previewReady.value = false; error.value = ''
  try {
    preview.value = await fetchReceiptPreview(String(route.query.schedule_product_id || ''),String(route.query.plan_category || ''))
    receiptDate.value ||= preview.value.receipt_date
    warehouse.value ||= preview.value.zones.find(zone => zone.id === zoneId.value)?.warehouse || warehouses.value[0] || ''
    zoneId.value ||= zones.value[0]?.id || ''
    if (!pending.value) { quantities.value = {}; selected.value = {} }
    previewReady.value = true
  } catch (cause) { error.value = errorText(cause) }
  finally { loading.value = false }
}
async function submit() {
  if (loading.value || saving.value) return
  if (!pending.value) {
    if (!preview.value || !previewReady.value) return
    error.value = ''
    if (!zoneId.value || !receiptDate.value) { error.value = '请选择库区和日期。'; return }
    if (isSewing.value) {
      for (const line of preview.value.lines) {
        const raw = String(quantities.value[line.bom_line_id] ?? '').trim()
        if (!raw || Number(raw) === 0) continue
        const quantity = Number(raw)
        if (!Number.isSafeInteger(quantity) || quantity < 0 || quantity > Number(line.can_receive)) {
          error.value = `${line.attributes.part_name}：本次入库须为非负整数，且不能超过剩余可入数量。`; return
        }
      }
      if (!selection.value.length) { error.value = '请至少填写一项大于 0 的本次入库数量。'; return }
    } else if (!selection.value.length) { error.value = '请选择本次入库部位。'; return }
    for (const line of selection.value) {
      const quantity = Number(quantities.value[line.bom_line_id])
      if (!Number.isSafeInteger(quantity) || quantity <= 0 || quantity > Number(line.can_receive)) {
        error.value = `${line.attributes.part_name}：本次入库须为正整数，且不能超过剩余可入数量。`; return
      }
    }
    pending.value = { etag: preview.value.etag, payload: { request_id: crypto.randomUUID(),
      schedule_product_id: preview.value.schedule_product_id, plan_category: preview.value.plan_category,
      zone_id: zoneId.value, receipt_date: receiptDate.value, remark: remark.value.trim(),
      lines: selection.value.map(line => ({bom_line_id:line.bom_line_id,quantity:String(quantities.value[line.bom_line_id])})),
    } }
    sessionStorage.setItem(pendingKey,JSON.stringify(pending.value))
  }
  error.value = ''
  saving.value = true
  try {
    const result = await confirmInternalReceipt(pending.value.payload,pending.value.etag)
    pending.value = null; sessionStorage.removeItem(pendingKey)
    ElMessage.success(`已提交待入库：${result.receipt_number}`)
    await load()
  } catch (cause) {
    const status = cause instanceof AxiosError ? cause.response?.status : undefined
    if (status && [400, 412, 428].includes(status)) {
      pending.value = null; sessionStorage.removeItem(pendingKey)
      error.value = errorText(cause)
      if (status === 412) error.value += ' 请刷新后重新填写。'
    } else error.value = '提交结果尚未确认。请点击“核对本次提交”，使用原请求核对，避免重复入库。'
  } finally { saving.value = false }
}
onMounted(() => {
  try {
    const saved = sessionStorage.getItem(pendingKey)
    if (saved) {
      pending.value = JSON.parse(saved)
      if (!pending.value?.payload?.request_id || !Array.isArray(pending.value.payload.lines)) throw new Error('未确认请求格式不完整')
      const payload = pending.value.payload
      zoneId.value = payload.zone_id; receiptDate.value = payload.receipt_date; remark.value = payload.remark
      quantities.value = Object.fromEntries(payload.lines.map(line => [line.bom_line_id,line.quantity]))
      selected.value = Object.fromEntries(payload.lines.map(line => [line.bom_line_id,true]))
    }
  }
  catch { pending.value = null; sessionStorage.removeItem(pendingKey) }
  void load()
})
</script>

<template>
  <section class="sewing-receipt-page erp-glass-form" v-loading="loading">
    <header class="page-heading"><div class="title-row"><h1>半成品入库</h1><span class="status info">{{ isSewing ? '厂内车缝' : '厂内金工' }}</span></div><ElButton :icon="Document" :disabled="saving" @click="router.push({name:'semi-receipt-records'})">入库记录</ElButton></header>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="preview">
      <section class="panel d1-context"><div class="info-grid"><div v-for="[label, value] in info" :key="label" class="info-cell"><span>{{ label }}</span><strong :title="value || '—'">{{ value || '—' }}</strong></div></div></section>
      <section class="panel d1-workspace">
        <div class="section-heading"><div><h2>本次入库</h2><span class="muted">{{ isSewing ? '按订单与 BOM 套数净需求，扣除累计入库、车缝直发及待发预留' : '按订单净需求和实际已领投入共同控制上限' }}</span></div><ElButton :icon="Refresh" :disabled="saving || !!pending" @click="load">刷新</ElButton></div>
        <div class="field-grid d1-fields erp-flat-form">
          <label class="form-field required"><span>收货日期</span><ElDatePicker v-model="receiptDate" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" popper-class="schedule-date-popper" aria-label="收货日期" :disabled="saving || !!pending" /></label>
          <label class="form-field required"><span>材料仓</span><ElSelect v-model="warehouse" aria-label="材料仓" :disabled="saving || !!pending" @change="zoneId = zones[0]?.id || ''"><ElOption v-for="name in warehouses" :key="name" :label="name" :value="name" /></ElSelect></label>
          <label class="form-field required"><span>库区</span><ElSelect v-model="zoneId" aria-label="库区" :disabled="saving || !!pending"><ElOption v-for="zone in zones" :key="zone.id" :label="zone.name" :value="zone.id" /></ElSelect></label>
          <label class="form-field"><span>入库人</span><ElInput :model-value="preview.actor" disabled aria-label="入库人" /></label>
        </div>
        <MetalReceiptTable :columns="columns" :rows="preview.lines" row-key="bom_line_id" class="erp-table-editor d1-lines" :empty="preview.excluded.length ? '本计划管材需外发喷塑，请在原外发单登记回库。' : '暂无可入库部位'">
          <template #cell-selected="{ row }"><input v-model="selected[row.bom_line_id]" type="checkbox" :aria-label="`选择${row.attributes.part_name}`" :disabled="Number(row.can_receive) <= 0 || saving || !!pending"></template>
          <template #cell-part="{ row }"><strong class="cell-text" :title="row.attributes.part_name">{{ row.attributes.part_name }}</strong></template>
          <template #cell-material="{ row }"><span class="cell-text" :title="row.attributes.material">{{ row.attributes.material || '—' }}</span></template>
          <template #cell-specification="{ row }"><span class="cell-text" :title="row.attributes.specification">{{ row.attributes.specification || (row.attributes.tube_diameter ? `${row.attributes.tube_diameter}×${row.attributes.tube_thickness}×${row.attributes.cutting_length_mm}mm` : '—') }}</span></template>
          <template #cell-color="{ row }"><span class="cell-text" :title="row.attributes.color">{{ row.attributes.color || '—' }}</span></template>
          <template #cell-unit="{ row }">{{ row.attributes.unit_name }}</template>
          <template #cell-usage="{ row }">{{ number(row.usage) }}</template>
          <template #cell-required="{ row }">{{ number(row.required) }}</template>
          <template #cell-received="{ row }">{{ number(row.received) }}</template>
          <template #cell-can_receive="{ row }"><strong :class="Number(row.can_receive) > 0 ? 'brand' : 'muted'" :title="isSewing ? `应入库 ${row.required} 套，厂内及外发累计已入库 ${row.received} 套；剩余可入已扣车缝直发及待发预留` : `已领投入剩余 ${row.input_remaining}，支持产出 ${row.input_supported}`">{{ number(row.can_receive) }}</strong></template>
          <template #cell-quantity="{ row }"><ElInput v-model="quantities[row.bom_line_id]" type="number" :min="isSewing ? 0 : 1" step="1" :max="row.can_receive" :aria-label="`${row.attributes.part_name}本次入库`" :placeholder="Number(row.can_receive) ? '填写数量' : '暂无可入数量'" :disabled="Number(row.can_receive) <= 0 || (!isSewing && !selected[row.bom_line_id]) || saving || !!pending"><template #suffix><span class="d1-unit">{{ row.attributes.unit_name }}</span></template></ElInput></template>
        </MetalReceiptTable>
        <label class="form-field d1-remark erp-flat-form"><span>入库备注 <small class="muted">{{ isSewing ? '选填 · 车缝按套入库' : '选填' }}</small></span><ElInput v-model="remark" type="textarea" :rows="3" maxlength="2000" placeholder="填写本次收货说明" aria-label="入库备注" :disabled="saving || !!pending" /></label>
      </section>
    </template>
    <section v-else class="panel d1-fallback"><ElSkeleton v-if="loading" :rows="9" animated /><template v-else><ElEmpty :description="error || '入库资料读取失败，请重试'" /><ElButton :icon="Refresh" @click="load">重新加载</ElButton></template></section>
    <footer class="footer-bar"><div>本次入库 <strong>{{ quantityTotal.toLocaleString('zh-CN') }}</strong> {{ isSewing ? '套' : '支' }} <span class="muted"> · {{ selection.length }} 个部位</span><small>提交后由仓库确认，确认后增加公共半成品库存</small></div><ElButton :icon="ArrowLeft" :disabled="saving" @click="router.back()">返回</ElButton><ElButton :icon="Refresh" :disabled="!preview || loading || saving || !!pending" @click="resetQuantities">重填</ElButton><ElButton type="primary" :loading="saving" :disabled="loading || saving || (!pending && (!preview || !previewReady || !selection.length))" @click="submit">{{ pending ? '核对本次提交' : '提交待入库' }}</ElButton></footer>
  </section>
</template>
