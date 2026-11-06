<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { fetchPurchaseTrackingArrivals, fetchPurchaseTrackingCoverage, fetchPurchaseTrackingFilterOptions } from '@/api/purchaseTracking'
import { useAuthStore } from '@/stores/auth'
import { materialAttributeFields } from '@/utils/materialAttributes'
import { formatTime } from './purchaseOrderDetailDisplay'
import PurchaseTrackingPolicyDialog from './PurchaseTrackingPolicyDialog.vue'
import type { PurchaseTrackingAction, PurchaseTrackingArrival, PurchaseTrackingCoverage, PurchaseTrackingFilterOptions, PurchaseTrackingQuery, PurchaseTrackingRiskCode, PurchaseTrackingRow, PurchaseTrackingTab } from '@/types/purchaseTracking'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const canView = computed(() => auth.user?.is_superuser === true || auth.hasPermission('procurement.view_purchaseorder'))
const canManagePolicy = computed(() => auth.user?.is_superuser === true || auth.managementCan('access_control.manage_notifications'))
const policyVisible = ref(false)

const riskOptions: Record<PurchaseTrackingTab, { value: PurchaseTrackingRiskCode; label: string }[]> = {
  arrival: [
    { value: 'NEAR_DUE', label: '临近交期' }, { value: 'DUE_TODAY', label: '今天到期' },
    { value: 'OVERDUE', label: '已逾期' }, { value: 'DELIVERY_UNKNOWN', label: '交期待核对' },
    { value: 'ARRIVAL_UNKNOWN', label: '到货数据待核对' }, { value: 'CLASSIFICATION_UNKNOWN', label: '分类待核对' },
    { value: 'RETURN_PENDING', label: '退货待处理' }, { value: 'ENDED', label: '已结束 / 历史' },
  ],
  coverage: [
    { value: 'PURCHASE_OVERDUE', label: '超过最晚采购日' }, { value: 'PURCHASE_DUE_TODAY', label: '今天须采购' },
    { value: 'BOM_PURCHASE_TIMEOUT', label: 'BOM确认后采购超时' }, { value: 'PURCHASE_UPCOMING', label: '未到最晚采购日' },
    { value: 'BOM_CONFIRMATION_UNKNOWN', label: 'BOM确认时间待核对' }, { value: 'SCHEDULE_DATE_UNKNOWN', label: '排产入库日待核对' },
    { value: 'ORDER_DELIVERY_UNKNOWN', label: '订单交期待核对' }, { value: 'PURCHASE_RULE_UNKNOWN', label: '规则待设置' },
    { value: 'SCHEDULED_UNPURCHASED', label: '已排产未采购' }, { value: 'SCHEDULED_SHORT', label: '已排产未买足' },
    { value: 'PENDING_PURCHASE', label: '普通待采购' }, { value: 'DEMAND_UNKNOWN', label: '需求待核对' },
    { value: 'DEMAND_CHANGED', label: '需求变化待核对' },
  ],
}

function queryText(key: string): string {
  const value = route.query[key]
  return typeof value === 'string' ? value : ''
}

function positiveInteger(value: string, fallback: number, max = Number.MAX_SAFE_INTEGER): number {
  return /^\d+$/.test(value) && Number(value) >= 1 && Number(value) <= max ? Number(value) : fallback
}

// 菜单入口已经是两个独立路由；保留旧的 tab 参数只用于兼容历史站内消息链接。
const mode = computed<PurchaseTrackingTab>(() => route.name === 'purchase-alerts' || queryText('tab') === 'coverage' ? 'coverage' : 'arrival')
const pageTitle = computed(() => mode.value === 'arrival' ? '采购跟踪' : '采购提醒')
const taskId = computed(() => queryText('production_task_id'))
const rowKey = computed(() => queryText('row_key'))
const risk = computed(() => riskOptions[mode.value].find(item => item.value === queryText('risk'))?.value ?? '')
const includeHistory = computed(() => queryText('include_history') === 'true' || queryText('include_history') === '1' || risk.value === 'ENDED')
const currentPage = computed(() => positiveInteger(queryText('page'), 1))
const pageSize = computed(() => positiveInteger(queryText('page_size'), 20, 100))
const arrivals = ref<PurchaseTrackingArrival[]>([])
const coverage = ref<PurchaseTrackingCoverage[]>([])
const hoveredMaterialRow = shallowRef<PurchaseTrackingArrival | PurchaseTrackingCoverage>()
const hoveredMaterialCell = shallowRef<HTMLElement>()
const hoveredMaterialFields = computed(() => hoveredMaterialRow.value ? materialAttributeFields(hoveredMaterialRow.value) : [])
const tasks = ref<PurchaseTrackingFilterOptions['production_tasks']>([])
const total = ref(0)
const loading = ref(false)
const loaded = ref(false)
const errorMessage = ref('')
const optionsError = ref('')
const actionError = ref('')
const panel = ref<HTMLElement>()
let requestVersion = 0
let requestController: AbortController | undefined
let optionsController: AbortController | undefined
let disposed = false

