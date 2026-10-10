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
import { createProductionOrderFromSalesOrder, submitProductionTask } from '@/api/productionTasks'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { SalesOrder, SalesOrderBatchLine, SalesOrderDeliveryBatch } from '@/types/salesOrder'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const canOrder = (code: string) => !authStore.user?.sales_access_enabled || authStore.canFor(code, order.value)
const orderId = computed(() => String(route.params.orderId || ''))
const order = ref<SalesOrder | null>(null)
const etag = ref('')
const pageState = ref<'loading' | 'ready' | 'error' | 'forbidden'>('loading')
const errorMessage = ref('')
const actionLoading = ref(false)
const activeTab = ref('information')
const confirmVisible = ref(false)
const blockedVisible = ref(false)
const conflictVisible = ref(false)
const productionVisible = ref(false)
const collaborationVisible = ref(false)
const cancelBatchVisible = ref(false)
const completeVisible = ref(false)
const exceptionCloseVisible = ref(false)
const selectedBatch = ref<SalesOrderDeliveryBatch | null>(null)
const productionForm = reactive({
  delivery_batch_line_id: '', quantity: 1, request_key: '', planned_start_date: '', planned_end_date: '',
  production_priority: 'NORMAL' as 'URGENT' | 'HIGH' | 'NORMAL' | 'LOW', production_batch_number: '', planner_id: null as string | null,
})
const productionRequestSignature = ref('')
const productionAttempted = ref(false)
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
const productionLine = computed(() => selectedBatch.value?.lines.find((line) => line.id === productionForm.delivery_batch_line_id) || null)
const batchHasProductionCapacity = (batch: SalesOrderDeliveryBatch) => batch.lines.some((line) => Math.floor(Number(line.remaining_quantity)) >= 1)
const productionPlanners = computed(() => {
  const people = [order.value?.merchandiser, order.value?.salesperson]
    .filter((item): item is NonNullable<typeof item> => Boolean(item))
  return people.filter((item, index, values) => values.findIndex((value) => value.id === item.id) === index)
})
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
  productionVisible.value = false
  collaborationVisible.value = false
  cancelBatchVisible.value = false
  completeVisible.value = false
  exceptionCloseVisible.value = false
  selectedBatch.value = null
  productionRequestSignature.value = ''
  productionAttempted.value = false
  Object.assign(productionForm, { delivery_batch_line_id: '', quantity: 1, request_key: '', planned_start_date: '', planned_end_date: '', production_priority: 'NORMAL', production_batch_number: '', planner_id: null })
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
  const targetLine = line && Math.floor(Number(line.remaining_quantity)) >= 1
    ? line
    : batch.lines.find((item) => Math.floor(Number(item.remaining_quantity)) >= 1) || null
  if (!targetLine) {
    ElMessage.warning('该批次产品已全部建立生产任务，无剩余可建数量。')
    return
  }
  selectedBatch.value = batch
  productionForm.delivery_batch_line_id = targetLine.id
  productionForm.quantity = Math.floor(Number(targetLine.remaining_quantity))
  productionForm.request_key = crypto.randomUUID()
  productionForm.planned_start_date = new Date().toISOString().slice(0, 10)
  productionForm.planned_end_date = batch.planned_delivery_date
  productionForm.production_priority = 'NORMAL'
  productionForm.production_batch_number = `PB-${batch.planned_delivery_date.replaceAll('-', '')}-${batch.batch_number}`
  productionForm.planner_id = order.value?.merchandiser?.id || order.value?.salesperson.id || null
  productionRequestSignature.value = ''
  productionAttempted.value = false
  productionVisible.value = true
}
function syncProductionQuantity() {
  const remaining = Math.floor(Number(productionLine.value?.remaining_quantity || 0))
  productionForm.quantity = remaining >= 1 ? Math.min(Math.max(Math.floor(Number(productionForm.quantity || 1)), 1), remaining) : 0
}
async function submitProduction() {
  if (actionLoading.value) return
  const remaining = Math.floor(Number(productionLine.value?.remaining_quantity || 0))
  if (!productionLine.value || !Number.isInteger(productionForm.quantity) || productionForm.quantity < 1 || productionForm.quantity > remaining) return ElMessage.warning('生产数量必须是整数，且不能超过可建数量。')
  const signature = `${productionForm.delivery_batch_line_id}|${productionForm.quantity}`
  if (productionRequestSignature.value !== signature) {
    productionForm.request_key = crypto.randomUUID()
    productionRequestSignature.value = signature
  }
  productionAttempted.value = true
  actionLoading.value = true
  try {
    const created = await createProductionOrderFromSalesOrder({
      request_key: productionForm.request_key,
      delivery_batch_line_id: productionLine.value.id,
      quantity: productionForm.quantity,
      planned_start_date: productionForm.planned_start_date || null,
      planned_end_date: productionForm.planned_end_date || null,
      production_priority: productionForm.production_priority,
      production_batch_number: productionForm.production_batch_number.trim(),
      planner_id: productionForm.planner_id,
    })
    try {
      await submitProductionTask(created.data.id, created.etag)
      ElMessage.success(`生产任务单 ${created.data.task_number} 已建立并提交 PMC。`)
    } catch (error) {
      ElMessage.warning(`生产任务单 ${created.data.task_number} 已保存为草稿，但提交 PMC 失败：${apiError(error)}`)
    }
    productionVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(`${apiError(error)} 已刷新订单，避免重复建立生产任务。`)
    productionVisible.value = false
    await load()
  } finally { actionLoading.value = false }
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

onMounted(load)
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
            <section class="content-card"><h2>产品与价格 · 共{{ order.lines.length }}个产品</h2><el-table :data="order.lines"><el-table-column label="产品/编码" min-width="260"><template #default="{ row }"><b>{{ row.product_name_snapshot }}</b><div class="muted">{{ row.product_number_snapshot }}</div></template></el-table-column><el-table-column label="数量" width="150"><template #default="{ row }">{{ numberText(row.quantity) }}</template></el-table-column><el-table-column prop="unit_code_snapshot" label="单位" width="100"/><el-table-column label="单价" width="160"><template #default="{ row }">{{ numberText(row.unit_price) }}</template></el-table-column><el-table-column label="金额" width="180"><template #default="{ row }">{{ numberText(row.line_total) }}</template></el-table-column><el-table-column label="金额(CNY)" width="190"><template #default="{ row }">{{ numberText(Number(row.line_total) * Number(order.exchange_rate)) }}</template></el-table-column></el-table></section>
            <section class="content-card"><h2>交付批次 · 共{{ activeBatches.length }}个批次</h2><el-table :data="activeBatches"><el-table-column prop="batch_number" label="批次" width="100"/><el-table-column prop="planned_delivery_date" label="计划交期" width="180"/><el-table-column label="产品" min-width="300"><template #default="{ row }">{{ row.lines.map((line: SalesOrderBatchLine) => line.product_name).join(' / ') }}</template></el-table-column><el-table-column label="数量" width="160"><template #default="{ row }">{{ row.lines.map((line: SalesOrderBatchLine) => numberText(line.quantity)).join(' / ') }}</template></el-table-column><el-table-column label="生产状态" width="160"><template #default="{ row }"><span class="status-tag is-warning">{{ row.production_summary.status_display || '尚未建立' }}</span></template></el-table-column><el-table-column label="操作" width="220"><template #default="{ row }"><el-button v-if="canCreateProductionTask && batchHasProductionCapacity(row)" size="small" @click="openProduction(row)">建立并提交PMC</el-button><span v-else-if="!canCreateProductionTask" class="muted">当前状态或权限不可建立</span><span v-else class="muted">无剩余可建数量</span></template></el-table-column></el-table></section>
          </template>
          <section v-else-if="activeTab === 'products'" class="content-card products-panel"><h2>产品与价格</h2><el-table :data="order.lines"><el-table-column label="产品/编码" min-width="220"><template #default="{ row }"><b>{{ row.product_name_snapshot }}</b><div class="muted">{{ row.product_number_snapshot }}</div></template></el-table-column><el-table-column label="数量" width="110"><template #default="{ row }">{{ numberText(row.quantity) }}</template></el-table-column><el-table-column label="报价单价" width="120"><template #default="{ row }">{{ row.quoted_unit_price === null ? '—' : numberText(row.quoted_unit_price) }}</template></el-table-column><el-table-column label="订单单价" width="120"><template #default="{ row }">{{ numberText(row.unit_price) }}</template></el-table-column><el-table-column label="价差" width="110"><template #default="{ row }">{{ row.quoted_unit_price === null ? '—' : numberText(row.price_difference) }}</template></el-table-column><el-table-column label="行金额" width="140"><template #default="{ row }">{{ numberText(row.line_total) }}</template></el-table-column></el-table><h2 class="subheading">产品要求</h2><article v-for="line in order.lines" :key="line.id" class="requirement-row"><strong>{{ line.product_name_snapshot }} / {{ line.product_number_snapshot }}</strong><p><b>品质要求：</b>{{ line.quality_requirements || '—' }}</p><p><b>包装要求：</b>{{ line.packaging_requirements || '—' }}</p><p><b>唛头要求：</b>{{ line.shipping_mark_requirements || '—' }}</p><p><b>价格备注：</b>{{ line.lower_price_reason || '—' }}</p></article></section>
          <section v-else-if="activeTab === 'batches'" class="content-card"><div class="section-heading"><h2>交付批次协同</h2><span>按批次中的单个产品建立生产订单</span></div><article v-for="batch in order.delivery_batches" :key="batch.id" class="detail-batch" :class="{ cancelled: batch.status === 'CANCELLED' }"><header><div><strong>{{ batch.batch_number }}</strong><span>{{ batch.planned_delivery_date }}</span></div><span class="status-tag" :class="batch.status === 'ACTIVE' ? 'is-success' : 'is-danger'">{{ batch.status_display }}</span></header><el-table :data="batch.lines"><el-table-column label="产品" min-width="240"><template #default="{ row }">{{ row.product_name }}<div class="muted">{{ row.product_number }}</div></template></el-table-column><el-table-column label="本批数量" width="130"><template #default="{ row }">{{ numberText(row.quantity) }}</template></el-table-column><el-table-column label="已建生产" width="130"><template #default="{ row }">{{ numberText(row.allocated_quantity) }}</template></el-table-column><el-table-column label="可建数量" width="130"><template #default="{ row }">{{ numberText(row.remaining_quantity) }}</template></el-table-column><el-table-column label="操作" width="210"><template #default="{ row }"><el-button v-if="batch.status === 'ACTIVE' && canCreateProductionTask && Number(row.remaining_quantity) > 0" size="small" @click="openProduction(batch, row)">建立生产订单</el-button></template></el-table-column></el-table><footer><span>{{ batch.notes || '无批次备注' }}</span><div><el-button v-if="batch.status === 'ACTIVE'" size="small" @click="openCollaboration(batch.id)">登记协同</el-button><el-button v-if="batch.status === 'ACTIVE' && canCancelBatch" size="small" type="danger" plain @click="openCancelBatch(batch)">取消批次</el-button></div></footer></article></section>
          <section v-else-if="activeTab === 'evidence'" class="content-card"><div class="section-heading"><h2>客户确认凭证</h2><label class="upload-button"><input type="file" :disabled="actionLoading" @change="uploadEvidence"><el-icon><UploadFilled/></el-icon>上传凭证</label></div><div v-if="!order.evidence.length" class="empty-state"><h3>尚未上传客户确认凭证</h3><p>无报价或返单必须先保存草稿，在此上传客户书面凭证后才能确认。</p></div><el-table v-else :data="order.evidence"><el-table-column prop="file_name" label="文件名" min-width="300"/><el-table-column prop="evidence_type" label="凭证类型" width="180"/><el-table-column prop="caption" label="说明" min-width="260"/><el-table-column label="操作" width="120"><template #default="{ row }"><a class="text-link" :href="salesOrderEvidenceUrl(order.id, row.file_id)" target="_blank" rel="noopener">查看文件</a></template></el-table-column></el-table></section>
          <section v-else-if="activeTab === 'versions'" class="content-card"><h2>订单版本记录</h2><el-table :data="order.versions"><el-table-column label="版本" width="100"><template #default="{ row }"><span class="status-tag is-neutral">V{{ row.version_number }}</span></template></el-table-column><el-table-column prop="change_reason" label="变更原因" min-width="360"/><el-table-column label="确认人" width="180"><template #default="{ row }">{{ row.confirmed_by?.display_name || '—' }}</template></el-table-column><el-table-column label="确认时间" width="220"><template #default="{ row }">{{ formatDateTime(row.confirmed_at) }}</template></el-table-column></el-table></section>
          <section v-else class="content-card"><h2>协同时间线</h2><div v-if="!order.collaboration_events.length" class="empty-state"><h3>暂无协同记录</h3><p>订金、合同、产前样、验货、订舱、发货、余款和单证将在这里留痕。</p></div><ol v-else class="timeline"><li v-for="item in order.collaboration_events" :key="item.id"><span class="timeline-dot"/><div><header><strong>{{ item.event_type_display }} · {{ item.title }}</strong><span class="status-tag" :class="statusClass(item.status)">{{ item.status_display }}</span></header><p>{{ item.note || '无补充说明' }}</p><small>{{ formatDateTime(item.occurred_at) }} · {{ item.recorded_by?.display_name || '系统' }}<template v-if="item.quantity"> · 数量 {{ numberText(item.quantity) }}</template></small></div></li></ol></section>
        </main>
        <aside class="detail-aside"><section class="summary-card"><h2>订单概览</h2><dl><dt>订单总额 ({{ order.currency_code }})</dt><dd class="amount">{{ Number(order.total_amount).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</dd><dt>客户名称</dt><dd>{{ order.customer_name }}</dd><dt>联系人</dt><dd>{{ order.customer_confirmer || '—' }}</dd><dt>买方主体</dt><dd>{{ order.transaction_entity_name || '—' }}</dd><dt>买方地址</dt><dd>{{ addressText() }}</dd><dt>卖方主体</dt><dd>{{ sellerText('seller_company_name') || sellerText('legal_name') || '—' }}</dd><dt>业务员</dt><dd>{{ order.salesperson.display_name }}</dd><dt>订单日期</dt><dd>{{ order.order_date }}</dd><dt>订单状态</dt><dd><span class="status-tag" :class="statusClass(order.status)">{{ order.status_display }}</span></dd><dt>版本</dt><dd><span class="status-tag is-neutral">V{{ order.version_number }}</span></dd><dt>来源报价</dt><dd>{{ order.source_quotation_number || '—' }}</dd><dt>确认方式</dt><dd>{{ order.confirmation_method_display || '—' }}</dd><dt>客户确认时间</dt><dd>{{ formatDateTime(order.customer_confirmed_at) }}</dd></dl></section><section class="summary-card"><h2>协同时间线</h2><p v-for="item in order.collaboration_events.slice(0, 3)" :key="item.id" class="aside-event"><span>{{ item.title }}</span><small>{{ formatDateTime(item.occurred_at) }}</small></p><p v-if="!order.collaboration_events.length" class="muted">暂无协同记录</p></section><section class="summary-card"><h2>相关凭证</h2><p v-for="file in order.evidence.slice(0, 3)" :key="file.id" class="aside-event"><span>{{ file.file_name }}</span></p><p v-if="!order.evidence.length" class="muted">暂无客户凭证</p></section></aside>
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
    <AppWindowDialog v-model="productionVisible" title="建立并提交生产订单" :width="900" :height="700" class="sales-order-dialog" :close-on-click-modal="false">
      <div class="dialog-columns production-layout">
        <section><h3>来源信息</h3><dl class="dialog-dl"><dt>销售订单</dt><dd>{{ order?.order_number }}</dd><dt>交付批次</dt><dd>{{ selectedBatch?.batch_number }}</dd><dt>计划交期</dt><dd>{{ selectedBatch?.planned_delivery_date }}</dd><dt>产品编码</dt><dd>{{ productionLine?.product_number }}</dd><dt>产品名称</dt><dd>{{ productionLine?.product_name }}</dd><dt>批次产品数量</dt><dd>{{ numberText(productionLine?.quantity || 0) }} {{ productionLine?.unit_code }}</dd></dl></section>
        <section><h3>生产计划</h3><label>产品</label><el-select v-model="productionForm.delivery_batch_line_id" :disabled="productionAttempted" @change="syncProductionQuantity"><el-option v-for="line in selectedBatch?.lines || []" :key="line.id" :value="line.id" :label="`${line.product_name} · 可建 ${numberText(line.remaining_quantity)}`" :disabled="Math.floor(Number(line.remaining_quantity)) < 1"/></el-select><label>计划数量</label><el-input-number v-model="productionForm.quantity" :disabled="productionAttempted" :min="1" :max="Math.floor(Number(productionLine?.remaining_quantity || 1))" :precision="0" :controls="false"/><label>优先级</label><el-select v-model="productionForm.production_priority" :disabled="productionAttempted"><el-option value="URGENT" label="紧急"/><el-option value="HIGH" label="高"/><el-option value="NORMAL" label="普通"/><el-option value="LOW" label="低"/></el-select><div class="field-pair"><label><span>计划开始</span><el-date-picker v-model="productionForm.planned_start_date" value-format="YYYY-MM-DD" :disabled="productionAttempted"/></label><label><span>计划完成</span><el-date-picker v-model="productionForm.planned_end_date" value-format="YYYY-MM-DD" :disabled="productionAttempted"/></label></div><label>生产批号</label><el-input v-model="productionForm.production_batch_number" :disabled="productionAttempted"/><label>计划员</label><el-select v-model="productionForm.planner_id" :disabled="productionAttempted"><el-option v-for="person in productionPlanners" :key="person.id" :value="person.id" :label="person.display_name"/></el-select></section>
      </div>
      <p class="dialog-lead">本次为当前批次中的单个产品建立生产订单，建立后立即提交 PMC；当前生产模块只接受整数数量。</p>
      <template #footer><el-button @click="productionVisible = false">取消</el-button><el-button type="primary" :loading="actionLoading" @click="submitProduction">建立并提交PMC</el-button></template>
    </AppWindowDialog>
    <AppWindowDialog v-model="collaborationVisible" :title="collaborationForm.event_type === 'SHIPMENT' ? '登记协同 · 发货' : '登记订单协同事项'" :width="840" :height="720" class="sales-order-dialog" :close-on-click-modal="false"><div class="dialog-columns"><section><h3>事项分类</h3><label>协同类型</label><el-select v-model="collaborationForm.event_type"><el-option v-for="item in eventTypes" :key="item[0]" :value="item[0]" :label="item[1]"/></el-select><label>关联批次</label><el-select v-model="collaborationForm.delivery_batch_id" clearable><el-option v-for="batch in activeBatches" :key="batch.id" :value="batch.id" :label="`${batch.batch_number} · ${batch.planned_delivery_date}`"/></el-select><label>事项状态</label><el-select v-model="collaborationForm.status"><el-option value="PENDING" label="待处理"/><el-option value="COMPLETED" label="完成"/><el-option value="RISK" label="风险"/><el-option value="CANCELLED" label="取消"/></el-select></section><section><h3>记录内容</h3><label>事项标题</label><el-input v-model="collaborationForm.title" maxlength="200"/><label>发生时间</label><el-date-picker v-model="collaborationForm.occurred_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ"/><template v-if="collaborationForm.event_type === 'SHIPMENT'"><label>本次发货数量</label><el-input-number v-model="collaborationForm.quantity" :min="0.0001" :precision="4" :controls="false"/></template><label>补充说明</label><el-input v-model="collaborationForm.note" type="textarea" :rows="3" maxlength="1000"/></section></div><section class="dialog-preview"><h3>记录内容预览</h3><dl class="dialog-dl"><dt>关联订单</dt><dd>{{ order?.order_number }}</dd><dt>协同事项</dt><dd>{{ eventTypes.find((item) => item[0] === collaborationForm.event_type)?.[1] }} · {{ collaborationForm.status === 'COMPLETED' ? '完成' : collaborationForm.status === 'RISK' ? '风险' : collaborationForm.status === 'CANCELLED' ? '取消' : '待处理' }}</dd><dt>事项标题</dt><dd>{{ collaborationForm.title || '尚未填写' }}</dd></dl></section><template #footer><el-button @click="collaborationVisible = false">取消</el-button><el-button type="primary" :loading="actionLoading" @click="addEvent">保存协同记录</el-button></template></AppWindowDialog>
    <AppWindowDialog v-model="cancelBatchVisible" title="取消正式交付批次" :width="900" :height="720" class="sales-order-dialog" :close-on-click-modal="false"><p class="dialog-lead danger">取消后保留已建立的生产与协同历史，批次差额和取消原因继续留痕。</p><div class="dialog-columns"><section><h3>批次影响</h3><dl class="dialog-dl"><dt>交付批次</dt><dd>{{ selectedBatch?.batch_number }}</dd><dt>计划交期</dt><dd>{{ selectedBatch?.planned_delivery_date }}</dd><dt>需求数量</dt><dd>{{ numberText(selectedBatch?.lines.reduce((sum, line) => sum + Number(line.quantity), 0) || 0) }}</dd></dl><table class="mini-table"><thead><tr><th>产品</th><th>数量</th></tr></thead><tbody><tr v-for="line in selectedBatch?.lines || []" :key="line.id"><td>{{ line.product_name }}</td><td>{{ numberText(line.quantity) }}</td></tr></tbody></table></section><section><h3>客户确认</h3><label>本订单客户凭证</label><el-select v-model="cancelForm.evidence_file_id"><el-option v-for="file in order?.evidence || []" :key="file.file_id" :value="file.file_id" :label="file.file_name"/></el-select><label>取消原因</label><el-input v-model="cancelForm.reason" type="textarea" :rows="6" maxlength="1000"/><p class="muted">客户确认凭证和取消原因将写入新版本历史。</p></section></div><template #footer><el-button @click="cancelBatchVisible = false">取消</el-button><el-button type="danger" :loading="actionLoading" @click="cancelBatch">确认取消批次</el-button></template></AppWindowDialog>
    <AppWindowDialog v-model="completeVisible" title="正常完结销售订单" :width="820" :height="620" class="sales-order-dialog" :close-on-click-modal="false"><span class="completion-state" :class="normalCompletionReady ? 'ready' : 'blocked'">{{ normalCompletionReady ? '条件满足' : '尚有缺口' }}</span><div class="dialog-columns completion-grid"><section><h3>交付检查</h3><dl class="dialog-dl"><dt>有效需求</dt><dd>{{ numberText(activeDemand) }}</dd><dt>累计发货</dt><dd>{{ numberText(completedShipment) }}</dd><dt>尚未交付</dt><dd>{{ numberText(remainingShipment) }}</dd></dl></section><section><h3>余款检查</h3><span class="status-tag" :class="balanceCompleted ? 'is-success' : 'is-warning'">{{ balanceCompleted ? '已完成' : '未完成' }}</span><p class="muted">余款协同事项需标记为完成；单证事项仅作提醒。</p></section></div><label>完结说明（选填）</label><el-input v-model="completeForm.note" type="textarea" :rows="3" maxlength="1000"/><p class="dialog-lead">说明可以填写，但不会因此变成异常关闭；最终仍由服务端复核交付和余款条件。</p><template #footer><el-button @click="completeVisible = false">取消</el-button><el-button type="primary" :loading="actionLoading" @click="completeOrder(false)">检查并正常完结</el-button></template></AppWindowDialog>
    <AppWindowDialog v-model="exceptionCloseVisible" title="异常关闭销售订单" :width="820" :height="620" class="sales-order-dialog" :close-on-click-modal="false"><div class="dialog-columns completion-grid"><section><h3>履约差额核对</h3><dl class="dialog-dl"><dt>有效需求</dt><dd>{{ numberText(activeDemand) }}</dd><dt>累计发货</dt><dd>{{ numberText(completedShipment) }}</dd><dt>尚未交付</dt><dd>{{ numberText(remainingShipment) }}</dd><dt>余款事项</dt><dd>{{ balanceCompleted ? '已完成' : '未完成' }}</dd></dl></section><section><p class="dialog-lead danger">异常关闭不表示交付或收款完成，未完成差额会保留在历史记录中。</p><label>异常关闭原因</label><el-input v-model="completeForm.reason" type="textarea" :rows="6" maxlength="1000"/></section></div><template #footer><el-button @click="exceptionCloseVisible = false">返回继续履约</el-button><el-button type="danger" :loading="actionLoading" @click="completeOrder(true)">确认异常关闭</el-button></template></AppWindowDialog>
    <AppWindowDialog v-model="conflictVisible" title="订单已被其他人更新" :width="680" :height="280" class="sales-order-dialog"><p class="dialog-lead danger">系统没有覆盖对方的修改。本次输入仍保留在当前弹窗，请先查看最新订单再决定如何处理。</p><template #footer><el-button @click="conflictVisible = false">保留当前输入</el-button><el-button type="primary" @click="conflictVisible = false; load()">查看最新记录</el-button></template></AppWindowDialog>
  </section>
</template>

<style lang="scss" scoped>
.sales-detail-page{height:calc(100vh - 92px);min-width:1260px;overflow:auto;padding:28px;background:var(--erp-page-background);color:#1f1d18}.detail-heading{display:flex;min-height:94px;align-items:flex-start;justify-content:space-between;gap:24px}.title-line{display:flex;align-items:center;gap:14px}.title-line h1{margin:0;font-family:'Noto Serif SC','Songti SC',serif;font-size:36px;font-weight:600;line-height:46px}.detail-heading p{margin:8px 0 0;color:#6f6a61;font-size:14px}.heading-actions{display:flex;align-items:center;gap:12px;margin-top:8px}.heading-actions .el-button{height:36px;margin:0;border-radius:5px}.heading-actions>.el-button{min-width:110px}.heading-actions>.el-button--primary{width:140px;border-color:#c84e28;background:#c84e28}.detail-tabs{display:flex;height:52px;align-items:flex-start;gap:18px}.detail-tabs button{height:44px;padding:0 10px;border:0;border-bottom:1px solid transparent;color:#6f6a61;background:transparent;font-size:16px;cursor:pointer}.detail-tabs button.active{border-bottom-color:#c84e28;color:#c84e28}.detail-layout{display:grid;grid-template-columns:minmax(0,1fr) 410px;align-items:start;gap:18px}.detail-content{display:grid;gap:16px}.content-card,.summary-card{border:1px solid #ddd6c9;border-radius:5px;background:#fcfbf7}.content-card{padding:14px}.content-card h2,.summary-card h2{margin:0;font-size:18px;line-height:28px}.content-card>h2{margin-bottom:12px}.info-grid{display:grid;grid-template-columns:125px 1fr 125px 1fr 145px 1fr;margin:0;gap:10px 12px;font-size:14px}.info-grid dt,.summary-card dt{color:#6f6a61}.info-grid dd,.summary-card dd{min-width:0;margin:0}.content-card :deep(.el-table){--el-table-border-color:#ddd6c9;--el-table-header-bg-color:#f0eadf;color:#1f1d18}.content-card :deep(.el-table__header th.el-table__cell){height:44px;background:#f0eadf;color:#6f6a61;font-weight:500}.content-card :deep(.el-table__inner-wrapper::before){display:none}.muted{margin-top:3px;color:#6f6a61;font-size:12px}.detail-aside{display:grid;gap:16px;position:sticky;top:0}.summary-card{padding:14px}.summary-card h2{margin-bottom:12px;padding:8px;background:#f0eadf}.summary-card dl{display:grid;grid-template-columns:128px 1fr;margin:0;gap:8px 10px;font-size:14px}.summary-card .amount{grid-column:1/-1;margin-bottom:4px;padding-bottom:12px;border-bottom:1px solid #ddd6c9;font-size:30px}.aside-event{display:flex;justify-content:space-between;margin:8px 0;font-size:13px}.aside-event small{color:#6f6a61}.status-tag{display:inline-flex;min-width:56px;height:24px;align-items:center;justify-content:center;padding:0 8px;border-radius:999px;color:#faf9f5;font-size:12px;font-weight:500;line-height:18px}.status-tag.is-neutral{background:#65635e}.status-tag.is-success{background:#4e8750}.status-tag.is-info{background:#2f97df}.status-tag.is-warning{background:#b87818}.status-tag.is-danger{background:#b8442c}.section-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}.section-heading>span{color:#6f6a61;font-size:13px}.subheading{margin-top:18px!important}.requirement-row{display:grid;grid-template-columns:230px repeat(4,minmax(0,1fr));gap:14px;padding:14px 8px;border-top:1px solid #ddd6c9;font-size:13px}.requirement-row p{margin:0;line-height:20px}.detail-batch{margin-top:14px;border:1px solid #ddd6c9;border-radius:5px}.detail-batch.cancelled{opacity:.68}.detail-batch>header,.detail-batch>footer{display:flex;align-items:center;justify-content:space-between;padding:12px 14px}.detail-batch>header{background:#f7f2e9}.detail-batch>header>div{display:flex;gap:22px}.detail-batch>footer{color:#6f6a61;font-size:13px}.detail-batch>footer .el-button{margin-left:8px}.empty-state{padding:80px 20px;text-align:center}.empty-state h3{margin:0 0 8px}.empty-state p{color:#6f6a61}.upload-button{display:inline-flex;height:32px;align-items:center;gap:7px;padding:0 16px;border-radius:4px;color:#fff;background:#c84e28;cursor:pointer}.upload-button input{display:none}.text-link{color:#c84e28;text-decoration:none}.timeline{margin:0;padding:4px 0;list-style:none}.timeline li{display:grid;grid-template-columns:22px 1fr;gap:10px;position:relative;padding-bottom:24px}.timeline li::before{position:absolute;top:18px;bottom:0;left:6px;width:1px;background:#ddd6c9;content:''}.timeline li:last-child::before{display:none}.timeline-dot{width:13px;height:13px;margin-top:4px;border:3px solid #f4c6b7;border-radius:50%;background:#c84e28}.timeline header{display:flex;align-items:center;justify-content:space-between}.timeline p{margin:6px 0;color:#4d4942}.timeline small{color:#6f6a61}.state-page{display:flex;height:100%;align-items:center;justify-content:center;flex-direction:column;text-align:center}.state-page h2{margin:18px 0 8px}.state-page p{max-width:520px;margin:0 0 22px;color:#6f6a61}.state-code{font-family:'Noto Serif SC',serif;font-size:64px;color:#c84e28}.loading-mark{width:44px;height:44px;border:3px solid #e6d8ca;border-top-color:#c84e28;border-radius:50%;animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
:deep(.sales-order-dialog){border-radius:6px;background:#fcfbf7}.sales-detail-page :deep(.sales-order-dialog .el-dialog__header){margin:0;padding:24px 28px 18px;border-bottom:1px solid #ddd6c9}.sales-detail-page :deep(.sales-order-dialog .el-dialog__title){font-family:'Noto Serif SC','Songti SC',serif;font-size:24px;font-weight:600}.sales-detail-page :deep(.sales-order-dialog .el-dialog__body){display:grid;gap:10px;padding:22px 28px}.sales-detail-page :deep(.sales-order-dialog .el-dialog__footer){padding:16px 28px 24px}.sales-detail-page :deep(.sales-order-dialog .el-input__wrapper),.sales-detail-page :deep(.sales-order-dialog .el-select__wrapper){min-height:38px;border-radius:4px}.sales-detail-page :deep(.sales-order-dialog .el-button){height:32px;border-radius:4px}.sales-detail-page :deep(.sales-order-dialog .el-button--primary){border-color:#c84e28;background:#c84e28}.dialog-lead{margin:0;padding:12px 14px;border-radius:5px;background:#f0eadf;color:#6f6a61;line-height:22px}.dialog-lead.danger{color:#9f351f;background:#f8e7e1}.check-list{display:grid;gap:8px}.check-list div{display:flex;align-items:center;gap:10px;padding:10px 12px;color:#9f351f;background:#fff4f0}.check-list div.passed{color:#3c7040;background:#edf6ed}.check-list span{display:inline-flex;width:22px;height:22px;align-items:center;justify-content:center;border-radius:50%;color:#fff;background:currentColor}.blocked-copy{display:flex;gap:14px}.blocked-copy>span{display:flex;width:38px;height:38px;align-items:center;justify-content:center;border-radius:50%;color:#fff;background:#c84e28;font-size:22px}.blocked-copy h3{margin:0 0 8px}.blocked-copy p{margin:0;color:#6f6a61}.dialog-columns{display:grid;grid-template-columns:1fr 1fr;gap:20px}.dialog-columns section{display:grid;align-content:start;gap:9px;padding:14px;border:1px solid #ddd6c9}.dialog-columns h3{margin:0 0 4px;font-size:17px}.dialog-columns label,.sales-order-dialog>label{margin-top:4px;color:#6f6a61;font-size:13px}.dialog-dl{display:grid;grid-template-columns:110px 1fr;margin:0;gap:10px}.dialog-dl dt{color:#6f6a61}.dialog-dl dd{margin:0}.production-layout{grid-template-columns:.9fr 1.1fr}.production-layout .field-pair{display:grid;grid-template-columns:1fr 1fr;gap:10px}.production-layout .field-pair label{display:grid;gap:6px}.production-layout :deep(.el-date-editor){width:100%}.confirm-layout{margin:2px 0}.mini-table{width:100%;border-collapse:collapse;font-size:13px}.mini-table th,.mini-table td{padding:8px;border-bottom:1px solid #e5ded2;text-align:left}.mini-table th{color:#6f6a61;background:#f3eee5;font-weight:500}.dialog-preview{padding:14px;border:1px solid #ddd6c9}.dialog-preview h3{margin:0 0 10px;font-size:17px}.completion-grid section{min-height:128px}.completion-state{display:inline-flex;width:max-content;padding:4px 10px;border-radius:999px;color:#fff;font-size:12px}.completion-state.ready{background:#4e8750}.completion-state.blocked{background:#b87818}
</style>

<style lang="scss" scoped>
.sales-detail-page { padding: 14px; }
</style>
