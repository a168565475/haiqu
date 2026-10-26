<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { MoreFilled, Plus, Search, Filter } from '@element-plus/icons-vue'
import BuildingOne from '@icon-park/vue-next/es/icons/BuildingOne'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  completePurchaseOrder,
  fetchVersionedPurchaseOrder,
  deletePurchaseOrder,
  fetchPurchaseOrderFilterOptions,
  fetchPurchaseOrders,
} from '@/api/purchaseOrders'
import { useAuthStore } from '@/stores/auth'
import PurchaseOrderCompleteDialog from '@/components/procurement/PurchaseOrderCompleteDialog.vue'
import SupplierAmountPopover from '@/components/procurement/SupplierAmountPopover.vue'
import type {
  PurchaseOrderListItem,
  PurchaseOrderFilterOptions,
  PurchaseOrderStatus,
  PurchaseReturnStatus,
  VersionedPurchaseOrder,
} from '@/types/purchaseOrder'

const router = useRouter()
const authStore = useAuthStore()
const isSuperuser = computed(() => authStore.user?.is_superuser === true)
const can = (permission: string) => isSuperuser.value || authStore.hasPermission(permission)
const canView = computed(() => can('procurement.view_purchaseorder'))
const canViewSuppliers = computed(() => can('procurement.view_supplier'))
const canAdd = computed(() => can('procurement.add_purchaseorder'))
const canEdit = computed(() => authStore.moduleCan('procurement.change_purchaseorder', 'procurement.add_purchaseorder'))
const canComplete = computed(() => authStore.moduleCan('access_control.complete_purchaseorder', 'procurement.submit_purchaseorder'))
const canSubmit = computed(() => can('procurement.submit_purchaseorder'))
const canDelete = computed(() => can('procurement.delete_purchaseorder'))

const emptyOptions = (): PurchaseOrderFilterOptions => ({
  production_tasks: [],
  suppliers: [],
  statuses: [],
})
const rows = ref<PurchaseOrderListItem[]>([])
const options = ref<PurchaseOrderFilterOptions>(emptyOptions())
const loading = ref(false)
const listError = ref('')
const optionsError = ref('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const listReady = ref(false)
const showMoreFilters = ref(false)
const deletingId = ref('')
const completingId = ref('')
const completionVisible = ref(false)
const completionSubmitting = ref(false)
const completionSnapshot = ref<VersionedPurchaseOrder | null>(null)
let disposed = false
let requestId = 0
let optionsRequestId = 0

const filters = reactive({
  keyword: '',
  productionTaskId: '',
  supplierId: '',
  status: '' as PurchaseOrderStatus | '',
  returnStatus: '' as PurchaseReturnStatus | '',
  createdAfter: '',
})

function apiErrorMessage(error: unknown, fallback: string): string {
  const response = (error as {
    response?: {
      status?: number
      data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string }
    }
  })?.response
  const firstFieldError = response?.data?.error?.field_errors
    ? Object.values(response.data.error.field_errors).flat()[0]
    : ''
  if (response?.status === 403) return '当前账号没有查看采购订单的权限。'
  return firstFieldError || response?.data?.error?.message || response?.data?.detail || fallback
}