const hasFilter = computed(() => Boolean(taskId.value || risk.value || rowKey.value || includeHistory.value))
const emptyMessage = computed(() => rowKey.value
  ? '当前定位记录不可见、已结束或状态已变化，请清除定位后查看当前清单。'
  : hasFilter.value ? '当前筛选下暂无未完成记录' : mode.value === 'arrival' ? '暂无未到齐批次' : '暂无待采购物料')

function errorText(error: unknown, fallback: string): string {
  const response = (error as { response?: { status?: number; data?: { error?: { message?: string } } } })?.response
  if (response?.status === 403) return '当前账号无权查看这些采购记录，请检查权限后重试。'
  return response?.data?.error?.message || fallback
}

function updateQuery(changes: LocationQueryRaw): void {
  const next: LocationQueryRaw = { ...route.query, ...changes, tab: undefined }
  for (const key of Object.keys(next)) if (next[key] === '' || next[key] === undefined || next[key] === null) delete next[key]
  const name = mode.value === 'coverage' ? 'purchase-alerts' : 'purchase-tracking'
  void router.push({ name, query: next })
}

function filterTask(value: string | undefined): void { updateQuery({ production_task_id: value || undefined, row_key: undefined, page: undefined }) }
function filterRisk(value: string | undefined): void { updateQuery({ risk: value || undefined, row_key: undefined, page: undefined }) }
function filterHistory(value: boolean | string | number): void { updateQuery({ include_history: value ? 'true' : undefined, page: undefined, row_key: undefined }) }
function resetFilters(): void { updateQuery({ production_task_id: undefined, risk: undefined, include_history: undefined, row_key: undefined, page: undefined }) }
function applyFilters(): void { void load() }
function changePage(value: number): void { if (value !== currentPage.value) updateQuery({ page: String(value) }) }
function changePageSize(value: number): void { if (value !== pageSize.value) updateQuery({ page_size: String(value), page: undefined }) }

async function load(): Promise<void> {
  const version = ++requestVersion
  requestController?.abort()
  hideMaterialAttributes()
  arrivals.value = []
  coverage.value = []
  total.value = 0
  loaded.value = false
  errorMessage.value = ''
  actionError.value = ''
  if (!canView.value) { loading.value = false; return }
  requestController = new AbortController()
  loading.value = true
  const query: PurchaseTrackingQuery = {
    page: currentPage.value,
    page_size: pageSize.value,
    ...(taskId.value ? { production_task_id: taskId.value } : {}),
    ...(risk.value ? { risk: risk.value } : {}),
    ...(includeHistory.value ? { include_history: true } : {}),
    ...(rowKey.value ? { row_key: rowKey.value } : {}),
  }
  const requestedMode = mode.value
  try {
    if (requestedMode === 'arrival') {
      const result = await fetchPurchaseTrackingArrivals(query, requestController.signal)
      if (version !== requestVersion) return
      arrivals.value = result.data
      total.value = result.meta.total
    } else {
      const result = await fetchPurchaseTrackingCoverage(query, requestController.signal)
      if (version !== requestVersion) return
      coverage.value = result.data
      total.value = result.meta.total
    }
    loaded.value = true
    await nextTick()
    if (version !== requestVersion || !rowKey.value) return
    const row = panel.value?.querySelector<HTMLElement>('.is-located')
    row?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
    row?.focus({ preventScroll: true })
  } catch (error) {
    if (version === requestVersion) errorMessage.value = errorText(error, `${pageTitle.value}加载失败，请重试。`)
  } finally {
    if (version === requestVersion) loading.value = false
  }
}

async function loadOptions(): Promise<void> {
  optionsController?.abort()
  optionsError.value = ''
  tasks.value = []
  if (!canView.value) return
  const controller = new AbortController()
  optionsController = controller
  try {
    const result = await fetchPurchaseTrackingFilterOptions(controller.signal)
    if (!disposed && !controller.signal.aborted) tasks.value = result.production_tasks
  } catch (error) {
    if (!disposed && !controller.signal.aborted) optionsError.value = errorText(error, '生产订单筛选选项加载失败。')
  }
}

