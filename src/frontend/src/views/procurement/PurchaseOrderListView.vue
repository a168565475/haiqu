<script setup lang="ts">
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
  return `${matched[1] || ''}${grouped}${matched[3] ? `.${matched[3]}` : ''}`
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

function supplierNames(row: PurchaseOrderListItem): string {
  const suppliers = row.supplier_summary || []
  if (!suppliers.length) return '尚未选择供应商'
  if (suppliers.length === 1) return suppliers[0]?.supplier_name || '—'
  return `${suppliers[0]?.supplier_name || '供应商'} 等 ${suppliers.length} 家`
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
    `${product.product_name || '—'}\n规格：${product.specification || '—'}\n颜色：${productColor(product)}`,
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
      `确定删除采购订单 ${row.order_number} 吗？已生成的供应商采购表、历史版本及 PDF 也会一并删除。删除后无法恢复，但可以从原生产订单重新创建。`,
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
  <section class="purchase-list-page" data-testid="purchase-order-list-page">
    <PurchaseOrderCompleteDialog :visible="completionVisible" :record="completionSnapshot?.data ?? null" :submitting="completionSubmitting" @cancel="closeCompletion" @confirm="submitCompletion" />
    <header class="page-heading">
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

    <div v-if="!canView" class="state-page">
      <h2>无权查看采购订单</h2>
      <p>请联系管理员开通“采购订单查看”权限后重试。</p>
    </div>

    <template v-else>
      <section class="filter-section" aria-label="采购订单筛选">
        <form class="filter-row" @submit.prevent="search">
          <ElInput v-model="filters.keyword" class="keyword-filter" clearable aria-label="搜索采购订单"
            placeholder="搜索采购单、来源单等" title="支持采购单、生产单、销售单、打样单、客户、供应商或物料名称" @keydown.enter="handleSearchEnter" @clear="search">
            <template #suffix><button type="button" class="purchase-search-button" aria-label="搜索采购订单列表" @click="search"><ElIcon><Search /></ElIcon></button></template>
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
          <ElButton :icon="Filter" class="more-filters-button" :aria-expanded="showMoreFilters" aria-controls="purchase-more-filters" @click="showMoreFilters = !showMoreFilters">更多筛选</ElButton>
          <div class="purchase-list-actions">
            <ElButton v-if="canViewSuppliers" class="supplier-button" data-testid="purchase-suppliers-entry" @click="openSuppliers">
              <BuildingOne theme="outline" size="18" :stroke-width="3" aria-hidden="true" />
              <span>供应商管理</span>
            </ElButton>
            <ElButton v-if="canAdd" type="primary" :icon="Plus" class="create-button" @click="openCreate">新建采购订单</ElButton>
          </div>
        </form>
        <div v-if="showMoreFilters" id="purchase-more-filters" class="extra-filters">
          <ElSelect v-model="filters.productionTaskId" filterable clearable placeholder="全部生产订单" aria-label="生产订单筛选" @change="search">
            <ElOption v-for="item in options.production_tasks" :key="item.id" :label="productionTaskLabel(item)" :value="item.id" />
          </ElSelect>
          <ElDatePicker v-model="filters.createdAfter" type="date" value-format="YYYY-MM-DD" placeholder="创建日期起" aria-label="创建日期起" clearable @change="search" />
          <ElButton @click="resetFilters">重置筛选</ElButton>
        </div>
      </section>

      <ElAlert v-if="listError" class="load-error" type="error" :title="listError" :closable="false" show-icon>
        <ElButton link @click="loadList">重新加载</ElButton>
      </ElAlert>
      <ElAlert v-if="optionsError" class="load-error" type="error" :title="optionsError" :closable="false" show-icon>
        <ElButton link @click="loadOptions">重试选项</ElButton>
      </ElAlert>

      <section class="list-card" aria-label="采购订单清单">
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
                <span>{{ row.is_historical_unlinked ? '历史未关联' : row.production_task_number || '—' }}</span>
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
          <ElTableColumn label="供应商进度" width="144">
            <template #default="{ row }"><span :title="supplierNames(row)">{{ supplierProgress(row) }}</span></template>
          </ElTableColumn>
          <ElTableColumn label="采购金额" width="146" show-overflow-tooltip>
            <template #default="{ row }"><span class="amount" :class="{ 'amount--pending': !row.currency_code || row.total_amount === null }">{{ row.currency_code && row.total_amount !== null ? `${row.currency_code} ${formatMoney(row.total_amount)}` : '待计算' }}</span></template>
          </ElTableColumn>
          <ElTableColumn label="是否邮寄" width="88" align="center">
            <template #default="{ row }">{{ row.is_mailed === null ? '待填写' : row.is_mailed ? '是' : '否' }}</template>
          </ElTableColumn>
          <ElTableColumn label="订单来源" width="112" align="center">
            <template #default="{ row }"><span class="purchase-source-tag" :class="{ 'is-sample': row.source_type === 'SAMPLE' }" data-testid="purchase-source-tag">{{ row.source_type === 'SAMPLE' ? '打样单' : '生产订单' }}</span></template>
          </ElTableColumn>
          <ElTableColumn label="采购状态" width="122" align="center">
            <template #default="{ row }"><span class="status-badge" :class="row.status === 'COMPLETED' ? 'is-completed' : row.status === 'SUBMITTED' ? 'is-confirmed' : row.status === 'PURCHASING' ? 'is-purchasing' : 'is-draft'" :title="row.completion_remark || ''">{{ row.status_display }}</span></template>
          </ElTableColumn>
          <ElTableColumn label="入库情况" width="198">
            <template #default="{ row }"><span class="inbound-summary" :class="row.completion?.inbound_status ? `inbound-${row.completion.inbound_status}` : 'muted'" data-testid="purchase-inbound-status">{{ row.completion?.inbound_status_display || '—' }}</span></template>
          </ElTableColumn>
          <ElTableColumn label="更新信息" width="161">
            <template #default="{ row }"><div class="cell-stack update-info"><span :title="row.updated_by_name ? '更新人' : '创建人'">{{ row.updated_by_name || row.created_by_name || '—' }}</span><small>{{ formatDateTime(row.updated_at || row.created_at) }}</small></div></template>
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
        <footer class="list-card__footer">
          <span>共 {{ listReady ? total : '—' }} 条</span>
          <ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]"
            :pager-count="5" layout="sizes, prev, pager, next" background @current-change="loadList" @size-change="search" />
        </footer>
      </section>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as crm;