function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const normalized = value.trim()
  const matched = /^(-?)(\d+)(?:\.(\d+))?$/.exec(normalized)
  if (!matched) return normalized
  const grouped = (matched[2] || '0').replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${matched[1] || ''}${grouped}${matched[3]?.replace(/0+$/, '') ? `.${matched[3].replace(/0+$/, '')}` : ''}`
}

function formatDateTime(value: string): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(parsed).replaceAll('/', '-')
}

const statusOptions = computed(() => options.value.statuses?.length ? options.value.statuses : [
  { value: 'DRAFT', label: '草稿' }, { value: 'SUBMITTED', label: '已确认' },
  { value: 'PURCHASING', label: '采购中' },
  { value: 'COMPLETED', label: '已完成采购' },
])
const returnStatusOptions: Array<{ value: PurchaseReturnStatus; label: string }> = [
  { value: 'NONE', label: '无退货' },
  { value: 'QUALITY_GENERATED', label: '待确认退货' },
  { value: 'PROCUREMENT_CONFIRMED', label: '待退货完成' },
  { value: 'COMPLETED', label: '退货完成' },
  { value: 'MISSING', label: '退货记录待核对' },
]

function productionTaskLabel(item: PurchaseOrderFilterOptions['production_tasks'][number]): string {
  return `${item.task_number} · ${item.order_number}`
}

function supplierLabel(item: PurchaseOrderFilterOptions['suppliers'][number]): string {
  return `${item.supplier_number} · ${item.supplier_name}`
}

function supplierProgress(row: PurchaseOrderListItem): string {
  return `${row.supplier_assigned_line_count ?? '—'}/${row.line_count} 行 · ${row.supplier_count}家`
}

function productField(row: PurchaseOrderListItem, field: 'specification' | 'color_name' | 'material'): string {
  return row.product_summary.map(product => product[field]?.trim() || '—').join('、') || '—'
}

function productColor(product: PurchaseOrderListItem['product_summary'][number]): string {
  const placeholderValues = new Set(['/', '-', '—'])
  return [product.color_card, product.color_name, product.color_code]
    .map((value) => (value || '').trim())
    .filter((value) => value && !placeholderValues.has(value))
    .join(' · ') || '—'
}

function productDetails(row: PurchaseOrderListItem): string {
  return row.product_summary.map((product) =>
    `${product.product_name || '—'}\n规格：${product.specification || '—'}\n颜色：${productColor(product)}\n材质：${product.material || '—'}`,
  ).join('\n\n')
}

async function loadList(): Promise<void> {
  const currentRequestId = ++requestId
  loading.value = true
  listError.value = ''
  try {
    const result = await fetchPurchaseOrders({
      page: page.value,
      page_size: pageSize.value,
      q: filters.keyword.trim() || undefined,
      production_task_id: filters.productionTaskId || undefined,
      supplier_id: filters.supplierId || undefined,
      status: filters.status,
      return_status: filters.returnStatus,
      created_after: filters.createdAfter || undefined,
      ordering: '-updated_at',
    })
    if (currentRequestId !== requestId) return
    rows.value = result.data
    total.value = result.meta.total
    listReady.value = true
    if (page.value > result.meta.total_pages && result.meta.total_pages > 0) {
      page.value = result.meta.total_pages
      await loadList()
    }
  } catch (error) {
    if (currentRequestId !== requestId) return
    rows.value = []
    total.value = 0
    listReady.value = false
    listError.value = apiErrorMessage(error, '采购订单列表加载失败，请稍后重试。')
  } finally {
    if (currentRequestId === requestId) loading.value = false
  }
}

async function loadOptions(): Promise<void> {
  const currentRequestId = ++optionsRequestId
  optionsError.value = ''
  try {
    const nextOptions = await fetchPurchaseOrderFilterOptions()
    if (disposed || currentRequestId !== optionsRequestId) return
    options.value = nextOptions
  } catch (error) {
    if (disposed || currentRequestId !== optionsRequestId) return
    optionsError.value = apiErrorMessage(error, '采购订单筛选项加载失败，请稍后重试。')
  }
}

async function reloadAll(): Promise<void> {
  await Promise.all([loadList(), loadOptions()])
}

function search(): void {
  page.value = 1
  void loadList()
}

function handleSearchEnter(event: KeyboardEvent): void {
  if (event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  search()
}

function resetFilters(): void {
  Object.assign(filters, {
    keyword: '', productionTaskId: '', supplierId: '', status: '', returnStatus: '', createdAfter: '',
  })
  search()
}

function openCreate(): void {
  if (canAdd.value) void router.push({ name: 'purchase-order-create' })
}

function openSuppliers(): void {
  if (canViewSuppliers.value) void router.push({ name: 'suppliers' })
}

function openConfirm(row: PurchaseOrderListItem): void {
  void router.push({ name: 'purchase-order-confirm', params: { id: row.id } })
}

function openSheets(row: PurchaseOrderListItem): void {
  void router.push({ name: 'purchase-sheet-template-select', params: { id: row.id } })
}

function returnActionLabel(row: PurchaseOrderListItem): string {
  const returnStatus = row.completion?.return_status
  if (returnStatus === 'QUALITY_GENERATED') return '查看品质情况'
  if (returnStatus === 'PROCUREMENT_CONFIRMED' || returnStatus === 'COMPLETED') return '查看退货明细'
  return ''
}

function openReturns(row: PurchaseOrderListItem): void {
  if (!returnActionLabel(row)) return
  void router.push({
    name: 'purchase-returns',
    query: { purchase_order_id: row.id, from: 'orders' },
  })
}

function hasRowAction(row: PurchaseOrderListItem): boolean {
  return canView.value || !!returnActionLabel(row)
    || ((canAdd.value && canSubmit.value && row.status === 'DRAFT') || (canEdit.value && row.status === 'SUBMITTED'))
    || ['SUBMITTED', 'PURCHASING'].includes(row.status)
    || (canDelete.value && row.status !== 'COMPLETED')
    || row.status === 'COMPLETED'
}

function handleRowAction(command: 'details' | 'confirm' | 'sheets' | 'delete' | 'complete' | 'returns', row: PurchaseOrderListItem): void {
  if (command === 'details') {
    void router.push({ name: 'purchase-order-detail', params: { id: row.id } })
    return
  }
  if (command === 'returns') {
    openReturns(row)
    return
  }
  if (command === 'complete') {
    void finishPurchase(row)
    return
  }
  if (command === 'confirm') {
    openConfirm(row)
    return
  }
  if (command === 'sheets') {
    openSheets(row)
    return
  }
  void removeOrder(row)
}

async function finishPurchase(row: PurchaseOrderListItem): Promise<void> {
  if (!canComplete.value || completingId.value || !['SUBMITTED', 'PURCHASING'].includes(row.status) || disposed) return
  completingId.value = row.id
  try {
    const current = await fetchVersionedPurchaseOrder(row.id)
    if (disposed) return
    if (!['SUBMITTED', 'PURCHASING'].includes(current.data.status) || !current.data.completion?.can_complete) {
      ElMessage.warning(current.data.completion?.blocked_reason || '当前采购单不能完成，请刷新后重试。')
      return
    }
    if (!current.etag) { ElMessage.error('未取得采购单版本，请刷新后重试。'); return }
    completionSnapshot.value = current
    completionVisible.value = true
  } catch (error) {
    if (!disposed) ElMessage.error(apiErrorMessage(error, '采购单读取失败，请刷新后重试。'))
  } finally {
    if (!completionVisible.value) completingId.value = ''
  }
}

function closeCompletion(): void {
  if (completionSubmitting.value) return
  completionVisible.value = false
  completionSnapshot.value = null
  completingId.value = ''
}

async function submitCompletion(remark: string): Promise<void> {
  const current = completionSnapshot.value
  if (disposed || completionSubmitting.value || !completionVisible.value || !canComplete.value || !current?.etag || !['SUBMITTED', 'PURCHASING'].includes(current.data.status) || !current.data.completion?.can_complete) return
  const value = current.data.completion.has_returns ? remark.trim() : ''
  if ((current.data.completion.has_returns && !value) || Array.from(value).length > 2000) return
  completionSubmitting.value = true
  try {
    // 使用打开弹窗时核对的同一版本，避免备注提交覆盖其他人的更新。
    await completePurchaseOrder(current.data.id, value, current.etag)
    if (disposed) return
    completionVisible.value = false
    completionSnapshot.value = null
    ElMessage.success('采购已完成。')
    await reloadAll()
  } catch (error) {
    if (disposed) return
    const status = (error as { response?: { status?: number } })?.response?.status
    ElMessage.error(status === 403 ? '当前账号没有完成该采购单的权限。' : apiErrorMessage(error, '完成采购失败，请重试。'))
    if ([403, 404, 409, 412].includes(status ?? 0)) {
      completionVisible.value = false
      completionSnapshot.value = null
      await reloadAll()
    }
  } finally {
    completionSubmitting.value = false
    if (!completionVisible.value) completingId.value = ''
  }
}

async function removeOrder(row: PurchaseOrderListItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除采购订单 ${row.order_number} 吗？已生成的供应商采购表、历史版本及归档文件也会一并删除。删除后无法恢复，但可以从原生产订单重新创建。`,
      '删除采购订单',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiErrorMessage(error, '无法打开删除确认框。'))
    return
  }

  deletingId.value = row.id
  try {
    await deletePurchaseOrder(row.id)
    ElMessage.success('采购订单及关联供应商采购表已删除。')
    await reloadAll()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '采购订单删除失败，请稍后重试。'))
  } finally {
    deletingId.value = ''
  }
}