// 仅排版十进制字符串，不使用浮点重算数量，也不把未知量补成 0。
function quantity(value: string | null, unit: string | null): string {
  if (value === null) return '—'
  if (!/^-?\d+(?:\.\d+)?$/.test(value)) return '待核对'
  const [integer = '', fraction = ''] = value.split('.')
  const decimals = fraction.replace(/0+$/, '')
  const formatted = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (decimals ? `.${decimals}` : '')
  return `${formatted} ${unit || '（单位待核对）'}`
}
function arrivalQuantity(row: PurchaseTrackingArrival, field: 'ordered' | 'received' | 'unreceived'): string {
  const useRoots = [row.ordered_root_count, row.received_root_count, row.unreceived_root_count].every(value => value !== null)
  return quantity(useRoots ? row[`${field}_root_count`] : row[`${field}_quantity`], useRoots ? '根' : row.unit)
}
function coverageQuantity(row: PurchaseTrackingCoverage, field: 'required' | 'purchased' | 'remaining'): string {
  const useRoots = [row.required_root_count, row.purchased_root_count, row.remaining_root_count].every(value => value !== null)
  return quantity(useRoots ? row[`${field}_root_count`] : row[`${field}_quantity`], useRoots ? '根' : row.unit)
}
function bomTimingText(row: PurchaseTrackingCoverage): string {
  return `BOM创建：${formatTime(row.bom_created_at)}；BOM确认：${formatTime(row.bom_confirmed_at)}；采购提醒起点：${formatTime(row.bom_purchase_due_at)}`
}
function hideMaterialAttributes(): void { hoveredMaterialRow.value = undefined }
function showMaterialAttributes(row: PurchaseTrackingArrival | PurchaseTrackingCoverage, column: { label: string }, cell: HTMLElement): void {
  // 合并列无法唯一对应某个材料；日期、状态列继续保留各自提示。
  if (!['材料', '品名', '规格', '采购数量', '实际收货', '合格数量', '待检数量', '退货数量', '未到数量', '需求数量', '已确认采购', '待采购'].includes(column.label)) {
    hideMaterialAttributes()
    return
  }
  hoveredMaterialCell.value = cell
  hoveredMaterialRow.value = row
}
function focusMaterialAttributes(row: PurchaseTrackingArrival | PurchaseTrackingCoverage, event: FocusEvent): void {
  if (event.currentTarget instanceof HTMLElement) {
    hoveredMaterialCell.value = event.currentTarget
    hoveredMaterialRow.value = row
  }
}
function hasReturn(row: PurchaseTrackingArrival): boolean { return row.return_pending || (row.return_quantity !== null && !/^0(?:\.0+)?$/.test(row.return_quantity)) }
function isDanger(row: PurchaseTrackingRow): boolean { return row.risks.some(item => item.level === 'danger') }
function arrivalRiskTag(row: PurchaseTrackingArrival) {
  const codes = row.risks.map(item => item.code)
  if (codes.includes('OVERDUE') || codes.includes('DUE_TODAY')) return { type: 'danger', effect: 'dark' } as const
  if (codes.includes('NEAR_DUE') && row.days_remaining === 1) return { type: 'warning', effect: 'dark' } as const
  const type = isDanger(row) ? 'danger' : row.risks.some(item => item.level === 'warning') ? 'warning' : row.risks.some(item => item.level === 'success') ? 'success' : 'info'
  return { type, effect: 'light' } as const
}
function arrivalRiskText(row: PurchaseTrackingArrival): string {
  // 退货风险可能排在临期风险前，交期状态优先露出倒计时，完整保留其他提示。
  const deadline = row.risks.find(item => ['OVERDUE', 'DUE_TODAY', 'NEAR_DUE'].includes(item.code))
  return riskText(deadline ? { ...row, risks: [deadline, ...row.risks.filter(item => item !== deadline)] } : row)
}
function coverageRiskTag(row: PurchaseTrackingCoverage) {
  const codes = row.risks.map(item => item.code)
  if (codes.includes('PURCHASE_OVERDUE') || codes.includes('PURCHASE_DUE_TODAY')) return { type: 'danger', effect: 'dark' } as const
  if (codes.some(code => ['BOM_CONFIRMATION_UNKNOWN', 'SCHEDULE_DATE_UNKNOWN', 'ORDER_DELIVERY_UNKNOWN', 'PURCHASE_RULE_UNKNOWN'].includes(code))
    || (codes.includes('PURCHASE_UPCOMING') && row.purchase_days_remaining === 1)) return { type: 'warning', effect: 'dark' } as const
  if (codes.includes('PURCHASE_UPCOMING')) return { type: 'warning', effect: 'light' } as const
  const type = isDanger(row) ? 'danger' : row.risks.some(item => item.level === 'warning') ? 'warning' : row.risks.some(item => item.level === 'success') ? 'success' : 'info'
  return { type, effect: 'light' } as const
}
function coverageRiskText(row: PurchaseTrackingCoverage): string {
  const primary = row.risks.find(item => ['PURCHASE_OVERDUE', 'PURCHASE_DUE_TODAY'].includes(item.code))
    || row.risks.find(item => item.code.endsWith('_UNKNOWN') || item.code === 'DEMAND_CHANGED')
    || row.risks.find(item => item.code === 'PURCHASE_UPCOMING')
  return riskText(primary ? { ...row, risks: [primary, ...row.risks.filter(item => item !== primary)] } : row)
}
function riskText(row: PurchaseTrackingRow): string {
  const labels = row.risks.map(item => item.label)
  if (!row.source_reliable && !row.verification_notes.length) labels.push('来源待核对')
  labels.push(...row.verification_notes)
  return labels.length ? labels.join('、') : '—'
}
function localAction(action: PurchaseTrackingAction): boolean {
  if (!action.path.startsWith('/') || action.path.startsWith('//') || /[\\\u0000-\u001f]/.test(action.path) || /%5c/i.test(action.path)) return false
  const target = router.resolve(action.path)
  return Boolean(target.matched.length && target.name !== 'not-found' && !target.matched.some(record => record.path.includes(':pathMatch')))
}
function actionsFor(row: PurchaseTrackingRow): PurchaseTrackingAction[] { return row.actions.filter(localAction) }
async function openAction(action: PurchaseTrackingAction): Promise<void> {
  if (!localAction(action)) return
  actionError.value = ''
  try { await router.push(action.path) } catch { actionError.value = '无法打开采购入口，请重试。' }
}
function showAction(row: PurchaseTrackingRow): boolean { return actionsFor(row).length > 0 }
function showActionBlocked(row: PurchaseTrackingRow): boolean { return !showAction(row) && Boolean(row.action_blocked_reason) }
function rowClassName({ row }: { row: PurchaseTrackingRow }): string { return row.row_key === rowKey.value ? 'is-located' : '' }
function arrivalGroupKey(row: PurchaseTrackingArrival): string { return `${row.purchase_order_no}\u0000${row.supplier_name}` }
function arrivalSpanMethod({ row, column, rowIndex }: { row: PurchaseTrackingArrival; column: { property?: string }; rowIndex: number }): [number, number] | undefined {
  if (!['task_number', 'purchase_order_no', 'supplier_name'].includes(column.property || '')) return undefined
  const rows = arrivals.value
  const groupKey = column.property === 'task_number' ? (item: PurchaseTrackingArrival) => item.production_task_id : arrivalGroupKey
  const key = groupKey(row)
  if (rowIndex > 0 && groupKey(rows[rowIndex - 1]!) === key) return [0, 0]
  let span = 1
  while (rowIndex + span < rows.length && groupKey(rows[rowIndex + span]!) === key) span += 1
  return [span, 1]
}

