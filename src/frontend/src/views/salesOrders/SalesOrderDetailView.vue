<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { MoreFilled, UploadFilled } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import {
  addSalesOrderCollaborationEvent,
  cancelSalesOrderDeliveryBatch,
  completeSalesOrder,
  confirmSalesOrder,
  fetchSalesOrder,
  salesOrderEvidenceUrl,
  uploadSalesOrderEvidence,
} from '@/api/salesOrders'
import { fetchAllProductionDataRecords } from '@/api/productionData'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import SalesOrderProductsTable from './SalesOrderProductsTable.vue'
import { useAuthStore } from '@/stores/auth'
import type { ProductCategory, ProductionUnit } from '@/types/productionData'
import type { SalesOrder, SalesOrderBatchLine, SalesOrderDeliveryBatch } from '@/types/salesOrder'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const canOrder = (code: string) => !authStore.user?.sales_access_enabled || authStore.canFor(code, order.value)
const orderId = computed(() => String(route.params.orderId || ''))
const order = ref<SalesOrder | null>(null)
const productCategories = ref<ProductCategory[]>([])
const productUnits = ref<ProductionUnit[]>([])
const productCatalogError = ref('')
const etag = ref('')
const pageState = ref<'loading' | 'ready' | 'error' | 'forbidden'>('loading')
const errorMessage = ref('')
const actionLoading = ref(false)
const activeTab = ref('information')
const confirmVisible = ref(false)
const blockedVisible = ref(false)
const conflictVisible = ref(false)
const collaborationVisible = ref(false)
const cancelBatchVisible = ref(false)
const completeVisible = ref(false)
const exceptionCloseVisible = ref(false)
const selectedBatch = ref<SalesOrderDeliveryBatch | null>(null)
const collaborationForm = reactive({ delivery_batch_id: null as string | null, event_type: 'NOTE', status: 'PENDING', title: '', note: '', quantity: null as string | null, occurred_at: '' })
const cancelForm = reactive({ reason: '', evidence_file_id: '' })
const completeForm = reactive({ note: '', reason: '' })
const eventTypes = [
  ['DEPOSIT', '订金'], ['CONTRACT', '合同'], ['PREPRODUCTION_SAMPLE', '产前样'], ['INSPECTION', '验货'],
  ['BOOKING', '订舱'], ['SHIPMENT', '发货'], ['BALANCE', '余款'], ['DOCUMENT', '单证'], ['NOTE', '备注'],
]

const canCreateProductionTask = computed(() => Boolean(
  ['CONFIRMED', 'FULFILLING'].includes(order.value?.status || '')
  && (authStore.user?.is_superuser || authStore.hasPermission('production_tasks.add_productiontask')),
))
const canCancelBatch = computed(() => canOrder('access_control.cancelbatch_salesorder') && ['CONFIRMED', 'FULFILLING'].includes(order.value?.status || ''))
const activeBatches = computed(() => order.value?.delivery_batches.filter((batch) => batch.status === 'ACTIVE') || [])
const batchHasProductionCapacity = (batch: SalesOrderDeliveryBatch) => batch.lines.some((line) => Math.floor(Number(line.remaining_quantity)) >= 1)
const confirmAllocations = computed(() => (order.value?.lines || []).map((line) => ({
  id: line.id,
  product: line.product_name_snapshot,
  ordered: Number(line.quantity),
  allocated: activeBatches.value.reduce((sum, batch) => sum + Number(batch.lines.find((item) => item.sales_order_line_id === line.id)?.quantity || 0), 0),
})))
const activeDemand = computed(() => activeBatches.value.reduce((sum, batch) => sum + batch.lines.reduce((lineSum, line) => lineSum + Number(line.quantity), 0), 0))
const completedShipment = computed(() => (order.value?.collaboration_events || [])
  .filter((item) => item.event_type === 'SHIPMENT' && item.status === 'COMPLETED')
  .reduce((sum, item) => sum + Number(item.quantity || 0), 0))
const remainingShipment = computed(() => Math.max(activeDemand.value - completedShipment.value, 0))
const balanceCompleted = computed(() => Boolean(order.value?.collaboration_events.some((item) => item.event_type === 'BALANCE' && item.status === 'COMPLETED')))
const normalCompletionReady = computed(() => activeDemand.value > 0 && remainingShipment.value <= 0 && balanceCompleted.value)
const confirmChecks = computed(() => [
  { label: '已选择当前客户名下的有效买方地址', passed: Boolean(order.value?.buyer_address_id) },
  { label: '每个产品的交付批次数量均已完整分配', passed: Boolean(order.value?.lines.length) && order.value!.lines.every((line) => {
    const allocated = activeBatches.value.reduce((sum, batch) => sum + Number(batch.lines.find((item) => item.sales_order_line_id === line.id)?.quantity || 0), 0)
    return Math.abs(allocated - Number(line.quantity)) < 0.00001
  }) },
  { label: '无报价或返单已上传客户书面凭证', passed: order.value?.source_type === 'QUOTATION' || Boolean(order.value?.evidence.length) },
])
const canConfirm = computed(() => confirmChecks.value.every((item) => item.passed))

function apiError(error: unknown): string {
  const response = (error as { response?: { data?: { detail?: string; error?: { message?: string; field_errors?: Record<string, string[]> } } } })?.response?.data
  const field = response?.error?.field_errors ? Object.values(response.error.field_errors).flat()[0] : ''
  return field || response?.error?.message || response?.detail || '操作失败，请稍后重试。'
}
function apiErrorCode(error: unknown): string {
  return String((error as { response?: { data?: { error?: { code?: string } } } })?.response?.data?.error?.code || '')
}
function apiStatus(error: unknown): number {
  return Number((error as { response?: { status?: number } })?.response?.status || 0)
}
function snapshotText(snapshot: Record<string, unknown>, key: string): string {
  return String(snapshot[key] || '').trim()
}
function sellerText(key: string): string {
  const snapshot = order.value?.seller_snapshot || {}
  const nested = snapshot.template_config
  return snapshotText(nested && typeof nested === 'object' ? nested as Record<string, unknown> : snapshot, key)
}
function addressText(): string {
  if (!order.value) return '—'
  const snapshot = order.value.buyer_address_snapshot
  return [snapshotText(snapshot, 'country_code'), snapshotText(snapshot, 'state_province'), snapshotText(snapshot, 'city'), snapshotText(snapshot, 'address_line1'), snapshotText(snapshot, 'address_line2')].filter(Boolean).join(' · ') || '—'
}
function numberText(value: string | number): string {
  return Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}