onMounted(() => {
  if (canView.value) void reloadAll()
})
onBeforeUnmount(() => { disposed = true; requestId++; optionsRequestId++; completionVisible.value = false; completionSnapshot.value = null })
</script>

<template>
  <section class="purchase-list-page erp-glass-list" data-testid="purchase-order-list-page">
    <PurchaseOrderCompleteDialog :visible="completionVisible" :record="completionSnapshot?.data ?? null" :submitting="completionSubmitting" @cancel="closeCompletion" @confirm="submitCompletion" />
    <section v-glass-spotlight class="erp-list-filter">
    <header class="page-heading erp-list-heading">
      <div class="page-heading__title">
        <h1>采购订单</h1>
        <span v-if="canView" class="page-heading__count">共 {{ listReady ? total : '—' }} 条</span>
      </div>
      <div v-if="!canView && canViewSuppliers" class="page-heading__actions">
        <ElButton class="supplier-button" data-testid="purchase-suppliers-entry" @click="openSuppliers">
          <BuildingOne theme="outline" size="18" :stroke-width="3" aria-hidden="true" />
          <span>供应商管理</span>
        </ElButton>
      </div>
    </header>

      <section v-if="canView" class="filter-section" aria-label="采购订单筛选">
        <form class="filter-row erp-list-filters" @submit.prevent="search">
          <ElInput v-model="filters.keyword" class="keyword-filter" clearable aria-label="搜索采购订单"
            placeholder="搜索采购单、来源单等" title="支持采购单、生产单、销售单、打样单、客户、供应商或物料名称" @keydown.enter="handleSearchEnter" @clear="search">
            <template #suffix><button type="button" class="erp-list-search-button" aria-label="搜索采购订单列表" @click="search"><ElIcon><Search /></ElIcon></button></template>
          </ElInput>
          <ElSelect v-model="filters.supplierId" class="supplier-filter" filterable clearable placeholder="供应商：全部"
            aria-label="供应商筛选" @change="search">
            <ElOption v-for="item in options.suppliers" :key="item.id" :label="supplierLabel(item)" :value="item.id" />
          </ElSelect>
          <ElSelect v-model="filters.status" class="status-filter" clearable placeholder="采购状态：全部" aria-label="采购状态筛选" @change="search">
            <ElOption v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </ElSelect>
          <ElSelect v-model="filters.returnStatus" class="return-filter" clearable placeholder="退货状态：全部" aria-label="退货状态筛选" @change="search">
            <ElOption v-for="item in returnStatusOptions" :key="item.value" :label="item.label" :value="item.value" />
          </ElSelect>
          <ElButton :icon="Filter" class="more-filters-button erp-button-motion" :aria-expanded="showMoreFilters" aria-controls="purchase-more-filters" @click="showMoreFilters = !showMoreFilters">更多筛选</ElButton>
          <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="resetFilters">重置</ElButton><ElButton class="erp-button-motion" type="primary" native-type="submit">应用筛选</ElButton></div>
        </form>
        <div v-if="showMoreFilters" id="purchase-more-filters" class="extra-filters erp-list-filters">
          <ElSelect v-model="filters.productionTaskId" filterable clearable placeholder="全部生产订单" aria-label="生产订单筛选" @change="search">
            <ElOption v-for="item in options.production_tasks" :key="item.id" :label="productionTaskLabel(item)" :value="item.id" />
          </ElSelect>
          <ElDatePicker v-model="filters.createdAfter" type="date" value-format="YYYY-MM-DD" placeholder="创建日期起" aria-label="创建日期起" clearable @change="search" />
        </div>
      </section>
    </section>

    <div v-if="!canView" class="state-page">
      <h2>无权查看采购订单</h2>
      <p>请联系管理员开通“采购订单查看”权限后重试。</p>
    </div>

    <template v-else>
      <ElAlert v-if="listError" class="load-error" type="error" :title="listError" :closable="false" show-icon>
        <ElButton link @click="loadList">重新加载</ElButton>
      </ElAlert>
      <ElAlert v-if="optionsError" class="load-error" type="error" :title="optionsError" :closable="false" show-icon>
        <ElButton link @click="loadOptions">重试选项</ElButton>
      </ElAlert>

      <section class="list-card erp-list-data" aria-label="采购订单清单">
          <div class="purchase-list-actions erp-list-toolbar">
            <ElButton v-if="canViewSuppliers" class="supplier-button erp-button-motion" data-testid="purchase-suppliers-entry" @click="openSuppliers">
              <BuildingOne theme="outline" size="18" :stroke-width="3" aria-hidden="true" />
              <span>供应商管理</span>
            </ElButton>
            <ElButton v-if="canAdd" type="primary" :icon="Plus" class="create-button erp-button-motion" @click="openCreate">新建采购订单</ElButton>
          </div>
        <div class="erp-list-table-frame">
        <ElTable v-loading="loading" :data="rows" row-key="id" class="purchase-table" height="100%">
          <ElTableColumn label="采购单号" width="162" show-overflow-tooltip>
            <template #default="{ row }"><strong class="order-number">{{ row.order_number }}</strong></template>
          </ElTableColumn>
          <ElTableColumn label="关联订单" width="145">
            <template #default="{ row }">
              <div v-if="row.source_type === 'SAMPLE'" class="cell-stack order-summary" data-testid="purchase-order-basic-info"
                :title="`打样单：${row.source_number || '—'}\n交期：${row.delivery_date || '—'}`">
                <span>{{ row.source_number || '—' }}</span>
              </div>
              <div v-else class="cell-stack order-summary" data-testid="purchase-order-basic-info"
                :title="`生产单号：${row.production_task_number || '—'}\n交期：${row.delivery_date || '—'}`">
                <span>{{ row.production_task_number || '—' }}</span>
              </div>
            </template>
          </ElTableColumn>
          <ElTableColumn label="产品信息" min-width="188">
            <template #default="{ row }">
              <div v-if="row.source_type === 'SAMPLE'" class="cell-stack product-summary" data-testid="purchase-sample-requirements">
                <strong>样品采购需求</strong><small>{{ row.line_count }}项</small>
              </div>
              <ElTooltip v-else-if="row.product_summary.length" placement="right" :show-after="250" popper-class="purchase-product-tooltip">
                <template #content><div class="product-tooltip-content">{{ productDetails(row) }}</div></template>
                <div class="cell-stack product-summary" tabindex="0" data-testid="purchase-order-products">
                  <strong>{{ row.product_summary[0].product_name || '—' }}<template v-if="row.product_summary.length > 1"> 等{{ row.product_summary.length }}款</template></strong>
                </div>
              </ElTooltip>
              <span v-else class="muted">—</span>
            </template>
          </ElTableColumn>
          <ElTableColumn label="规格" min-width="148" show-overflow-tooltip><template #default="{ row }">{{ productField(row, 'specification') }}</template></ElTableColumn>
          <ElTableColumn label="颜色" min-width="110" show-overflow-tooltip><template #default="{ row }">{{ productField(row, 'color_name') }}</template></ElTableColumn>
          <ElTableColumn label="材质" min-width="100" show-overflow-tooltip><template #default="{ row }">{{ productField(row, 'material') }}</template></ElTableColumn>
          <ElTableColumn label="供应商进度" width="144">
            <template #default="{ row }"><SupplierAmountPopover :suppliers="row.supplier_summary || []" :currency="row.currency_code" :label="supplierProgress(row)" /></template>
          </ElTableColumn>
          <ElTableColumn label="采购金额" width="146" show-overflow-tooltip>
            <template #default="{ row }"><span class="amount" :class="{ 'amount--pending erp-list-tag erp-list-tag--neutral': !row.currency_code || row.total_amount === null }">{{ row.currency_code && row.total_amount !== null ? `${row.currency_code} ${formatMoney(row.total_amount)}` : '待计算' }}</span></template>
          </ElTableColumn>
          <ElTableColumn label="是否邮寄" width="88" align="center">
            <template #default="{ row }">{{ row.is_mailed === null ? '待填写' : row.is_mailed ? '是' : '否' }}</template>
          </ElTableColumn>
          <ElTableColumn label="订单来源" width="112" align="center">
            <template #default="{ row }"><span class="purchase-source-tag erp-list-tag" :class="row.source_type === 'SAMPLE' ? 'is-sample erp-list-tag--warning' : 'erp-list-tag--info'" data-testid="purchase-source-tag">{{ row.source_type === 'SAMPLE' ? '打样单' : '生产订单' }}</span></template>
          </ElTableColumn>
          <ElTableColumn label="采购状态" width="122" align="center">
            <template #default="{ row }"><span class="status-badge erp-list-tag" :class="row.status === 'COMPLETED' ? 'is-completed erp-list-tag--success' : row.status === 'SUBMITTED' ? 'is-confirmed erp-list-tag--info' : row.status === 'PURCHASING' ? 'is-purchasing erp-list-tag--brand' : 'is-draft erp-list-tag--neutral'" :title="row.completion_remark || ''">{{ row.status_display }}</span></template>
          </ElTableColumn>
          <ElTableColumn label="入库情况" width="198">
            <template #default="{ row }"><span class="inbound-summary" :class="[row.completion?.inbound_status ? `inbound-${row.completion.inbound_status}` : 'muted', { 'erp-list-tag': row.completion?.inbound_status && row.completion.inbound_status !== 'NOT_STARTED', 'erp-list-tag--brand': ['PENDING_RECEIPT', 'PARTIAL_RECEIVED'].includes(row.completion?.inbound_status || ''), 'erp-list-tag--warning': row.completion?.inbound_status === 'PENDING_QUALITY', 'erp-list-tag--danger': ['PENDING_PROCUREMENT_CONFIRMATION', 'RETURN_RECORD_MISSING'].includes(row.completion?.inbound_status || ''), 'erp-list-tag--info': row.completion?.inbound_status === 'PENDING_RETURN', 'erp-list-tag--success': ['CONFIRMED', 'COMPLETED'].includes(row.completion?.inbound_status || '') }]" data-testid="purchase-inbound-status">{{ row.completion?.inbound_status_display || '—' }}</span></template>
          </ElTableColumn>
          <ElTableColumn label="更新时间" width="161">
            <template #default="{ row }">{{ formatDateTime(row.updated_at || row.created_at) }}</template>
          </ElTableColumn>
          <ElTableColumn label="操作" width="72" fixed="right" align="center">
            <template #default="{ row }">
              <div class="row-actions">
                <ElDropdown v-if="hasRowAction(row)" :persistent="false" trigger="click" placement="bottom-end" @command="handleRowAction($event, row)">
                  <ElButton link class="row-more-button" :icon="MoreFilled" :aria-label="`${row.order_number}的更多操作`" :loading="deletingId === row.id || completingId === row.id" />
                  <template #dropdown>
                    <ElDropdownMenu>
                      <ElDropdownItem v-if="returnActionLabel(row)" command="returns">{{ returnActionLabel(row) }}</ElDropdownItem>
                      <ElDropdownItem command="details">查看明细</ElDropdownItem>
                      <ElDropdownItem v-if="canAdd && canSubmit && row.status === 'DRAFT'" command="confirm">确认</ElDropdownItem>
                      <ElDropdownItem v-if="canEdit && row.status === 'SUBMITTED'" command="confirm">编辑采购订单</ElDropdownItem>
                      <ElDropdownItem v-if="['SUBMITTED', 'PURCHASING', 'COMPLETED'].includes(row.status)" command="sheets">采购表</ElDropdownItem>
                      <ElDropdownItem v-if="canComplete && ['SUBMITTED', 'PURCHASING'].includes(row.status)" command="complete" :disabled="!row.completion?.can_complete" :title="row.completion?.blocked_reason || ''">完成采购</ElDropdownItem>
                      <ElDropdownItem v-if="canDelete && row.status !== 'COMPLETED'" command="delete" divided>删除</ElDropdownItem>
                    </ElDropdownMenu>
                  </template>
                </ElDropdown>
                <span v-if="!hasRowAction(row)" class="muted">—</span>
              </div>
            </template>
          </ElTableColumn>
          <template #empty>
            <div class="empty-state">
              <strong>{{ listError ? '采购订单加载失败' : loading ? '正在加载采购订单' : '暂无采购订单' }}</strong>
              <p>{{ listError ? '请重新加载后再试。' : '调整筛选条件，或选择生产订单、打样单新建采购订单。' }}</p>
              <ElButton v-if="listError" @click="reloadAll">重新加载</ElButton>
              <ElButton v-else-if="canAdd && !loading" type="primary" :icon="Plus" @click="openCreate">新建采购订单</ElButton>
            </div>
          </template>
        </ElTable>
        </div>
        <footer class="list-card__footer erp-list-footer">
          <span>共 {{ listReady ? total : '—' }} 条</span>
          <ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]"
            :pager-count="5" layout="sizes, prev, pager, next" background @current-change="loadList" @size-change="search" />
        </footer>
      </section>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/mixins' as mixin;