@use '@/styles/crm/mixins' as mixin;

.purchase-list-page {
  box-sizing: border-box; width: 100%; height: calc(100dvh - 92px); min-width: 0;
  display: flex; flex-direction: column; padding: 28px 28px 18px;
  color: crm.$crm-text-primary; background: crm.$crm-color-page; font: 14px/1.5 crm.$crm-font-body;
  --el-color-primary: #{crm.$crm-primary}; --el-color-primary-light-3: #{crm.$crm-primary-light-3};
  --el-color-primary-light-9: #{crm.$crm-color-selected}; --el-text-color-primary: #{crm.$crm-text-primary};
  --el-text-color-regular: #{crm.$crm-text-secondary}; --el-border-color: #{crm.$crm-border-default};
  --el-fill-color-blank: #{crm.$crm-color-surface}; --el-fill-color-light: #{crm.$crm-color-subtle};
  --el-border-radius-base: 5px;
  --el-text-color-placeholder: #{crm.$crm-text-muted};
  --el-text-color-disabled: #{crm.$crm-text-disabled};
}
.page-heading { flex: 0 0 50px; display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.page-heading__title { display: flex; align-items: center; gap: 30px; min-width: 0; }
.page-heading h1 { margin: 0; font: 700 38px/50px crm.$crm-font-display; letter-spacing: -1px; white-space: nowrap; }
.page-heading__count { color: crm.$crm-text-secondary; white-space: nowrap; }
.page-heading__actions { display: flex; align-items: center; gap: 16px; }
.page-heading__actions :deep(.el-button + .el-button) { margin-left: 0; }
.page-heading__actions :deep(.el-button) { height: 40px; }
.create-button { width: 164px; }
.supplier-button { width: 144px; color: crm.$crm-text-primary; }
.supplier-button :deep(> span) { display: flex; align-items: center; gap: 8px; }
.filter-section { flex: none; margin-top: 12px; }
.filter-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; min-height: 32px; }
.keyword-filter { width: 250px; min-width: 250px; flex: none; }
.supplier-filter { width: 180px; flex: none; }
.status-filter { width: 160px; flex: none; }
.return-filter { width: 150px; flex: none; }
.more-filters-button { width: 112px; height: 32px; margin: 0; color: crm.$crm-text-secondary; }
.purchase-list-actions { flex: none; display: flex; align-items: center; gap: 8px; margin-left: auto; }
.purchase-list-actions :deep(.el-button) { height: 32px; margin: 0; padding: 0 12px; }
.purchase-search-button { @include mixin.reset-button; display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 24px; cursor: pointer; }
.purchase-search-button:focus-visible { @include mixin.focus-ring; }
.filter-row :deep(.el-input__wrapper), .filter-row :deep(.el-select__wrapper) { min-height: 32px; box-shadow: 0 0 0 1px crm.$crm-border-default inset; }
.filter-row :deep(.el-input__inner), .filter-row :deep(.el-select__placeholder) { font-size: 14px; }
.extra-filters { display: flex; align-items: center; gap: 16px; padding-top: 12px; }
.extra-filters :deep(.el-select) { width: 300px; }
.extra-filters :deep(.el-date-editor) { width: 207px; flex: none; }
.load-error { flex: none; margin-top: 8px; }
.list-card { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; margin-top: 8px; outline: 1px solid crm.$crm-border-default; outline-offset: -1px; border-radius: 5px; background: crm.$crm-color-surface; }
.purchase-table { min-height: 0; flex: 1; --el-table-border-color: #{crm.$crm-border-subtle}; --el-table-row-hover-bg-color: #{crm.$crm-color-row-hover}; --el-table-header-bg-color: #{crm.$crm-color-subtle}; --el-table-tr-bg-color: #{crm.$crm-color-surface}; --el-table-bg-color: #{crm.$crm-color-surface}; }
.purchase-list-page .purchase-table :deep(.el-table__header th.el-table__cell) { height: 48px; padding: 0; color: crm.$crm-text-secondary; background: crm.$crm-color-subtle; font-size: 12px; font-weight: 400; border-right: 1px solid crm.$crm-border-subtle; }
.purchase-list-page .purchase-table :deep(.el-table__body td.el-table__cell) { height: 53.333333px; padding: 0; border-right: 1px solid crm.$crm-border-subtle; color: crm.$crm-text-primary; font-size: 14px; }
.purchase-list-page .purchase-table :deep(.cell) { padding: 0 12px; line-height: 21px; font-size: 14px; }
.purchase-list-page .purchase-table :deep(th .cell) { font-size: 12px; }
.purchase-table :deep(.el-table__inner-wrapper::before) { display: none; }
.cell-stack { min-width: 0; display: flex; flex-direction: column; line-height: 21px; }
.cell-stack > * { @include mixin.text-ellipsis; }
.cell-stack small { color: crm.$crm-text-secondary; font-size: 14px; }
.product-summary strong, .order-number { font-weight: 600; }
.order-summary > span { font-weight: 500; }
.product-summary:focus-visible { @include mixin.focus-ring; }
.product-tooltip-content { max-width: 440px; max-height: 420px; overflow: auto; white-space: pre-line; }
.amount, .order-number { font-variant-numeric: tabular-nums; white-space: nowrap; }
.amount { font-weight: 500; }
.amount--pending { box-sizing: border-box; display: inline-flex; justify-content: center; align-items: center; min-width: 56px; height: 24px; padding: 0 8px; border-radius: 999px; background: #5e5d59; color: #faf9f5; font: 500 12px/18px 'Noto Sans SC Variable', crm.$crm-font-body; }
.update-info small { color: crm.$crm-text-primary; }
.status-badge { box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; min-width: 88px; height: 24px; padding: 0 8px; border-radius: 999px; color: #faf9f5; font: 500 12px/18px 'Noto Sans SC Variable', crm.$crm-font-body; white-space: nowrap; }
.status-badge.is-purchasing { background: crm.$crm-primary; }
.status-badge.is-confirmed { background: crm.$crm-info; }
.status-badge.is-draft { background: #5e5d59; }
.status-badge.is-completed { background: crm.$crm-success; }
.purchase-source-tag { box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; width: 72px; height: 24px; padding: 0 8px; border: 0; border-radius: 999px; color: #faf9f5; background: crm.$crm-info; font: 500 12px/18px 'Noto Sans SC Variable', crm.$crm-font-body; white-space: nowrap; }
.purchase-source-tag.is-sample { background: #c96442; }
.inbound-summary { box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; max-width: 100%; min-height: 24px; padding: 2px 9px; border-radius: 999px; color: crm.$crm-text-inverse; background: crm.$crm-neutral; font-size: 12px; line-height: 18px; }
.inbound-summary.inbound-PENDING_RECEIPT, .inbound-summary.inbound-PARTIAL_RECEIVED { background: crm.$crm-primary; }
.inbound-summary.inbound-PENDING_QUALITY { background: crm.$crm-warning; }
.inbound-summary.inbound-PENDING_PROCUREMENT_CONFIRMATION, .inbound-summary.inbound-RETURN_RECORD_MISSING { background: crm.$crm-danger; }
.inbound-summary.inbound-PENDING_RETURN { background: crm.$crm-info; }
.inbound-summary.inbound-CONFIRMED, .inbound-summary.inbound-COMPLETED { background: crm.$crm-success; }
.inbound-summary.inbound-NOT_STARTED, .inbound-summary.muted { min-width: 0; padding: 0; color: crm.$crm-text-muted; background: transparent; }
.row-actions { display: flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; }
.row-more-button { color: crm.$crm-text-secondary; width: 36px; height: 32px; }
.muted { color: crm.$crm-text-muted; }
.purchase-list-page .list-card__footer { height: auto !important; min-height: 48px; flex: none; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 16px !important; border-top: 1px solid crm.$crm-border-subtle; color: crm.$crm-text-secondary; font-size: 14px; }
.list-card__footer :deep(.el-pagination) { min-width: 0; max-width: 100%; flex-wrap: wrap; justify-content: flex-end; margin-left: auto; gap: 16px; --el-pagination-button-bg-color: #{crm.$crm-color-surface}; --el-pagination-button-color: #{crm.$crm-text-secondary}; }
.list-card__footer :deep(.el-pagination__sizes) { margin: 0 8px 0 0; }
.list-card__footer :deep(.el-select) { width: 136px; }
.list-card__footer :deep(.el-select__wrapper) { min-height: 42px; }
.list-card__footer :deep(.btn-prev), .list-card__footer :deep(.btn-next), .list-card__footer :deep(.el-pager li) { min-width: 46px; height: 42px; border: 1px solid crm.$crm-border-default; border-radius: 5px; font-weight: 400; }
.list-card__footer :deep(.el-pager) { gap: 10px; }
.list-card__footer :deep(.el-pager li.is-active) { color: crm.$crm-primary; border-color: crm.$crm-primary; background: crm.$crm-color-surface; }
.empty-state { display: flex; min-height: 300px; flex-direction: column; align-items: center; justify-content: center; color: crm.$crm-text-secondary; }
.empty-state strong { font-size: 18px; color: crm.$crm-text-primary; }
.empty-state p { margin: 8px 0 16px; }
.state-page { flex: 1; display: grid; place-content: center; text-align: center; }
.state-page h2 { margin: 0 0 8px; }
.state-page p { margin: 0; color: crm.$crm-text-secondary; }
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