function coverageSpanMethod({ row, column, rowIndex }: { row: PurchaseTrackingCoverage; column: { property?: string }; rowIndex: number }): [number, number] | undefined {
  if (column.property !== 'task_number') return undefined
  const rows = coverage.value
  if (rowIndex > 0 && rows[rowIndex - 1]!.production_task_id === row.production_task_id) return [0, 0]
  let span = 1
  while (rowIndex + span < rows.length && rows[rowIndex + span]!.production_task_id === row.production_task_id) span += 1
  return [span, 1]
}

watch(() => [route.fullPath, canView.value], () => { void load() }, { immediate: true })
watch(canView, () => { void loadOptions() }, { immediate: true })
watch(() => [mode.value, canView.value, canManagePolicy.value], () => { policyVisible.value = false })
onBeforeUnmount(() => { disposed = true; requestVersion++; requestController?.abort(); optionsController?.abort() })
</script>

<template>
  <section class="purchase-tracking-page erp-glass-list" data-testid="purchase-tracking-page">
    <section class="erp-list-filter">
      <header class="page-heading erp-list-heading">
        <div class="page-heading__title">
          <h1>{{ pageTitle }}</h1>
          <span class="page-heading__count">共 {{ canView && loaded ? total : '—' }} 条</span>
        </div>
      </header>
      <section v-if="canView" class="filter-section" :aria-label="`${pageTitle}筛选`">
        <form class="filter-row erp-list-filters" @submit.prevent="applyFilters">
          <ElSelect :model-value="taskId" filterable clearable class="task-filter" placeholder="生产订单：全部" aria-label="生产订单筛选" @update:model-value="filterTask">
            <ElOption v-for="task in tasks" :key="task.id" :value="task.id" :label="[task.task_number, task.order_number].filter(Boolean).join(' · ')" />
          </ElSelect>
          <ElSelect :model-value="risk" clearable class="risk-filter" placeholder="提醒：全部" aria-label="提醒筛选" @update:model-value="filterRisk">
            <ElOption v-for="option in riskOptions[mode]" :key="option.value" :value="option.value" :label="option.label" />
          </ElSelect>
          <ElCheckbox v-if="mode === 'coverage'" :model-value="includeHistory" @update:model-value="filterHistory">包含历史记录</ElCheckbox>
          <div class="erp-list-filter-actions">
            <ElButton class="erp-button-motion" @click="resetFilters">重置</ElButton>
            <ElButton class="erp-button-motion" type="primary" native-type="submit">应用筛选</ElButton>
          </div>
        </form>
      </section>
    </section>

    <div v-if="!canView" class="state-page">
      <h2>无权查看{{ pageTitle }}</h2>
      <p>需要采购订单查看权限及对应任务的数据范围。</p>
    </div>

    <template v-else>
      <ElAlert v-if="optionsError" class="load-error" type="warning" :title="optionsError" :closable="false" show-icon>
        <ElButton link @click="loadOptions">重试选项</ElButton>
      </ElAlert>
      <ElAlert v-if="errorMessage" class="load-error" type="error" :title="errorMessage" :closable="false" show-icon>
        <ElButton link data-testid="retry-tracking" @click="load">重新加载</ElButton>
      </ElAlert>
      <ElAlert v-if="actionError" class="load-error" type="error" :title="actionError" :closable="false" show-icon />
      <div v-if="rowKey" class="tracking-location" role="status">正在定位消息关联记录<ElButton link data-testid="clear-tracking-location" @click="updateQuery({ row_key: undefined, page: undefined })">清除定位</ElButton></div>

      <section class="list-card erp-list-data" :aria-label="`${pageTitle}清单`">
        <div class="erp-list-toolbar">
          <span class="list-toolbar-hint" :title="mode === 'coverage' ? 'BOM确认后超时未买足提醒；已排产按最晚采购日判断紧急程度，缺日期单独提示。已确认采购不代表到货或齐料。' : undefined">{{ mode === 'arrival' ? '未到齐批次' : '未采购或未买足 · 紧急订单优先' }}</span>
          <div class="tracking-toolbar-actions">
            <ElButton v-if="mode === 'coverage' && canManagePolicy" class="erp-button-motion" data-testid="open-tracking-policy" @click="policyVisible = true">提醒设置</ElButton>
            <ElButton class="erp-button-motion" :disabled="loading" data-testid="refresh-tracking" @click="load">刷新</ElButton>
          </div>
        </div>
        <div ref="panel" class="erp-list-table-frame" :aria-busy="loading" @scroll.capture="hideMaterialAttributes">
          <ElTable v-if="mode === 'arrival'" v-loading="loading" :data="arrivals" row-key="row_key" :row-class-name="rowClassName" :span-method="arrivalSpanMethod" class="tracking-table arrival-table" height="100%" @cell-mouse-enter="showMaterialAttributes" @cell-mouse-leave="hideMaterialAttributes" @mouseleave="hideMaterialAttributes">
            <ElTableColumn prop="task_number" label="生产订单号" width="132" show-overflow-tooltip><template #default="{ row }"><span class="tracking-cell tracking-strong">{{ row.task_number }}</span></template></ElTableColumn>
            <ElTableColumn label="产品" width="150" show-overflow-tooltip><template #default="{ row }"><span class="tracking-cell">{{ row.product_name || '产品待核对' }}</span></template></ElTableColumn>
            <ElTableColumn prop="purchase_order_no" label="订单号" width="154" show-overflow-tooltip><template #default="{ row }"><span class="tracking-cell tracking-strong">{{ row.purchase_order_no }}</span></template></ElTableColumn>
            <ElTableColumn prop="supplier_name" label="供应商" width="150" show-overflow-tooltip><template #default="{ row }"><span class="tracking-cell">{{ row.supplier_name || '供应商待核对' }}</span></template></ElTableColumn>
            <ElTableColumn label="采购批次" width="108" align="center"><template #default="{ row }"><span class="tracking-cell">{{ row.batch_number === null ? '待核对' : `第${row.batch_number}批` }}</span></template></ElTableColumn>
            <ElTableColumn label="材料" min-width="150"><template #default="{ row }"><span class="tracking-cell" tabindex="0" data-testid="arrival-material-name" :aria-label="`查看材料属性：${row.material_name || '材料待核对'}`" @focus="focusMaterialAttributes(row, $event)" @blur="hideMaterialAttributes" @keydown.esc="hideMaterialAttributes">{{ row.material_name || '材料待核对' }}</span></template></ElTableColumn>
            <ElTableColumn label="规格" width="150"><template #default="{ row }"><span class="tracking-cell" tabindex="0" data-testid="arrival-specification" :aria-label="`查看材料属性：${row.material_name || '材料待核对'}`" @focus="focusMaterialAttributes(row, $event)" @blur="hideMaterialAttributes" @keydown.esc="hideMaterialAttributes">{{ row.specification || '—' }}</span></template></ElTableColumn>
            <ElTableColumn label="采购数量" width="120" align="right"><template #default="{ row }"><span class="tracking-cell tracking-number">{{ arrivalQuantity(row, 'ordered') }}</span></template></ElTableColumn>
            <ElTableColumn label="实际收货" width="120" align="right"><template #default="{ row }"><span class="tracking-cell tracking-number">{{ arrivalQuantity(row, 'received') }}</span></template></ElTableColumn>
            <ElTableColumn label="合格数量" width="120" align="right"><template #default="{ row }"><span class="tracking-cell tracking-number">{{ quantity(row.accepted_quantity, row.unit) }}</span></template></ElTableColumn>
            <ElTableColumn label="待检数量" width="120" align="right"><template #default="{ row }"><span class="tracking-cell tracking-number">{{ quantity(row.pending_quality_quantity, row.unit) }}</span></template></ElTableColumn>
            <ElTableColumn label="退货数量" width="120" align="right"><template #default="{ row }"><span class="tracking-cell tracking-number">{{ hasReturn(row) ? quantity(row.return_quantity, row.unit) : '0' }}</span></template></ElTableColumn>
            <ElTableColumn label="未到数量" width="120" align="right"><template #default="{ row }"><span class="tracking-cell tracking-number" :class="{ 'risk-danger': isDanger(row) }">{{ arrivalQuantity(row, 'unreceived') }}</span></template></ElTableColumn>
            <ElTableColumn label="采购交期" width="112" fixed="right" show-overflow-tooltip><template #default="{ row }"><span class="tracking-cell">{{ row.delivery_date || '待核对' }}</span></template></ElTableColumn>
            <ElTableColumn label="交期状态" width="150" fixed="right" show-overflow-tooltip><template #default="{ row }"><ElTag v-bind="arrivalRiskTag(row)" disable-transitions class="tracking-risk-tag" :title="arrivalRiskText(row)" data-testid="arrival-delivery-status"><span class="tracking-cell">{{ arrivalRiskText(row) }}</span></ElTag></template></ElTableColumn>
            <ElTableColumn label="操作" width="144" fixed="right"><template #default="{ row }"><div class="tracking-actions"><ElButton v-for="action in actionsFor(row)" :key="action.kind + action.path" link type="primary" @click="openAction(action)">{{ action.label }}</ElButton><span v-if="showActionBlocked(row)" class="muted" :title="row.action_blocked_reason">受限</span><span v-if="!showAction(row) && !showActionBlocked(row)" class="muted">—</span></div></template></ElTableColumn>
            <template #empty><div class="empty-state"><strong>{{ errorMessage ? `采购跟踪加载失败` : loading ? '正在加载采购跟踪' : emptyMessage }}</strong><p>{{ errorMessage ? '请重新加载后再试。' : '已到齐批次不会显示在这里。' }}</p><ElButton v-if="errorMessage" @click="load">重新加载</ElButton></div></template>
          </ElTable>

          <ElTable v-else v-loading="loading" :data="coverage" row-key="row_key" :row-class-name="rowClassName" :span-method="coverageSpanMethod" class="tracking-table coverage-table" height="100%" @cell-mouse-enter="showMaterialAttributes" @cell-mouse-leave="hideMaterialAttributes" @mouseleave="hideMaterialAttributes">
            <ElTableColumn prop="task_number" label="生产订单号" width="120" show-overflow-tooltip><template #default="{ row }"><span class="tracking-cell tracking-strong">{{ row.task_number }}</span></template></ElTableColumn>
            <ElTableColumn label="产品" width="110" show-overflow-tooltip><template #default="{ row }"><span class="tracking-cell">{{ row.product_name || '产品待核对' }}</span></template></ElTableColumn>
            <ElTableColumn label="BOM创建时间" width="156" show-overflow-tooltip><template #default="{ row }"><span class="tracking-cell" :title="bomTimingText(row)">{{ formatTime(row.bom_created_at) }}</span></template></ElTableColumn>
            <ElTableColumn label="订单交期" width="112" show-overflow-tooltip><template #default="{ row }"><span v-if="row.order_delivery_date" class="tracking-cell">{{ row.order_delivery_date }}</span><ElTag v-else type="warning" effect="dark" disable-transitions class="tracking-risk-tag" title="订单交期未填写，需核对补充" data-testid="coverage-order-date-missing">缺交期</ElTag></template></ElTableColumn>
            <ElTableColumn label="品名" min-width="150"><template #default="{ row }"><span class="tracking-cell" tabindex="0" data-testid="coverage-material-name" :aria-label="`查看材料属性：${row.material_name || '材料待核对'}`" @focus="focusMaterialAttributes(row, $event)" @blur="hideMaterialAttributes" @keydown.esc="hideMaterialAttributes">{{ row.material_name || '材料待核对' }}</span></template></ElTableColumn>
            <ElTableColumn label="规格" width="110"><template #default="{ row }"><span class="tracking-cell" tabindex="0" data-testid="coverage-specification" :aria-label="`查看材料属性：${row.material_name || '材料待核对'}`" @focus="focusMaterialAttributes(row, $event)" @blur="hideMaterialAttributes" @keydown.esc="hideMaterialAttributes">{{ row.specification || '—' }}</span></template></ElTableColumn>
            <ElTableColumn label="需求数量" width="96" align="right"><template #default="{ row }"><span class="tracking-cell tracking-number">{{ coverageQuantity(row, 'required') }}</span></template></ElTableColumn>
            <ElTableColumn label="已确认采购" width="104" align="right"><template #default="{ row }"><span class="tracking-cell tracking-number">{{ coverageQuantity(row, 'purchased') }}</span></template></ElTableColumn>
            <ElTableColumn label="待采购" width="96" align="right"><template #default="{ row }"><span class="tracking-cell tracking-number risk-danger">{{ coverageQuantity(row, 'remaining') }}</span></template></ElTableColumn>
            <ElTableColumn label="排产材料入库日" width="136" show-overflow-tooltip><template #default="{ row }"><ElTag v-if="row.scheduled && !row.material_inbound_date" type="warning" effect="dark" disable-transitions class="tracking-risk-tag" title="已排产但缺少材料入库日，无法计算最晚采购日" data-testid="coverage-schedule-date-missing">缺日期</ElTag><span v-else class="tracking-cell">{{ row.material_inbound_date || '未排产' }}</span></template></ElTableColumn>
            <ElTableColumn label="最晚采购日" width="112" show-overflow-tooltip><template #default="{ row }"><ElTag v-if="row.scheduled && !row.latest_purchase_date" type="warning" effect="dark" disable-transitions class="tracking-risk-tag" :title="riskText(row)" data-testid="coverage-purchase-date-missing"><span class="tracking-cell">{{ row.material_inbound_date ? '待核对' : '缺日期' }}</span></ElTag><span v-else class="tracking-cell" :class="{ 'risk-danger': row.purchase_days_remaining !== null && row.purchase_days_remaining <= 0 }">{{ row.latest_purchase_date || '未排产' }}</span></template></ElTableColumn>
            <ElTableColumn label="采购总单" width="100" show-overflow-tooltip><template #default="{ row }"><span class="tracking-cell">{{ row.group_status || '来源待核对' }}</span></template></ElTableColumn>
            <ElTableColumn label="提醒" width="180" show-overflow-tooltip><template #default="{ row }"><ElTag v-bind="coverageRiskTag(row)" disable-transitions class="tracking-risk-tag" :title="coverageRiskText(row)" data-testid="coverage-purchase-status"><span class="tracking-cell">{{ coverageRiskText(row) }}</span></ElTag></template></ElTableColumn>
            <ElTableColumn label="操作" width="144" fixed="right"><template #default="{ row }"><div class="tracking-actions"><ElButton v-for="action in actionsFor(row)" :key="action.kind + action.path" link type="primary" @click="openAction(action)">{{ action.label }}</ElButton><span v-if="showActionBlocked(row)" class="muted" :title="row.action_blocked_reason">受限</span><span v-if="!showAction(row) && !showActionBlocked(row)" class="muted">—</span></div></template></ElTableColumn>
            <template #empty><div class="empty-state"><strong>{{ errorMessage ? '采购提醒加载失败' : loading ? '正在加载采购提醒' : emptyMessage }}</strong><p>{{ errorMessage ? '请重新加载后再试。' : '已采购足量的物料不会显示在这里。' }}</p><ElButton v-if="errorMessage" @click="load">重新加载</ElButton></div></template>
          </ElTable>
        </div>
        <ElTooltip virtual-triggering :virtual-ref="hoveredMaterialCell" :visible="Boolean(hoveredMaterialRow)" placement="top" :show-after="80" :teleported="true" :enterable="false" popper-class="purchase-tracking-material-tooltip">
          <template #content><div class="material-attribute-tooltip"><div v-for="field in hoveredMaterialFields" :key="field.key"><span>{{ field.label }}</span><strong>{{ field.value }}</strong></div><div v-if="!hoveredMaterialFields.length">暂无物料属性</div></div></template>
        </ElTooltip>
        <footer class="list-card__footer erp-list-footer">
          <span role="status" aria-live="polite">共 {{ canView && loaded ? total : '—' }} 条</span>
          <ElPagination :current-page="currentPage" :page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" :pager-count="5" layout="sizes, prev, pager, next" background @current-change="changePage" @size-change="changePageSize" />
        </footer>
      </section>
      <p v-if="mode === 'arrival'" class="tracking-footnote">管材提前5天、其他材料提前3天提醒；实收包含待检，未到与退货分开提示，退货不自动视为补交。</p>
      <PurchaseTrackingPolicyDialog v-if="mode === 'coverage' && canManagePolicy" v-model="policyVisible" @saved="load" />
    </template>
  </section>