.page-heading__title { display: flex; flex-wrap: wrap; align-items: baseline; gap: 12px; min-width: 0; }
.page-heading__count { color: var(--erp-color-text-secondary); white-space: nowrap; font-size: 12px; }
.page-heading__actions { display: flex; align-items: center; gap: 8px; margin-left: auto; }
.create-button { width: 164px; }
.supplier-button { width: 144px; }
.supplier-button :deep(> span) { display: flex; align-items: center; gap: 8px; }
.keyword-filter { width: min(250px, 100%); flex: none; }
.supplier-filter { width: 180px; flex: none; }
.status-filter { width: 160px; flex: none; }
.return-filter { width: 150px; flex: none; }
.more-filters-button { width: 112px; }
.extra-filters { padding-top: 12px; }
.extra-filters :deep(.el-select) { width: min(300px, 100%); }
.extra-filters :deep(.el-date-editor) { width: 207px; flex: none; }
.load-error { flex: none; }
.cell-stack { min-width: 0; display: flex; flex-direction: column; line-height: 18px; }
.cell-stack > * { @include mixin.text-ellipsis; }
.cell-stack small { color: var(--erp-table-text); font-size: 12px; }
.product-summary strong, .order-number { font-weight: 600; }
.order-summary > span { font-weight: 500; }
.product-summary:focus-visible { @include mixin.focus-ring; }
.product-tooltip-content { max-width: 440px; max-height: 420px; overflow: auto; white-space: pre-line; }
.amount, .order-number { font-variant-numeric: tabular-nums; white-space: nowrap; }
.amount { font-weight: 500; }
.status-badge { min-width: 88px; }
.purchase-source-tag { width: 72px; }
.inbound-summary { max-width: 100%; }
.row-actions { display: flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; }
.row-more-button { color: var(--erp-table-text); width: 36px; height: 32px; }
.muted { color: var(--erp-table-text); }
.empty-state { display: flex; min-height: 300px; flex-direction: column; align-items: center; justify-content: center; color: var(--erp-color-text-secondary); }
.empty-state strong { font-size: 18px; color: var(--erp-color-text-primary); }
.empty-state p { margin: 8px 0 16px; }
.state-page { flex: 1; display: grid; place-content: center; text-align: center; }
.state-page h2 { margin: 0 0 8px; }
.state-page p { margin: 0; color: var(--erp-color-text-secondary); }
</style>

