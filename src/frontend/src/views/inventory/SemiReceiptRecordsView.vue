<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { vHorizontalOverflow } from '@/directives/horizontalOverflow'
import { confirmInternalReceiptRecord, deleteInternalReceiptRecord, fetchSemiReceiptRecord, fetchSemiReceiptRecords } from '@/api/internalReceipts'
import { useAuthStore } from '@/stores/auth'
import type { SemiReceiptRecord, ReceiptAttributes } from '@/types/internalReceipt'
import '@/styles/internalReceipt.scss'
const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const canConfirm = computed(() => auth.user?.is_superuser === true || auth.hasPermission('inventory.confirm_internalsemifinishedreceipt'))
const outgoing = computed(() => route.name === 'semi-outbound-records' || route.query.direction === 'OUT')
const direction = computed(() => outgoing.value ? 'OUT' as const : 'IN' as const)
const actionLabel = computed(() => outgoing.value ? '出库' : '入库')
const rows = ref<SemiReceiptRecord[]>([]), total = ref(0), page = ref(1), source = ref(''), search = ref('')
const loading = ref(false), error = ref(''), detailLoading = ref(false), detailError = ref(''), visible = ref(false)
const detail = ref<SemiReceiptRecord | null>(null), dates = ref<string[] | null>([])
const confirming = ref<string | null>(null)
const deleting = ref<string | null>(null)
const number = (value:string) => Number(value).toLocaleString('zh-CN')
const specification = (value:ReceiptAttributes) => value.specification || `${value.tube_diameter} × ${value.cutting_length_mm}mm`
let sequence = 0, detailSequence = 0
function message(cause:unknown) { return cause instanceof AxiosError ? cause.response?.data?.error?.message || '请求失败，请重试。' : '请求失败，请重试。' }
async function confirm(row: SemiReceiptRecord) {
  if (confirming.value || deleting.value || row.status !== 'PENDING' || !canConfirm.value) return
  confirming.value = row.id
  try { await confirmInternalReceiptRecord(row.receipt_id || row.id, row.etag); await load() }
  catch (cause) { error.value = message(cause) }
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
    const result=await fetchSemiReceiptRecords({direction:direction.value,page:page.value,page_size:20,source:source.value,search:search.value.trim(),date_from:dates.value?.[0],date_to:dates.value?.[1],product_line_id:route.query.product_line_id || undefined})
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
    <header class="receipt-heading erp-list-heading"><h1>半成品{{ actionLabel }}记录</h1><span class="muted">共 {{ total }} 条{{ actionLabel }}明细</span><ElButton class="erp-button-motion" @click="router.push({name:'material-inventory'})">材料库存</ElButton></header>
    <div class="receipt-filters erp-list-filters"><ElInput v-model="search" clearable :placeholder="`搜索${actionLabel}单号、生产订单、产品或部位`" @keyup.enter="load(true)" @clear="load(true)" /><ElSelect v-model="source" placeholder="全部来源" aria-label="入库来源" @change="load(true)"><ElOption label="全部来源" value=""/><ElOption :label="outgoing ? '生产领用出库' : '厂内入库'" value="INTERNAL"/><ElOption :label="outgoing ? '其他出库' : '外发入库'" value="EXTERNAL"/></ElSelect><ElDatePicker v-model="dates" type="daterange" value-format="YYYY-MM-DD" :start-placeholder="`${actionLabel}开始日期`" :end-placeholder="`${actionLabel}结束日期`" @change="load(true)"/><ElButton class="erp-button-motion" @click="load()">刷新</ElButton><div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="search=''; source=''; dates=[]; load(true)">重置</ElButton><ElButton class="erp-button-motion" type="primary" :loading="loading" @click="load(true)">应用筛选</ElButton></div></div>
    </section>
    <section class="erp-list-data">
    <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div class="erp-list-table-frame"><div v-horizontal-overflow class="receipt-records-table receipt-table-scroll erp-list-table-scroll scroll-actions-container" v-loading="loading"><table class="receipt-table erp-list-native-table erp-list-native-table--nowrap"><colgroup><col style="width:178px"><col style="width:96px"><col style="width:144px"><col style="width:128px"><col style="width:96px"><col style="width:80px"><col style="width:80px"><col style="width:128px"><col style="width:86px"><col style="width:76px"><col style="width:100px"><col style="width:82px"><col style="width:58px"><col style="width:106px"><col style="width:82px"><col style="width:190px"></colgroup><thead><tr><th>{{ actionLabel }}单号</th><th>{{ actionLabel }}来源</th><th>生产订单</th><th>产品</th><th>部位</th><th>品类</th><th>材质</th><th>规格</th><th>颜色</th><th>厚度</th><th>加工阶段</th><th class="number">数量</th><th>单位</th><th>{{ actionLabel }}日期</th><th>状态</th><th class="scroll-actions-cell">操作</th></tr></thead><tbody>
      <tr v-for="row in rows" :key="row.id"><td :title="row.receipt_number" class="primary-text">{{ row.receipt_number }}</td><td><span class="erp-list-tag" :class="row.source==='EXTERNAL' ? 'erp-list-tag--info' : 'erp-list-tag--brand'">{{ row.source_display }}</span></td><td :title="row.production_order">{{ row.production_order }}</td><td :title="row.product">{{ row.product }}</td><td :title="row.attributes.part_name" class="primary-text">{{ row.attributes.part_name }}</td><td>{{ row.attributes.category }}</td><td>{{ row.attributes.material }}</td><td :title="specification(row.attributes)">{{ specification(row.attributes) }}</td><td :title="row.attributes.color">{{ row.attributes.color }}</td><td>{{ row.attributes.tube_thickness || row.attributes.thickness || '—' }}</td><td>{{ row.stage }}</td><td class="number">{{ number(row.quantity) }}</td><td>{{ row.unit }}</td><td>{{ row.receipt_date }}</td><td><span class="erp-list-tag" :class="row.status === 'PENDING' ? 'erp-list-tag--warning' : 'erp-list-tag--success'">{{ row.status === 'PENDING' ? '待入库' : `已${actionLabel}` }}</span></td><td class="scroll-actions-cell"><button class="receipt-link" @click="open(row)">查看</button><button v-if="row.status === 'PENDING' && canConfirm" class="receipt-link receipt-confirm-link" :disabled="Boolean(confirming || deleting)" data-testid="confirm-semi-receipt" @click="confirm(row)">{{ confirming === row.id ? '确认中…' : '确认入库' }}</button><button v-if="!outgoing && row.status === 'PENDING' && row.can_delete" class="receipt-link receipt-delete-link" :disabled="Boolean(confirming || deleting)" data-testid="delete-semi-receipt" @click="remove(row)">{{ deleting === row.id ? '处理中…' : '删除' }}</button></td></tr>
      <tr v-if="!rows.length && !loading"><td colspan="16" class="empty">{{ error ? '加载失败，请重试' : `暂无${actionLabel}记录` }}</td></tr>
    </tbody></table></div></div>
    <footer class="receipt-pagination erp-list-footer"><span class="muted">按{{ actionLabel }}流水展示，保留生产任务与产品来源</span><ElPagination v-model:current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="load()" /></footer>
    </section>
    <AppWindowDialog v-model="visible" :title="detail ? `${detail.source_display} · 来源详情` : `${actionLabel}来源详情`" :width="1180" :height="660" :min-width="760" :min-height="440" class="semi-receipt-source-dialog" :close-on-click-modal="false">
      <div v-loading="detailLoading" class="receipt-detail-body"><ElAlert v-if="detailError" :title="detailError" type="error" :closable="false"/><template v-if="detail">
        <div class="receipt-detail-title"><h2>{{ detail.receipt_number }}</h2><span class="receipt-tag" :class="{external:detail.source==='EXTERNAL'}">{{ detail.source_display }}</span><span class="receipt-tag" :class="detail.status === 'PENDING' ? 'warning' : 'success'">{{ detail.status === 'PENDING' ? '待入库' : `已${actionLabel}` }}</span></div>
        <div class="receipt-detail-grid"><label>生产订单<strong>{{ detail.production_order }}</strong></label><label>产品<strong>{{ detail.product }}</strong></label><label v-if="!outgoing">{{ detail.source==='INTERNAL' ? '厂内工序' : '加工厂' }}<strong>{{ detail.source_detail?.workshop || detail.source_detail?.factory || '—' }}</strong></label><label v-if="!outgoing && detail.source === 'EXTERNAL'">原外发单<strong>{{ detail.source_detail?.source_number || '—' }}</strong></label><label>{{ actionLabel }}日期<strong>{{ detail.receipt_date }}</strong></label><label>材料仓 / 库区<strong>{{ detail.warehouse }} / {{ detail.zone }}</strong></label><label>{{ actionLabel }}人<strong>{{ detail.actor }}</strong></label></div>
        <template v-if="detail.source === 'EXTERNAL' && detail.source_detail?.source_type === 'TUBE_OUTSOURCING_RETURN'"><h3>管材外发回货</h3><div class="receipt-detail-grid receipt-detail-progress"><label>材料来源<strong>{{ detail.source_detail?.source_kind_label || '—' }}</strong></label><label>回货单号<strong>{{ detail.source_detail?.receipt_number || detail.receipt_number }}</strong></label><label>原料颜色<strong>{{ detail.source_detail?.raw_color || '—' }}</strong></label><label>喷塑颜色<strong>{{ detail.source_detail?.spray_color || detail.attributes.color || '—' }}</strong></label><label>实发支数<strong>{{ number(detail.source_detail?.dispatched_quantity || '0') }} 支</strong></label><label>实收支数<strong>{{ number(detail.source_detail?.received_quantity || detail.quantity) }} 支</strong></label><label>少回支数<strong>{{ number(detail.source_detail?.shortage_quantity || '0') }} 支</strong></label><label>少回原因<strong>{{ detail.source_detail?.shortage_reason || '—' }}</strong></label></div></template>
        <h3>{{ actionLabel }}明细</h3><div class="receipt-table-scroll"><table class="receipt-table"><thead><tr><th>部位</th><th>品类</th><th>材质</th><th>规格</th><th>颜色</th><th>厚度</th><th>加工阶段</th><th class="number">数量</th><th>单位</th></tr></thead><tbody><tr><td>{{ detail.attributes.part_name }}</td><td>{{ detail.attributes.category }}</td><td>{{ detail.attributes.material }}</td><td>{{ specification(detail.attributes) }}</td><td>{{ detail.attributes.color }}</td><td>{{ detail.attributes.tube_thickness || detail.attributes.thickness || '—' }}</td><td>{{ detail.stage }}</td><td class="number">{{ number(detail.quantity) }}</td><td>{{ detail.unit }}</td></tr></tbody></table></div>
        <template v-if="!outgoing && detail.source==='INTERNAL'"><h3>部位入库进度</h3><div class="receipt-detail-grid receipt-detail-progress"><label>应入库<strong>{{ number(detail.source_detail?.required || '0') }} {{ detail.unit }}</strong></label><label>本次之前已入<strong>{{ number(detail.source_detail?.received_before || '0') }} {{ detail.unit }}</strong></label><label>本次之后累计<strong>{{ number(detail.source_detail?.received_after || '0') }} {{ detail.unit }}</strong></label><label>本次对应原料投入<strong><template v-if="detail.source_detail?.input_quantity === null">不核算</template><template v-else-if="detail.source_detail?.input_quantity != null">{{ number(detail.source_detail.input_quantity) }} {{ detail.source_detail.input_unit }}</template><template v-else>—</template></strong></label></div></template>
        <div v-if="outgoing" class="receipt-detail-grid"><label>出库前库存<strong>{{ detail.source_detail?.before_quantity }}</strong></label><label>出库后库存<strong>{{ detail.source_detail?.after_quantity }}</strong></label></div><p class="receipt-detail-remark">备注：{{ detail.source_detail?.remark || detail.remark || '—' }}</p>
      </template></div><template #footer><ElButton @click="visible=false">关闭</ElButton></template>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
.receipt-heading > .el-button { margin-left: auto; }
.receipt-filters > :deep(.el-input) { width: min(100%, 320px); }
.receipt-filters > :deep(.el-select) { width: 140px; }
.receipt-filters > :deep(.el-date-editor) { width: 270px; flex: none; }
.receipt-records-table .receipt-table { min-width: 1500px; }
.receipt-link { border: 0; padding: 0; background: none; color: var(--erp-color-brand); cursor: pointer; font: inherit; }
.receipt-confirm-link { margin-left: 10px; color: var(--erp-color-success); }
.receipt-delete-link { margin-left: 10px; color: var(--erp-color-danger); }
.receipt-link:disabled { cursor: not-allowed; opacity: .6; }
</style>