function formatDateTime(value: string | null): string {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
}
function statusClass(value: string): string {
  if (['CONFIRMED', 'COMPLETED', 'READY', 'IN_PRODUCTION'].includes(value)) return 'is-success'
  if (value === 'FULFILLING') return 'is-info'
  if (['RISK', 'PAUSED', 'PENDING'].includes(value)) return 'is-warning'
  if (['CANCELLED', 'REJECTED'].includes(value)) return 'is-danger'
  return 'is-neutral'
}
function handleMutationError(error: unknown) {
  if ([409, 412].includes(apiStatus(error)) || apiErrorCode(error) === 'CONCURRENT_UPDATE') conflictVisible.value = true
  else ElMessage.error(apiError(error))
}
function clearDialogState() {
  confirmVisible.value = false
  blockedVisible.value = false
  conflictVisible.value = false
  collaborationVisible.value = false
  cancelBatchVisible.value = false
  completeVisible.value = false
  exceptionCloseVisible.value = false
  selectedBatch.value = null
  Object.assign(collaborationForm, { delivery_batch_id: null, event_type: 'NOTE', status: 'PENDING', title: '', note: '', quantity: null, occurred_at: '' })
  Object.assign(cancelForm, { reason: '', evidence_file_id: '' })
  Object.assign(completeForm, { note: '', reason: '' })
}
async function load() {
  pageState.value = 'loading'
  errorMessage.value = ''
  order.value = null
  etag.value = ''
  clearDialogState()
  try {
    const result = await fetchSalesOrder(orderId.value)
    order.value = result.data
    etag.value = result.etag
    pageState.value = 'ready'
  } catch (error) {
    pageState.value = apiStatus(error) === 403 ? 'forbidden' : 'error'
    errorMessage.value = apiError(error)
  }
}
async function confirmOrder() {
  if (actionLoading.value || !order.value || !canConfirm.value) return
  actionLoading.value = true
  try {
    const result = await confirmSalesOrder(order.value.id, etag.value)
    order.value = result.data
    etag.value = result.etag
    confirmVisible.value = false
    ElMessage.success('销售订单已确认。')
  } catch (error) {
    if (apiErrorCode(error) === 'BUYER_ADDRESS_REQUIRED') {
      confirmVisible.value = false
      blockedVisible.value = true
    } else handleMutationError(error)
  } finally { actionLoading.value = false }
}
async function uploadEvidence(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (actionLoading.value || !file || !order.value) return
  actionLoading.value = true
  try {
    const result = await uploadSalesOrderEvidence(order.value.id, file, etag.value)
    order.value = result.data
    etag.value = result.etag
    ElMessage.success('客户确认凭证已上传。')
  } catch (error) { handleMutationError(error) } finally { actionLoading.value = false; target.value = '' }
}
function openProduction(batch: SalesOrderDeliveryBatch, line?: SalesOrderBatchLine) {
  if (!order.value || !(line ? Number(line.remaining_quantity) >= 1 : batchHasProductionCapacity(batch))) {
    ElMessage.warning('该批次产品已全部建立生产任务，无剩余可建数量。')
    return
  }
  void router.push({ name: 'production-task-create', query: {
    sales_order_id: order.value.id, delivery_batch_id: batch.id,
  } })
}
function openCollaboration(batchId: string | null = null, eventType = 'NOTE') {
  Object.assign(collaborationForm, { delivery_batch_id: batchId, event_type: eventType, status: 'PENDING', title: '', note: '', quantity: null, occurred_at: new Date().toISOString() })
  collaborationVisible.value = true
}
async function addEvent() {
  if (actionLoading.value) return
  if (!order.value || !collaborationForm.title.trim()) return ElMessage.warning('请填写协同事项标题。')
  if (collaborationForm.event_type === 'SHIPMENT' && Number(collaborationForm.quantity || 0) <= 0) return ElMessage.warning('发货事项必须填写有效发货数量。')
  actionLoading.value = true
  try {
    const result = await addSalesOrderCollaborationEvent(order.value.id, { ...collaborationForm }, etag.value)
    etag.value = result.etag
    collaborationVisible.value = false
    await load()
    ElMessage.success('协同事项已登记。')
  } catch (error) { handleMutationError(error) } finally { actionLoading.value = false }
}
function openCancelBatch(batch: SalesOrderDeliveryBatch) {
  selectedBatch.value = batch
  Object.assign(cancelForm, { reason: '', evidence_file_id: order.value?.evidence.at(-1)?.file_id || '' })
  cancelBatchVisible.value = true
}
async function cancelBatch() {
  if (actionLoading.value || !order.value || !selectedBatch.value) return
  if (!cancelForm.reason.trim() || !cancelForm.evidence_file_id) return ElMessage.warning('取消原因和本订单客户凭证均为必填。')
  actionLoading.value = true
  try {
    const result = await cancelSalesOrderDeliveryBatch(order.value.id, selectedBatch.value.id, cancelForm.reason.trim(), cancelForm.evidence_file_id, etag.value)
    order.value = result.data
    etag.value = result.etag
    cancelBatchVisible.value = false
    ElMessage.success('交付批次已取消，下游历史已保留。')
  } catch (error) { handleMutationError(error) } finally { actionLoading.value = false }
}
async function completeOrder(exceptionClose: boolean) {
  if (actionLoading.value || !order.value) return
  const reason = exceptionClose ? completeForm.reason.trim() : completeForm.note.trim()
  if (exceptionClose && !reason) return ElMessage.warning('异常关闭原因不能为空。')
  actionLoading.value = true
  try {
    const result = await completeSalesOrder(order.value.id, exceptionClose, reason, etag.value)
    order.value = result.data
    etag.value = result.etag
    completeVisible.value = false
    exceptionCloseVisible.value = false
    ElMessage.success(exceptionClose ? '销售订单已异常关闭，差额和原因已留痕。' : '销售订单已正常完结。')
  } catch (error) { handleMutationError(error) } finally { actionLoading.value = false }
}