<style lang="scss">
@use '@/styles/crm/tokens' as crm;

// MessageBox 挂载在 body，使用专用类继承采购页规范。
.purchase-completion-dialog {
  --el-color-primary: #{crm.$crm-primary};
  --el-color-primary-light-3: #{crm.$crm-primary-light-3};
  --el-color-primary-dark-2: #{crm.$crm-primary-pressed};
  --el-color-primary-light-9: #{crm.$crm-color-selected};
  --el-bg-color: #{crm.$crm-color-surface};
  --el-fill-color-blank: #{crm.$crm-color-surface};
  --el-text-color-primary: #{crm.$crm-text-primary};
  --el-text-color-regular: #{crm.$crm-text-regular};
  --el-border-color: #{crm.$crm-border-default};
  --el-border-radius-base: 5px;
  width: 480px;
  max-width: 480px;
  padding: 24px;
  border: 1px solid crm.$crm-border-default;
  border-radius: 6px;
  font-family: crm.$crm-font-body;

  .el-message-box__title { font-size: 20px; font-weight: 600; }
  .el-message-box__message { line-height: 24px; }
  .el-message-box__btns { padding-top: 16px; }
  .el-button { height: 40px; padding: 0 20px; }
  .el-textarea__inner { min-height: 96px !important; padding: 10px 12px; line-height: 24px; }
}
</style>
