<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { fetchReceiptPreview, confirmInternalReceipt } from '@/api/internalReceipts'
import type { ReceiptPayload, ReceiptPreview } from '@/types/internalReceipt'
import '@/styles/internalReceipt.scss'

const route = useRoute(), router = useRouter()
const preview = ref<ReceiptPreview | null>(null), loading = ref(false), saving = ref(false), error = ref('')
const zoneId = ref(''), receiptDate = ref(''), remark = ref('')
const quantities = ref<Record<string,string | number>>({}), selected = ref<Record<string,boolean>>({})
const pending = ref<{payload:ReceiptPayload; etag:string} | null>(null)
const pendingKey = `internal-receipt-pending:${String(route.query.schedule_product_id)}:${String(route.query.plan_category)}`
const isSewing = computed(() => preview.value?.plan_category === 'SEWING')
const selection = computed(() => (preview.value?.lines || []).filter(line => isSewing.value
  ? Number(quantities.value[line.bom_line_id]) > 0
  : selected.value[line.bom_line_id]))
const quantityTotal = computed(() => selection.value.reduce((sum,line) => sum + (Number(quantities.value[line.bom_line_id]) || 0),0))
const warehouses = computed(() => [...new Set(preview.value?.zones.map(zone => zone.warehouse) || [])])
const warehouse = ref('')
const zones = computed(() => preview.value?.zones.filter(zone => zone.warehouse === warehouse.value) || [])
const number = (value:string) => Number(value).toLocaleString('zh-CN')
function errorText(cause:unknown) {
  if (cause instanceof AxiosError) return cause.response?.data?.error?.message || '请求未完成，请重试。'
  return '页面加载失败，请重试。'
}
async function load() {
  loading.value = true; error.value = ''
  try {
    preview.value = await fetchReceiptPreview(String(route.query.schedule_product_id || ''),String(route.query.plan_category || ''))
    receiptDate.value ||= preview.value.receipt_date
    warehouse.value ||= preview.value.zones.find(zone => zone.id === zoneId.value)?.warehouse || warehouses.value[0] || ''
    zoneId.value ||= zones.value[0]?.id || ''
    if (!pending.value) { quantities.value = {}; selected.value = {} }
  } catch (cause) { error.value = errorText(cause) }
  finally { loading.value = false }
}
async function submit() {
  if (!preview.value || saving.value) return
  error.value = ''
  if (!pending.value) {
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
  saving.value = true
  try {
    const result = await confirmInternalReceipt(pending.value.payload,pending.value.etag)
    pending.value = null; sessionStorage.removeItem(pendingKey)
    ElMessage.success(`入库成功：${result.receipt_number}`)
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
  <section class="internal-receipt-page" v-loading="loading">
    <header class="receipt-heading"><h1>半成品入库</h1><span class="receipt-tag">厂内入库</span><span class="muted">{{ preview?.plan_category === 'SEWING' ? '车缝计划' : '金工计划' }}</span><ElButton @click="router.push({name:'semi-receipt-records'})">入库记录</ElButton></header>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div v-if="preview" class="receipt-form-scroll">
      <section class="receipt-summary">
        <div class="receipt-summary-grid"><label>生产订单<strong>{{ preview.production_order }}</strong></label><label>产品<strong>{{ preview.product }}</strong></label><label>工序<strong>{{ preview.plan_category === 'METAL' ? '金工' : '车缝' }}</strong></label><label>订单数量<strong>{{ number(preview.order_quantity) }}</strong></label></div>
        <fieldset :disabled="saving || !!pending" class="receipt-fields"><label>收货日期<input v-model="receiptDate" type="date" aria-label="收货日期"></label><label>材料仓<select v-model="warehouse" aria-label="材料仓" @change="zoneId = zones[0]?.id || ''"><option v-for="name in warehouses" :key="name">{{ name }}</option></select></label><label>库区<select v-model="zoneId" aria-label="库区"><option v-for="zone in zones" :key="zone.id" :value="zone.id">{{ zone.name }}</option></select></label><label>入库人<input :value="preview.actor" disabled aria-label="入库人"></label></fieldset>
      </section>
      <section class="receipt-form-section"><div class="receipt-section-heading"><h2>本次入库明细</h2><span class="muted">按订单净需求和实际已领投入共同控制上限</span><ElButton :disabled="saving || !!pending" @click="load">刷新</ElButton></div>
      <div class="receipt-table-scroll"><table class="erp-table-editor receipt-table receipt-entry-table"><colgroup><col v-if="!isSewing" style="width:56px"><col style="width:150px"><col style="width:240px"><col style="width:110px"><col style="width:125px"><col style="width:70px"><col style="width:105px"><col style="width:120px"><col style="width:120px"><col style="width:125px"><col style="width:160px"></colgroup><thead><tr><th v-if="!isSewing">选择</th><th>部位</th><th>材质 / 规格</th><th>颜色</th><th>加工阶段</th><th>单位</th><th class="number">单个用量</th><th class="number">应入库</th><th class="number">已入库</th><th class="number">剩余可入</th><th class="number">本次入库</th></tr></thead><tbody>
        <tr v-for="line in preview.lines" :key="line.bom_line_id"><td v-if="!isSewing"><input v-model="selected[line.bom_line_id]" type="checkbox" :aria-label="`选择${line.attributes.part_name}`" :disabled="Number(line.can_receive) <= 0 || saving || !!pending"></td><td class="primary-text">{{ line.attributes.part_name }}</td><td :title="`${line.attributes.material} / ${line.attributes.specification || line.attributes.tube_diameter}`">{{ line.attributes.material }} / {{ line.attributes.specification || `${line.attributes.tube_diameter}×${line.attributes.tube_thickness}×${line.attributes.cutting_length_mm}mm` }}</td><td>{{ line.attributes.color }}</td><td>{{ line.stage }}</td><td>{{ line.attributes.unit_name }}</td><td class="number">{{ number(line.usage) }}</td><td class="number">{{ number(line.required) }}</td><td class="number">{{ number(line.received) }}</td><td class="number" :title="`已领投入剩余 ${line.input_remaining}，支持产出 ${line.input_supported}`">{{ number(line.can_receive) }}</td><td><input v-model="quantities[line.bom_line_id]" class="quantity-input" type="number" :min="isSewing ? 0 : 1" step="1" :max="line.can_receive" :aria-label="`${line.attributes.part_name}本次入库`" :placeholder="Number(line.can_receive) ? '填写数量' : '暂无可入数量'" :disabled="Number(line.can_receive) <= 0 || (!isSewing && !selected[line.bom_line_id]) || saving || !!pending"></td></tr>
        <tr v-if="!preview.lines.length"><td :colspan="isSewing ? 10 : 11" class="empty">{{ preview.excluded.length ? '本计划管材需外发喷塑，请在原外发单登记回库。' : '暂无可入库部位' }}</td></tr>
      </tbody></table></div>
      <p class="muted receipt-helper">需外发喷塑的部件沿用原外发流程，不在此重复入库。车缝按套入库，投入面料按米核算。</p>
      <label class="receipt-remark">备注<textarea v-model="remark" maxlength="2000" placeholder="填写本次收货说明" :disabled="saving || !!pending" /></label>
      </section>
    </div>
    <footer class="receipt-footer"><div>{{ isSewing ? '已填写' : '已选' }} <strong>{{ selection.length }}</strong> 项 · 本次入库 <strong>{{ quantityTotal.toLocaleString('zh-CN') }}</strong> {{ preview?.plan_category === 'METAL' ? '支' : '套' }}<p class="muted">确认后立即增加公共半成品库存</p></div><ElButton :disabled="saving" @click="router.back()">返回</ElButton><ElButton type="primary" :loading="saving" :disabled="!preview || (!pending && !selection.length)" @click="submit">{{ pending ? '核对本次提交' : '确认入库' }}</ElButton></footer>
  </section>
</template>