</template>

<style scoped lang="scss">
.purchase-tracking-page { height: 100%; min-width: 0; }
.page-heading__title { display: flex; flex-wrap: wrap; align-items: baseline; gap: 12px; min-width: 0; }
.page-heading__count { color: var(--erp-color-text-secondary); white-space: nowrap; font-size: 12px; }
.task-filter { width: 260px; flex: none; }
.risk-filter { width: 190px; flex: none; }
.list-toolbar-hint { color: var(--erp-color-text-secondary); font-size: 12px; }
.tracking-toolbar-actions { display: flex; align-items: center; }
.load-error { flex: none; }
.tracking-location { display: flex; align-items: center; gap: 12px; flex: none; color: var(--erp-color-text-secondary); font-size: 12px; }
.tracking-table { width: 100%; }
.material-attribute-tooltip { min-width: 180px; line-height: 24px; font-size: 14px; }
.material-attribute-tooltip > div { display: flex; gap: 8px; }
.material-attribute-tooltip span { color: var(--erp-color-text-secondary); min-width: 42px; }
.tracking-cell { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tracking-strong { font-weight: 600; }
.tracking-number { font-variant-numeric: tabular-nums; }
.risk-danger { color: var(--erp-color-danger); font-weight: 500; }
.tracking-risk-tag { max-width: 100%; vertical-align: middle; font-weight: 600; }
.tracking-risk-tag :deep(.el-tag__content) { min-width: 0; }
.tracking-actions { display: flex; align-items: center; gap: 8px; min-width: 0; overflow: hidden; white-space: nowrap; }
.tracking-actions .el-button { flex: none; min-height: 32px; margin-left: 0; padding: 0; font-size: 12px; }
.muted { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--erp-color-text-secondary); }
.empty-state { display: flex; min-height: 260px; flex-direction: column; align-items: center; justify-content: center; color: var(--erp-color-text-secondary); }
.empty-state strong { color: var(--erp-color-text-primary); font-size: 16px; }
.empty-state p { margin: 8px 0 16px; }
.tracking-footnote { flex: none; margin: 0; color: var(--erp-color-text-secondary); font-size: 12px; line-height: 20px; }
.state-page { display: grid; flex: 1; place-content: center; text-align: center; }
.state-page h2 { margin: 0 0 8px; }
.state-page p { margin: 0; color: var(--erp-color-text-secondary); }
@media (max-width: 700px) {
  .task-filter, .risk-filter { width: 100%; }
  .erp-list-filter-actions { width: 100%; margin-left: 0; }
}
</style>