async function loadProductLabels() {
  const [categories, units] = await Promise.allSettled([
    fetchAllProductionDataRecords<ProductCategory>('product-categories'),
    fetchAllProductionDataRecords<ProductionUnit>('production-units'),
  ])
  productCategories.value = categories.status === 'fulfilled' ? categories.value : []
  productUnits.value = units.status === 'fulfilled' ? units.value : []
  productCatalogError.value = categories.status === 'rejected' || units.status === 'rejected'
    ? '类别或单位名称加载失败，其他产品信息仍按订单保存内容显示。请刷新重试。' : ''
}
onMounted(() => {
  void loadProductLabels()
  void load()
})
</script>

<template>
  <section class="sales-detail-page">
    <div v-if="pageState === 'loading'" class="state-page"><div class="loading-mark" /><h2>正在加载销售订单</h2><p>正在读取订单、批次和协同记录，请稍候。</p></div>
    <div v-else-if="pageState === 'forbidden'" class="state-page"><span class="state-code">403</span><h2>没有权限查看此销售订单</h2><p>页面不会显示上一次打开的订单数据，请联系管理员检查数据范围。</p><el-button @click="router.push({ name: 'sales-orders' })">返回销售订单</el-button></div>
    <div v-else-if="pageState === 'error'" class="state-page"><span class="state-code">!</span><h2>销售订单加载失败</h2><p>{{ errorMessage }}</p><el-button type="primary" @click="load">重新加载</el-button></div>

    <template v-else-if="order">
      <header class="detail-heading">
        <div><div class="title-line"><h1>{{ order.order_number }}</h1><span class="status-tag" :class="statusClass(order.status)">{{ order.status_display }}</span><span class="status-tag is-neutral">V{{ order.version_number }}</span></div><p>来源：{{ order.source_quotation_number ? `报价 ${order.source_quotation_number}` : order.source_type_display }}　|　客户确认：{{ order.customer_confirmer || '未登记' }} · {{ order.confirmation_method_display || '—' }} · {{ formatDateTime(order.customer_confirmed_at) }}</p></div>
        <div class="heading-actions"><el-button @click="router.push({ name: 'sales-orders' })">返回列表</el-button><el-button v-if="order.status === 'DRAFT' && canOrder('sales_orders.change_salesorder')" @click="router.push({ name: 'sales-order-edit', params: { orderId: order.id } })">编辑草稿</el-button><el-button v-if="['CONFIRMED', 'FULFILLING', 'PAUSED'].includes(order.status) && canOrder('access_control.confirmedchange_salesorder')" @click="router.push({ name: 'sales-order-edit', params: { orderId: order.id } })">订单变更</el-button><el-button v-if="order.status === 'DRAFT' && canOrder('access_control.confirm_salesorder')" type="primary" @click="confirmVisible = true">确认订单</el-button><el-button v-if="canOrder('access_control.collaborate_salesorder')" :type="order.status === 'DRAFT' ? 'default' : 'primary'" @click="openCollaboration()">登记协同事项</el-button><el-dropdown v-if="canOrder('access_control.complete_salesorder') && ['CONFIRMED', 'FULFILLING', 'PAUSED'].includes(order.status)" trigger="click"><el-button :icon="MoreFilled">更多</el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-if="['CONFIRMED', 'FULFILLING'].includes(order.status)" @click="completeVisible = true">正常完结</el-dropdown-item><el-dropdown-item divided @click="exceptionCloseVisible = true">异常关闭</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
      </header>

      <nav class="detail-tabs" aria-label="销售订单详情页签"><button v-for="tab in [['information','订单信息'],['products','产品与价格'],['batches','交付批次'],['evidence','客户凭证'],['versions','版本记录'],['timeline','协同时间线']]" :key="tab[0]" type="button" :class="{ active: activeTab === tab[0] }" @click="activeTab = tab[0]">{{ tab[1] }}</button></nav>
      <div class="detail-layout">
        <main class="detail-content">
          <template v-if="activeTab === 'information'">
            <section class="content-card"><h2>基本信息</h2><dl class="info-grid"><dt>订单编号</dt><dd>{{ order.order_number }}</dd><dt>客户名称</dt><dd>{{ order.customer_name }}</dd><dt>买方地址快照</dt><dd>{{ addressText() }}</dd><dt>订单日期</dt><dd>{{ order.order_date }}</dd><dt>联系人</dt><dd>{{ order.customer_confirmer || '—' }}</dd><dt>业务员</dt><dd>{{ order.salesperson.display_name }}</dd><dt>订单状态</dt><dd><span class="status-tag" :class="statusClass(order.status)">{{ order.status_display }}</span></dd><dt>确认方式</dt><dd>{{ order.confirmation_method_display || '—' }}</dd><dt>交易币种</dt><dd>{{ order.currency_code }}</dd><dt>来源报价</dt><dd>{{ order.source_quotation_number || '—' }}</dd><dt>确认时间</dt><dd>{{ formatDateTime(order.customer_confirmed_at) }}</dd><dt>备注</dt><dd>{{ order.confirmation_summary || '—' }}</dd></dl></section>
            <section class="content-card"><h2>产品与价格 · 共{{ order.lines.length }}个产品</h2><SalesOrderProductsTable :order="order" :categories="productCategories" :units="productUnits" :catalog-error="productCatalogError"/></section>
            <section class="content-card"><h2>交付批次 · 共{{ activeBatches.length }}个批次</h2><el-table :data="activeBatches"><el-table-column prop="batch_number" label="批次" width="100"/><el-table-column prop="planned_delivery_date" label="计划交期" width="180"/><el-table-column label="产品" min-width="300"><template #default="{ row }">{{ row.lines.map((line: SalesOrderBatchLine) => line.product_name).join(' / ') }}</template></el-table-column><el-table-column label="数量" width="160"><template #default="{ row }">{{ row.lines.map((line: SalesOrderBatchLine) => numberText(line.quantity)).join(' / ') }}</template></el-table-column><el-table-column label="生产状态" width="160"><template #default="{ row }"><span class="status-tag is-warning">{{ row.production_summary.status_display || '尚未建立' }}</span></template></el-table-column><el-table-column label="操作" width="220"><template #default="{ row }"><el-button v-if="canCreateProductionTask && batchHasProductionCapacity(row)" size="small" @click="openProduction(row)">创建生产任务单</el-button><span v-else-if="!canCreateProductionTask" class="muted">当前状态或权限不可建立</span><span v-else class="muted">无剩余可建数量</span></template></el-table-column></el-table></section>
          </template>
          <section v-else-if="activeTab === 'products'" class="content-card products-panel"><h2>产品与价格</h2><SalesOrderProductsTable :order="order" :categories="productCategories" :units="productUnits" :catalog-error="productCatalogError"/><h2 class="subheading">产品要求</h2><article v-for="line in order.lines" :key="line.id" class="requirement-row"><strong>{{ line.customer_product_name_snapshot || line.product_name_snapshot }}<template v-if="line.product_number_snapshot"> / {{ line.product_number_snapshot }}</template></strong><p><b>品质要求：</b>{{ line.quality_requirements || '—' }}</p><p><b>包装要求：</b>{{ line.packaging_requirements || '—' }}</p><p><b>唛头要求：</b>{{ line.shipping_mark_requirements || '—' }}</p><p><b>价格备注：</b>{{ line.lower_price_reason || '—' }}</p></article></section>
          <section v-else-if="activeTab === 'batches'" class="content-card"><div class="section-heading"><h2>交付批次协同</h2><span>选择批次后进入生产任务单创建页</span></div><article v-for="batch in order.delivery_batches" :key="batch.id" class="detail-batch" :class="{ cancelled: batch.status === 'CANCELLED' }"><header><div><strong>{{ batch.batch_number }}</strong><span>{{ batch.planned_delivery_date }}</span></div><span class="status-tag" :class="batch.status === 'ACTIVE' ? 'is-success' : 'is-danger'">{{ batch.status_display }}</span></header><el-table :data="batch.lines"><el-table-column label="产品" min-width="240"><template #default="{ row }">{{ row.product_name }}<div class="muted">{{ row.product_number }}</div></template></el-table-column><el-table-column label="本批数量" width="130"><template #default="{ row }">{{ numberText(row.quantity) }}</template></el-table-column><el-table-column label="已建生产" width="130"><template #default="{ row }">{{ numberText(row.allocated_quantity) }}</template></el-table-column><el-table-column label="可建数量" width="130"><template #default="{ row }">{{ numberText(row.remaining_quantity) }}</template></el-table-column><el-table-column label="操作" width="210"><template #default="{ row }"><el-button v-if="batch.status === 'ACTIVE' && canCreateProductionTask && Number(row.remaining_quantity) > 0" size="small" @click="openProduction(batch, row)">创建生产任务单</el-button></template></el-table-column></el-table><footer><span>{{ batch.notes || '无批次备注' }}</span><div><el-button v-if="batch.status === 'ACTIVE'" size="small" @click="openCollaboration(batch.id)">登记协同</el-button><el-button v-if="batch.status === 'ACTIVE' && canCancelBatch" size="small" type="danger" plain @click="openCancelBatch(batch)">取消批次</el-button></div></footer></article></section>
          <section v-else-if="activeTab === 'evidence'" class="content-card"><div class="section-heading"><h2>客户确认凭证</h2><label class="upload-button"><input type="file" :disabled="actionLoading" @change="uploadEvidence"><el-icon><UploadFilled/></el-icon>上传凭证</label></div><div v-if="!order.evidence.length" class="empty-state"><h3>尚未上传客户确认凭证</h3><p>无报价或返单必须先保存草稿，在此上传客户书面凭证后才能确认。</p></div><el-table v-else :data="order.evidence"><el-table-column prop="file_name" label="文件名" min-width="300"/><el-table-column prop="evidence_type" label="凭证类型" width="180"/><el-table-column prop="caption" label="说明" min-width="260"/><el-table-column label="操作" width="120"><template #default="{ row }"><a class="text-link" :href="salesOrderEvidenceUrl(order.id, row.file_id)" target="_blank" rel="noopener">查看文件</a></template></el-table-column></el-table></section>
          <section v-else-if="activeTab === 'versions'" class="content-card"><h2>订单版本记录</h2><el-table :data="order.versions"><el-table-column label="版本" width="100"><template #default="{ row }"><span class="status-tag is-neutral">V{{ row.version_number }}</span></template></el-table-column><el-table-column prop="change_reason" label="变更原因" min-width="360"/><el-table-column label="确认人" width="180"><template #default="{ row }">{{ row.confirmed_by?.display_name || '—' }}</template></el-table-column><el-table-column label="确认时间" width="220"><template #default="{ row }">{{ formatDateTime(row.confirmed_at) }}</template></el-table-column></el-table></section>
          <section v-else class="content-card"><h2>协同时间线</h2><div v-if="!order.collaboration_events.length" class="empty-state"><h3>暂无协同记录</h3><p>订金、合同、产前样、验货、订舱、发货、余款和单证将在这里留痕。</p></div><ol v-else class="timeline"><li v-for="item in order.collaboration_events" :key="item.id"><span class="timeline-dot"/><div><header><strong>{{ item.event_type_display }} · {{ item.title }}</strong><span class="status-tag" :class="statusClass(item.status)">{{ item.status_display }}</span></header><p>{{ item.note || '无补充说明' }}</p><small>{{ formatDateTime(item.occurred_at) }} · {{ item.recorded_by?.display_name || '系统' }}<template v-if="item.quantity"> · 数量 {{ numberText(item.quantity) }}</template></small></div></li></ol></section>
        </main>
        <aside class="detail-aside"><section class="summary-card"><h2>订单概览</h2><dl><dt>订单总额 ({{ order.currency_code }})</dt><dd class="amount">{{ Number(order.total_amount).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</dd><dt>人民币总额 (CNY)</dt><dd>{{ order.total_amount_cny == null ? '—' : numberText(order.total_amount_cny) }}</dd><dt>系统汇率</dt><dd>{{ order.exchange_rate_snapshot?.rate || '—' }}<small v-if="order.exchange_rate_snapshot"> · {{ order.exchange_rate_snapshot.source_name }} · {{ order.exchange_rate_snapshot.effective_date }}</small></dd><dt>客户名称</dt><dd>{{ order.customer_name }}</dd><dt>联系人</dt><dd>{{ order.customer_confirmer || '—' }}</dd><dt>买方主体</dt><dd>{{ order.transaction_entity_name || '—' }}</dd><dt>买方地址</dt><dd>{{ addressText() }}</dd><dt>卖方主体</dt><dd>{{ sellerText('seller_company_name') || sellerText('legal_name') || '—' }}</dd><dt>业务员</dt><dd>{{ order.salesperson.display_name }}</dd><dt>订单日期</dt><dd>{{ order.order_date }}</dd><dt>订单状态</dt><dd><span class="status-tag" :class="statusClass(order.status)">{{ order.status_display }}</span></dd><dt>版本</dt><dd><span class="status-tag is-neutral">V{{ order.version_number }}</span></dd><dt>来源报价</dt><dd>{{ order.source_quotation_number || '—' }}</dd><dt>确认方式</dt><dd>{{ order.confirmation_method_display || '—' }}</dd><dt>客户确认时间</dt><dd>{{ formatDateTime(order.customer_confirmed_at) }}</dd></dl></section><section class="summary-card"><h2>协同时间线</h2><p v-for="item in order.collaboration_events.slice(0, 3)" :key="item.id" class="aside-event"><span>{{ item.title }}</span><small>{{ formatDateTime(item.occurred_at) }}</small></p><p v-if="!order.collaboration_events.length" class="muted">暂无协同记录</p></section><section class="summary-card"><h2>相关凭证</h2><p v-for="file in order.evidence.slice(0, 3)" :key="file.id" class="aside-event"><span>{{ file.file_name }}</span></p><p v-if="!order.evidence.length" class="muted">暂无客户凭证</p></section></aside>
      </div>
    </template>

    <AppWindowDialog v-model="confirmVisible" title="确认销售订单" :width="900" :height="700" class="sales-order-dialog" :close-on-click-modal="false">
      <p class="dialog-lead">确认后订单进入正式履约，后续修改必须通过订单变更生成新版本。</p>
      <div class="dialog-columns confirm-layout">
        <section><h3>订单摘要</h3><dl class="dialog-dl"><dt>订单编号</dt><dd>{{ order?.order_number }}</dd><dt>客户</dt><dd>{{ order?.customer_name }}</dd><dt>订单金额</dt><dd>{{ order?.currency_code }} {{ numberText(order?.total_amount || 0) }}</dd><dt>产品 / 批次</dt><dd>{{ order?.lines.length || 0 }} 种 / {{ activeBatches.length }} 批</dd><dt>买方地址</dt><dd>{{ addressText() }}</dd></dl></section>
        <section><h3>批次数量核对</h3><table class="mini-table"><thead><tr><th>产品</th><th>订单数量</th><th>已分配</th></tr></thead><tbody><tr v-for="item in confirmAllocations" :key="item.id"><td>{{ item.product }}</td><td>{{ numberText(item.ordered) }}</td><td>{{ numberText(item.allocated) }}</td></tr></tbody></table></section>
      </div>
      <section class="check-list"><div v-for="item in confirmChecks" :key="item.label" :class="{ passed: item.passed }"><span>{{ item.passed ? '✓' : '!' }}</span>{{ item.label }}</div></section>
      <template #footer><el-button @click="confirmVisible = false">取消</el-button><el-button type="primary" :disabled="!canConfirm" :loading="actionLoading" @click="confirmOrder">确认订单</el-button></template>
    </AppWindowDialog>
    <AppWindowDialog v-model="blockedVisible" title="确认前缺失信息" :width="700" :height="340" class="sales-order-dialog"><div class="blocked-copy"><span>!</span><div><h3>买方地址尚未满足确认条件</h3><p>草稿仍已保留。请到编辑页选择当前客户名下的有效法定交易地址，再重新确认。</p></div></div><template #footer><el-button @click="blockedVisible = false">暂不处理</el-button><el-button type="primary" @click="router.push({ name: 'sales-order-edit', params: { orderId }, query: { section: 'buyer-address' } })">去补充买方地址</el-button></template></AppWindowDialog>
    <AppWindowDialog v-model="collaborationVisible" :title="collaborationForm.event_type === 'SHIPMENT' ? '登记协同 · 发货' : '登记订单协同事项'" :width="840" :height="720" class="sales-order-dialog" :close-on-click-modal="false"><div class="dialog-columns"><section><h3>事项分类</h3><label>协同类型</label><el-select v-model="collaborationForm.event_type"><el-option v-for="item in eventTypes" :key="item[0]" :value="item[0]" :label="item[1]"/></el-select><label>关联批次</label><el-select v-model="collaborationForm.delivery_batch_id" clearable><el-option v-for="batch in activeBatches" :key="batch.id" :value="batch.id" :label="`${batch.batch_number} · ${batch.planned_delivery_date}`"/></el-select><label>事项状态</label><el-select v-model="collaborationForm.status"><el-option value="PENDING" label="待处理"/><el-option value="COMPLETED" label="完成"/><el-option value="RISK" label="风险"/><el-option value="CANCELLED" label="取消"/></el-select></section><section><h3>记录内容</h3><label>事项标题</label><el-input v-model="collaborationForm.title" maxlength="200"/><label>发生时间</label><el-date-picker v-model="collaborationForm.occurred_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ"/><template v-if="collaborationForm.event_type === 'SHIPMENT'"><label>本次发货数量</label><el-input-number v-model="collaborationForm.quantity" :min="0.0001" :precision="4" :controls="false"/></template><label>补充说明</label><el-input v-model="collaborationForm.note" type="textarea" :rows="3" maxlength="1000"/></section></div><section class="dialog-preview"><h3>记录内容预览</h3><dl class="dialog-dl"><dt>关联订单</dt><dd>{{ order?.order_number }}</dd><dt>协同事项</dt><dd>{{ eventTypes.find((item) => item[0] === collaborationForm.event_type)?.[1] }} · {{ collaborationForm.status === 'COMPLETED' ? '完成' : collaborationForm.status === 'RISK' ? '风险' : collaborationForm.status === 'CANCELLED' ? '取消' : '待处理' }}</dd><dt>事项标题</dt><dd>{{ collaborationForm.title || '尚未填写' }}</dd></dl></section><template #footer><el-button @click="collaborationVisible = false">取消</el-button><el-button type="primary" :loading="actionLoading" @click="addEvent">保存协同记录</el-button></template></AppWindowDialog>
    <AppWindowDialog v-model="cancelBatchVisible" title="取消正式交付批次" :width="900" :height="720" class="sales-order-dialog" :close-on-click-modal="false"><p class="dialog-lead danger">取消后保留已建立的生产与协同历史，批次差额和取消原因继续留痕。</p><div class="dialog-columns"><section><h3>批次影响</h3><dl class="dialog-dl"><dt>交付批次</dt><dd>{{ selectedBatch?.batch_number }}</dd><dt>计划交期</dt><dd>{{ selectedBatch?.planned_delivery_date }}</dd><dt>需求数量</dt><dd>{{ numberText(selectedBatch?.lines.reduce((sum, line) => sum + Number(line.quantity), 0) || 0) }}</dd></dl><table class="mini-table"><thead><tr><th>产品</th><th>数量</th></tr></thead><tbody><tr v-for="line in selectedBatch?.lines || []" :key="line.id"><td>{{ line.product_name }}</td><td>{{ numberText(line.quantity) }}</td></tr></tbody></table></section><section><h3>客户确认</h3><label>本订单客户凭证</label><el-select v-model="cancelForm.evidence_file_id"><el-option v-for="file in order?.evidence || []" :key="file.file_id" :value="file.file_id" :label="file.file_name"/></el-select><label>取消原因</label><el-input v-model="cancelForm.reason" type="textarea" :rows="6" maxlength="1000"/><p class="muted">客户确认凭证和取消原因将写入新版本历史。</p></section></div><template #footer><el-button @click="cancelBatchVisible = false">取消</el-button><el-button type="danger" :loading="actionLoading" @click="cancelBatch">确认取消批次</el-button></template></AppWindowDialog>
    <AppWindowDialog v-model="completeVisible" title="正常完结销售订单" :width="820" :height="620" class="sales-order-dialog" :close-on-click-modal="false"><span class="completion-state" :class="normalCompletionReady ? 'ready' : 'blocked'">{{ normalCompletionReady ? '条件满足' : '尚有缺口' }}</span><div class="dialog-columns completion-grid"><section><h3>交付检查</h3><dl class="dialog-dl"><dt>有效需求</dt><dd>{{ numberText(activeDemand) }}</dd><dt>累计发货</dt><dd>{{ numberText(completedShipment) }}</dd><dt>尚未交付</dt><dd>{{ numberText(remainingShipment) }}</dd></dl></section><section><h3>余款检查</h3><span class="status-tag" :class="balanceCompleted ? 'is-success' : 'is-warning'">{{ balanceCompleted ? '已完成' : '未完成' }}</span><p class="muted">余款协同事项需标记为完成；单证事项仅作提醒。</p></section></div><label>完结说明（选填）</label><el-input v-model="completeForm.note" type="textarea" :rows="3" maxlength="1000"/><p class="dialog-lead">说明可以填写，但不会因此变成异常关闭；最终仍由服务端复核交付和余款条件。</p><template #footer><el-button @click="completeVisible = false">取消</el-button><el-button type="primary" :loading="actionLoading" @click="completeOrder(false)">检查并正常完结</el-button></template></AppWindowDialog>
    <AppWindowDialog v-model="exceptionCloseVisible" title="异常关闭销售订单" :width="820" :height="620" class="sales-order-dialog" :close-on-click-modal="false"><div class="dialog-columns completion-grid"><section><h3>履约差额核对</h3><dl class="dialog-dl"><dt>有效需求</dt><dd>{{ numberText(activeDemand) }}</dd><dt>累计发货</dt><dd>{{ numberText(completedShipment) }}</dd><dt>尚未交付</dt><dd>{{ numberText(remainingShipment) }}</dd><dt>余款事项</dt><dd>{{ balanceCompleted ? '已完成' : '未完成' }}</dd></dl></section><section><p class="dialog-lead danger">异常关闭不表示交付或收款完成，未完成差额会保留在历史记录中。</p><label>异常关闭原因</label><el-input v-model="completeForm.reason" type="textarea" :rows="6" maxlength="1000"/></section></div><template #footer><el-button @click="exceptionCloseVisible = false">返回继续履约</el-button><el-button type="danger" :loading="actionLoading" @click="completeOrder(true)">确认异常关闭</el-button></template></AppWindowDialog>
    <AppWindowDialog v-model="conflictVisible" title="订单已被其他人更新" :width="680" :height="280" class="sales-order-dialog"><p class="dialog-lead danger">系统没有覆盖对方的修改。本次输入仍保留在当前弹窗，请先查看最新订单再决定如何处理。</p><template #footer><el-button @click="conflictVisible = false">保留当前输入</el-button><el-button type="primary" @click="conflictVisible = false; load()">查看最新记录</el-button></template></AppWindowDialog>
  </section>
</template>

<style lang="scss" scoped>
@use '@/styles/theme/detail' as detail;.sales-detail-page{height:auto;min-width:0;overflow:visible;padding:0;background:transparent;color:var(--erp-color-text-primary);font-family:var(--erp-font-body);font-size:13px;line-height:20px}.detail-heading{display:flex;min-height:0;align-items:flex-start;justify-content:space-between;gap:14px;flex-wrap:wrap;margin-bottom:14px}.title-line{display:flex;align-items:center;gap:14px;flex-wrap:wrap;min-width:0}.title-line h1{margin:0;font-family:var(--erp-font-body);font-size:36px;font-weight:700;line-height:44px;overflow-wrap:anywhere}.detail-heading p{margin:8px 0 0;color:var(--erp-color-text-regular);font-size:13px}.heading-actions{display:flex;align-items:center;gap:8px;margin-top:0;flex-wrap:wrap}.heading-actions .el-button{height:32px;margin:0;border-radius:8px}.heading-actions>.el-button{min-width:110px}.heading-actions>.el-button--primary{width:140px;border-color:var(--erp-button-primary-border);background:var(--erp-button-primary-surface)}.detail-tabs{display:flex;height:auto;align-items:flex-start;gap:8px;min-height:32px;flex-wrap:wrap;margin-bottom:14px}.detail-tabs button{height:32px;padding:0 10px;border:0;color:var(--erp-color-text-regular);background:transparent;font-size:13px;cursor:pointer;position:relative}.detail-tabs button.active{color:var(--erp-color-brand)}.detail-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(280px, 28%);align-items:start;gap:14px}.detail-content{display:grid;gap:14px;min-width:0}.content-card,.summary-card{@include detail.surface;padding:16px}.content-card h2,.summary-card h2{margin:0;font-size:16px;line-height:24px;font-family:var(--erp-font-body)}.content-card>h2{margin-bottom:12px}.info-grid{display:grid;grid-template-columns:repeat(3, minmax(84px, auto) minmax(0, 1fr));margin:0;gap:10px 12px;font-size:13px}.info-grid dt,.summary-card dt{color:var(--erp-color-text-regular)}.info-grid dd,.summary-card dd{min-width:0;margin:0;overflow-wrap:anywhere}.content-card :deep(.el-table){--el-table-border-color:var(--erp-table-border);--el-table-header-bg-color:var(--erp-table-background);color:var(--erp-table-text)}.content-card :deep(.el-table__header th.el-table__cell){height:38px;background:var(--erp-table-header-background);color:var(--erp-table-text);font-weight:500}.content-card :deep(.el-table__inner-wrapper::before){display:none}.muted{margin-top:3px;color:var(--erp-color-text-regular);font-size:12px}.detail-aside{display:grid;gap:14px;position:sticky;top:0;min-width:0}.summary-card h2{margin-bottom:12px;padding:0;background:transparent}.summary-card dl{display:grid;grid-template-columns:minmax(84px, auto) minmax(0, 1fr);margin:0;gap:8px 10px;font-size:13px}.summary-card .amount{grid-column:1/-1;margin-bottom:4px;padding-bottom:12px;border-bottom:1px solid var(--erp-color-border);font-size:30px}.aside-event{display:flex;justify-content:space-between;margin:8px 0;font-size:13px}.aside-event small{color:var(--erp-color-text-regular)}.status-tag{display:inline-flex;min-width:56px;height:24px;align-items:center;justify-content:center;padding:0 8px;border-radius:999px;color:var(--erp-tag-neutral-text);font-size:12px;font-weight:500;line-height:18px}.status-tag.is-neutral{background:var(--erp-tag-neutral-background)}.status-tag.is-success{background:var(--erp-tag-success-background)}.status-tag.is-info{background:var(--erp-tag-info-background)}.status-tag.is-warning{background:var(--erp-tag-warning-background)}.status-tag.is-danger{background:var(--erp-tag-danger-background)}.section-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}.section-heading>span{color:var(--erp-color-text-regular);font-size:13px}.subheading{margin-top:18px!important}.requirement-row{display:grid;grid-template-columns:minmax(150px,1.4fr) repeat(4,minmax(0,1fr));gap:14px;padding:14px 8px;border-top:1px solid var(--erp-color-border);font-size:13px}.requirement-row p{margin:0;line-height:20px}.detail-batch{@include detail.inset;margin-top:14px;overflow:hidden}.detail-batch.cancelled{opacity:.68}.detail-batch>header,.detail-batch>footer{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;flex-wrap:wrap;gap:10px}.detail-batch>header{background:var(--erp-color-subtle)}.detail-batch>header>div{display:flex;gap:10px 22px;flex-wrap:wrap}.detail-batch>footer{color:var(--erp-color-text-regular);font-size:13px}.detail-batch>footer .el-button{margin-left:8px}.empty-state{padding:80px 20px;text-align:center}.empty-state h3{margin:0 0 8px}.empty-state p{color:var(--erp-color-text-regular)}.upload-button{display:inline-flex;height:32px;align-items:center;gap:7px;padding:0 16px;border-radius:8px;color:var(--erp-button-primary-text);background:var(--erp-button-primary-surface);cursor:pointer}.upload-button input{display:none}.text-link{color:var(--erp-color-brand);text-decoration:none}.timeline{margin:0;padding:4px 0;list-style:none}.timeline li{display:grid;grid-template-columns:22px 1fr;gap:10px;position:relative;padding-bottom:24px}.timeline li::before{position:absolute;top:18px;bottom:0;left:6px;width:1px;background:var(--erp-color-border);content:''}.timeline li:last-child::before{display:none}.timeline-dot{width:13px;height:13px;margin-top:4px;border:3px solid var(--erp-color-danger-border);border-radius:50%;background:var(--erp-color-brand)}.timeline header{display:flex;align-items:center;justify-content:space-between}.timeline p{margin:6px 0;color:var(--erp-color-text-primary)}.timeline small{color:var(--erp-color-text-regular)}.state-page{display:flex;height:100%;align-items:center;justify-content:center;flex-direction:column;text-align:center}.state-page h2{margin:18px 0 8px}.state-page p{max-width:520px;margin:0 0 22px;color:var(--erp-color-text-regular)}.state-code{font-family:var(--erp-font-body);font-size:64px;color:var(--erp-color-brand)}.loading-mark{width:44px;height:44px;border:3px solid var(--erp-color-border);border-top-color:var(--erp-color-brand);border-radius:50%;animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.sales-detail-page :deep(.sales-order-dialog .el-dialog__header){margin:0;padding:24px 28px 18px;border-bottom:1px solid var(--erp-color-border)}.sales-detail-page :deep(.sales-order-dialog .el-dialog__title){font-family:var(--erp-font-body);font-size:24px;font-weight:600}.sales-detail-page :deep(.sales-order-dialog .el-dialog__body){display:grid;gap:10px;padding:22px 28px}.sales-detail-page :deep(.sales-order-dialog .el-dialog__footer){padding:16px 28px 24px}.sales-detail-page :deep(.sales-order-dialog .el-input__wrapper),.sales-detail-page :deep(.sales-order-dialog .el-select__wrapper){min-height:38px;border-radius:4px}.sales-detail-page :deep(.sales-order-dialog .el-button){height:32px;border-radius:4px}.sales-detail-page :deep(.sales-order-dialog .el-button--primary){border-color:var(--erp-button-primary-border);background:var(--erp-button-primary-surface)}.dialog-lead{margin:0;padding:12px 14px;border-radius:8px;background:var(--erp-color-subtle);color:var(--erp-color-text-regular);line-height:22px}.dialog-lead.danger{color:var(--erp-color-danger);background:var(--erp-color-danger-soft)}.check-list{display:grid;gap:8px}.check-list div{display:flex;align-items:center;gap:10px;padding:10px 12px;color:var(--erp-color-brand);background:var(--erp-color-subtle);border-radius:8px}.check-list div.passed{color:var(--erp-color-success);background:var(--erp-color-subtle)}.check-list span{display:inline-flex;width:22px;height:22px;align-items:center;justify-content:center;border-radius:50%;color:var(--erp-color-text-inverse);background:currentColor}.blocked-copy{display:flex;gap:14px}.blocked-copy>span{display:flex;width:38px;height:38px;align-items:center;justify-content:center;border-radius:50%;color:var(--erp-color-text-inverse);background:var(--erp-color-brand);font-size:22px}.blocked-copy h3{margin:0 0 8px}.blocked-copy p{margin:0;color:var(--erp-color-text-regular)}.dialog-columns{display:grid;grid-template-columns:1fr 1fr;gap:20px}.dialog-columns section{@include detail.inset;display:grid;align-content:start;gap:9px;padding:14px}.dialog-columns h3{margin:0 0 4px;font-size:17px}.dialog-columns label,.sales-order-dialog>label{margin-top:4px;color:var(--erp-color-text-regular);font-size:13px}.dialog-dl{display:grid;grid-template-columns:110px 1fr;margin:0;gap:10px}.dialog-dl dt{color:var(--erp-color-text-regular)}.dialog-dl dd{margin:0}.production-layout{grid-template-columns:.9fr 1.1fr}.production-layout .field-pair{display:grid;grid-template-columns:1fr 1fr;gap:10px}.production-layout .field-pair label{display:grid;gap:6px}.production-layout :deep(.el-date-editor){width:100%}.confirm-layout{margin:2px 0}.mini-table{width:100%;border-collapse:collapse;font-size:13px}.mini-table th,.mini-table td{padding:8px;border-bottom:1px solid var(--erp-table-border);text-align:left}.mini-table th{color:var(--erp-table-text);background:var(--erp-table-header-background);font-weight:500}.dialog-preview{@include detail.inset;padding:14px}.dialog-preview h3{margin:0 0 10px;font-size:17px}.completion-grid section{min-height:128px}.completion-state{display:inline-flex;width:max-content;padding:4px 10px;border-radius:999px;color:var(--erp-color-text-inverse);font-size:12px}.completion-state.ready{background:var(--erp-color-success)}.completion-state.blocked{background:var(--erp-color-warning)}.detail-tabs button.active::after { content:""; position:absolute; left:4px; right:4px; bottom:0; height:3px; border-radius:4px 4px 1px 1px; background:var(--erp-tab-active-indicator); }@media (max-width:1280px) { .detail-layout { grid-template-columns:minmax(0,1fr); } .detail-aside { position:static; grid-template-columns:repeat(3,minmax(0,1fr)); } .summary-card dl { grid-template-columns:minmax(0,1fr); gap:4px; } .summary-card dd { margin-bottom:8px; } }@media (max-width:800px) { .detail-aside { grid-template-columns:minmax(0,1fr); } .info-grid { grid-template-columns:minmax(90px,auto) minmax(0,1fr); } .requirement-row { grid-template-columns:repeat(2,minmax(0,1fr)); } .dialog-columns { grid-template-columns:minmax(0,1fr); } }
</style>
