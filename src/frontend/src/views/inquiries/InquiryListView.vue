<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { ArrowDown, ArrowLeft, ArrowRight, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { More } from '@icon-park/vue-next'
import { assignInquiry, bulkAssignInquiries, bulkMarkInquiryInvalid, deleteInquiry, exportInquiries, fetchInquiryDeletionPreview, fetchInquiryBoard, fetchInquiryMetrics, fetchInquiryOptions, fetchInquiries, markInquiryInvalid, setInquiryPriority } from '@/api/inquiries'
import { createSavedView, fetchSavedViews, setDefaultSavedView } from '@/api/savedViews'
import { useOptions } from '@/composables/useOptions'
import { useAuthStore } from '@/stores/auth'
import type { InquiryDeletionPreview, InquiryMetrics, InquiryOptions, InquiryRow } from '@/types/inquiry'
import type { SavedView } from '@/types/savedView'
import InquiryActionDialog from '@/components/inquiries/InquiryActionDialog.vue'
import InquiryNotice from '@/components/inquiries/InquiryNotice.vue'
import CrmPageHeader from '@/components/crm/CrmPageHeader.vue'
import DataTableToolbar from '@/components/common/DataTableToolbar.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import StatusTag from '@/components/customers/CustomerActivityTag.vue'
import QuotationFromInquiryDialog from '@/components/quotations/QuotationFromInquiryDialog.vue'
import columnsIcon from '@/assets/crm-v2/columns.svg'
import filterIcon from '@/assets/crm-v2/filter.svg'
import sortIcon from '@/assets/crm-v2/sort.svg'
import assignIcon from '@/assets/crm-v2/transfer-owner.svg'
import bookmarkIcon from '@/assets/crm-v2/bookmark.svg'
import exportIcon from '@/assets/crm-v2/export.svg'
import { allRowsAllow, columnChoices, filterKeys, formatEstimatedAmount, formatReceived, readColumns, readListQuery, slaPresentation, sortChoices, statusTone, priorityTone } from './inquiryListState'
import { handlingStageLabel } from './inquiryWorktime'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const sourceOptions = useOptions('INQUIRY_SOURCE')
const initial = readListQuery(route.query)
const filters = reactive(initial.filters)
const page = ref(initial.page)
const pageSize = ref(initial.pageSize)
const ordering = ref(initial.ordering)
const view = ref(initial.view)
const rows = ref<InquiryRow[]>([])
const total = ref(0)
const loading = ref(true)
const errorMessage = ref('')
const options = ref<InquiryOptions | null>(null)
const metrics = ref<InquiryMetrics | null>(null)
const counts = reactive<{ all: number | null; mine: number | null; unassigned: number | null }>({ all: null, mine: null, unassigned: null })
const boardLanes = ref<Array<{ code: string; label: string; count: number; cards: InquiryRow[] }>>([])
const selectedRows = ref<InquiryRow[]>([])
const table = ref<{ clearSelection: () => void }>()
const moreVisible = ref(false)
const moreFilters = reactive({ ...filters })
const amountInput = ref('')
const filterError = ref('')
const density = ref<'normal' | 'compact'>('compact')
const saveSettings = reactive({ sort: true, columns: true, default: false })
const saveError = ref('')
const createdViewId = ref('')
const actionError = ref('')
const deleteVisible = ref(false)
const deleteLoading = ref(false)
const deleteError = ref('')
const deleteTarget = ref<InquiryRow | null>(null)
const deletePreview = ref<InquiryDeletionPreview | null>(null)
const deleteEtag = ref('')
const draggingColumn = ref('')
const orderedColumnChoices = computed(() => [...columns.value, ...columnChoices.map(item => item.key).filter(key => !columns.value.includes(key))].map(key => columnChoices.find(item => item.key === key)!))
const tableColumns = computed(() => columns.value.map(key => ({ key, label: columnChoices.find(item => item.key === key)!.label, width: ({ country:113, source:110, priority:114, owner:119, amount:162, product:160, received:120, sla:130, status:130, reminder:130 } as Record<string, number>)[key] })))
const canSetDefault = computed(() => canReadViews.value && auth.hasPermission('preferences.change_savedview'))
function dropColumn(target: string) {
  const source = draggingColumn.value
  draggingColumn.value = ''
  if (!columns.value.includes(source) || !columns.value.includes(target) || source === target) return
  const next = columns.value.filter(key => key !== source)
  next.splice(next.indexOf(target), 0, source)
  columns.value = next
}
const dateShortcuts = [{ text: '最近 30 天', value: () => { const end = new Date(); const start = new Date(); start.setDate(start.getDate() - 29); return [start, end] } }]
watch(moreVisible, opened => {
  if (!opened) return
  Object.assign(moreFilters, filters); filterError.value = ''
  amountInput.value = filters.amount_min ? `${filters.amount_currency} ${filters.amount_min}` : ''
  receivedRange.value = filters.received_from && filters.received_to ? [filters.received_from.slice(0,10), filters.received_to.slice(0,10)] : null
})
const receivedRange = ref<[string, string] | null>(filters.received_from && filters.received_to ? [filters.received_from.slice(0, 10), filters.received_to.slice(0, 10)] : null)
const storageKey = 'haiqu.inquiries.columns.v2'
function storedColumns() { try { return readColumns(localStorage.getItem(storageKey)) } catch { return readColumns(null) } }
const columns = ref<string[]>(storedColumns())
const savedViews = ref<SavedView[]>([])
const savedViewsError = ref(false)
const saveVisible = ref(false)
const viewName = ref('')
const saving = ref(false)
const exporting = ref(false)
const actionVisible = ref(false)
const actionKind = ref<'assign' | 'mark_invalid'>('assign')
const actionRows = ref<InquiryRow[]>([])
const bulkAction = ref(false)
const acting = ref(false)
const form = reactive({ ownerId: '', reason: '', reasonCode: '', reasonDetail: '' })
const invalidReasonLabels: Record<string, string> = { DUPLICATE: '重复询盘', SPAM: '垃圾询盘', UNPROCESSABLE: '无法处理', OTHER: '其他' }
const quoteRow = ref<InquiryRow | null>(null)
const quoteVisible = ref(false)
const priorityVisible = ref(false)
const priorityRow = ref<InquiryRow | null>(null)
const priorityValue = ref('')
const prioritySaving = ref(false)
let requestVersion = 0
let summaryVersion = 0
let disposed = false
let initialized = false
const canAssign = computed(() => auth.hasPermission('inquiries.assign_inquiry'))
const canBulk = computed(() => auth.hasPermission('inquiries.bulk_change_inquiry'))
const canChange = computed(() => auth.hasPermission('inquiries.change_inquiry'))
const canSave = computed(() => auth.hasPermission('preferences.add_savedview'))
const canReadViews = computed(() => auth.hasPermission('preferences.view_savedview'))
const canDelete = computed(() => auth.hasPermission('inquiries.delete_inquiry'))
const canMarkInvalid = computed(() => auth.hasPermission(auth.user?.sales_access_enabled ? 'access_control.markinvalid_inquiry' : 'inquiries.change_inquiry'))
const canBulkAssign = computed(() => canAssign.value && canBulk.value && allRowsAllow(selectedRows.value, 'assign'))
const canBulkInvalid = computed(() => (auth.user?.sales_access_enabled ? auth.hasPermission('access_control.markinvalid_inquiry') : canChange.value) && canBulk.value && allRowsAllow(selectedRows.value, 'mark_invalid'))
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const visiblePages = computed(() => { const start = Math.max(1, Math.min(page.value - 2, totalPages.value - 4)); return Array.from({ length: Math.min(5, totalPages.value) }, (_, index) => start + index) })
const extraCount = computed(() => [filters.owner_employee_id, filters.assignment_status, filters.sla_state, filters.product_q, filters.received_from || filters.received_to, filters.has_quotation, filters.priority, filters.amount_min].filter(Boolean).length)
const shortcuts = computed(() => [
  { key: 'all', label: '全部询盘', count: counts.all, width: 140 },
  ...(auth.user?.employee?.id ? [{ key: 'mine', label: '我的询盘', count: counts.mine, width: 150 }] : []),
  { key: 'unassigned', label: '待分配', count: counts.unassigned, width: 170 },
  { key: 'risk', label: '即将超时', count: metrics.value?.due_soon ?? null, width: 140 },
  { key: 'quoting', label: '报价中', count: metrics.value?.quoting ?? null, width: 150 },
  ...(typeof metrics.value?.has_quotation === 'number' ? [{ key: 'has_quotation', label: '已转报价', count: metrics.value.has_quotation, width: 150 }] : []),
])
const activeShortcut = computed(() => {
  const active = filterKeys.filter(key => Boolean(filters[key]))
  if (!active.length) return 'all'
  if (active.length !== 1) return ''
  if (filters.owner_employee_id && filters.owner_employee_id === auth.user?.employee?.id) return 'mine'
  if (filters.assignment_status === 'UNASSIGNED') return 'unassigned'
  if (filters.sla_state === 'DUE_SOON') return 'risk'
  if (filters.status === 'QUOTING') return 'quoting'
  if (filters.has_quotation === 'true') return 'has_quotation'
  return ''
})
function message(error: unknown) {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查连接后重试。'
  const status = error.response.status
  const detail = (error.response.data as { error?: { message?: string } })?.error?.message
  if (status === 401) return '登录状态已失效，请重新登录。'
  if (status === 403) return '当前账号没有此操作权限。'
  if (status === 412 || status === 428) return detail || '记录版本已变化，请关闭窗口并刷新列表后重试。'
  return detail || '请求失败，请稍后重试。'
}
function query() {
  const params: Record<string, string | number> = { page: page.value, page_size: pageSize.value, ordering: ordering.value }
  for (const key of filterKeys) if (filters[key]) params[key] = filters[key]
  return params
}
function restoreQuery() {
  const state = readListQuery(route.query)
  Object.assign(filters, state.filters)
  page.value = state.page; pageSize.value = state.pageSize; ordering.value = state.ordering; view.value = state.view
  receivedRange.value = filters.received_from && filters.received_to ? [filters.received_from.slice(0, 10), filters.received_to.slice(0, 10)] : null
}
async function syncUrl() {
  const next = { ...query(), ...(view.value === 'board' ? { view: 'board' } : {}) }
  const keys = Object.keys(next)
  const same = keys.length === Object.keys(route.query).length && keys.every(key => String(route.query[key]) === String(next[key as keyof typeof next]))
  if (same) await load()
  else await router.replace({ query: next })
}
async function load() {
  const version = ++requestVersion
  loading.value = true; errorMessage.value = ''; selectedRows.value = []; table.value?.clearSelection()
  try {
    if (view.value === 'board') {
      const result = await fetchInquiryBoard(query())
      if (disposed || version !== requestVersion) return
      boardLanes.value = result.lanes
    } else {
      const result = await fetchInquiries(query())
      if (disposed || version !== requestVersion) return
      total.value = result.meta.total
      if (page.value > totalPages.value) { page.value = totalPages.value; await syncUrl(); return }
      rows.value = result.data
    }
  } catch (error) {
    if (disposed || version !== requestVersion) return
    rows.value = []; boardLanes.value = []; total.value = 0; errorMessage.value = message(error)
  } finally { if (!disposed && version === requestVersion) loading.value = false }
}
async function loadSummary() {
  const version = ++summaryVersion
  try {
    const summary = await fetchInquiryMetrics({})
    if (disposed || version !== summaryVersion) return
    counts.all = summary.list_counts?.all ?? null
    counts.mine = summary.list_counts?.mine ?? null
    counts.unassigned = summary.list_counts?.unassigned ?? null
    metrics.value = summary
  } catch {
    if (disposed || version !== summaryVersion) return
    counts.all = null; counts.mine = null; counts.unassigned = null; metrics.value = null
  }
}
async function refreshAll() { await Promise.all([load(), loadSummary()]) }
async function downloadExport() {
  if (exporting.value || !auth.hasPermission('inquiries.view_inquiry')) return
  exporting.value = true
  try {
    const params = { ...query() }; delete params.page; delete params.page_size
    const blob = await exportInquiries(params)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = `询盘列表_${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(link); link.click(); link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) {
    if (error instanceof AxiosError && error.response?.data instanceof Blob && error.response.data.size < 1000000) {
      try { error.response.data = JSON.parse(await error.response.data.text()) } catch { /* 使用统一错误提示。 */ }
    }
    ElMessage.error(message(error))
  } finally { exporting.value = false }
}
function applyFilters() { page.value = 1; void syncUrl() }
function clearFilters() { Object.assign(filters, readListQuery({}).filters); receivedRange.value = null }
function resetFilters() { clearFilters(); moreVisible.value = false; applyFilters() }
function applyMore() {
  const amount = amountInput.value.trim().replace(/,/g, '').replace(/\s*以上$/, '')
  const match = /^([A-Za-z]{3})\s+(\d{1,32}(?:\.\d{1,8})?)$/.exec(amount)
  if (amount && !match) { filterError.value = '请输入币种和非负金额，例如 USD 10000。'; return }
  moreFilters.amount_currency = match?.[1]?.toUpperCase() || ''
  moreFilters.amount_min = match?.[2] || ''
  moreFilters.received_from = receivedRange.value ? `${receivedRange.value[0]}T00:00:00+08:00` : ''
  moreFilters.received_to = receivedRange.value ? `${receivedRange.value[1]}T23:59:59.999999+08:00` : ''
  Object.assign(filters, moreFilters)
  moreVisible.value = false; applyFilters()
}
function resetMore() { Object.assign(moreFilters, readListQuery({}).filters); receivedRange.value = null; amountInput.value = ''; filterError.value = '' }
function applyShortcut(key: string) {
  clearFilters()
  if (key === 'mine') { if (!auth.user?.employee?.id) return; filters.owner_employee_id = auth.user.employee.id }
  if (key === 'unassigned') filters.assignment_status = 'UNASSIGNED'
  if (key === 'risk') filters.sla_state = 'DUE_SOON'
  if (key === 'quoting') filters.status = 'QUOTING'
  if (key === 'has_quotation') filters.has_quotation = 'true'
  applyFilters()
}
function changePage(value: number) { if (loading.value || value < 1 || value > totalPages.value) return; page.value = value; void syncUrl() }
function changeSize() { page.value = 1; void syncUrl() }
function routeTo(name: 'inquiry-create' | 'inquiry-detail', id?: string) { void router.push({ name, params: id ? { inquiryId: id } : {} }) }
async function loadSavedViews() {
  if (!canReadViews.value) return
  try { savedViews.value = await fetchSavedViews('INQUIRY'); savedViewsError.value = false }
  catch { savedViewsError.value = true }
}
function applySavedView(saved: SavedView) {
  const state = readListQuery({ ...saved.filter_definition, ordering: saved.sort_definition[0] || saved.filter_definition.ordering })
  Object.assign(filters, state.filters); pageSize.value = state.pageSize
  if (saved.sort_definition.length || saved.filter_definition.ordering) ordering.value = state.ordering
  if (saved.column_definition.length || saved.filter_definition.density) columns.value = readColumns(JSON.stringify(saved.column_definition))
  if (saved.filter_definition.density === 'normal' || saved.filter_definition.density === 'compact') density.value = saved.filter_definition.density
  receivedRange.value = filters.received_from && filters.received_to ? [filters.received_from.slice(0, 10), filters.received_to.slice(0, 10)] : null
  applyFilters()
}
function openSave() {
  viewName.value = ''; saveError.value = ''; createdViewId.value = ''
  Object.assign(saveSettings, { sort: true, columns: true, default: false }); saveVisible.value = true
}
async function submitSave() {
  if (saving.value || !canSave.value) return
  if (!viewName.value.trim()) { saveError.value = '请输入视图名称。'; return }
  if (saveSettings.default && !canSetDefault.value) { saveError.value = '当前账号没有设置默认视图权限。'; return }
  const definition = { ...query() }; delete definition.page
  if (!saveSettings.sort) delete definition.ordering
  if (saveSettings.columns) definition.density = density.value
  saving.value = true; saveError.value = ''
  try {
    if (!createdViewId.value) {
      const created = await createSavedView({ module_code: 'INQUIRY', view_name: viewName.value.trim(), filter_definition: definition, column_definition: saveSettings.columns ? columns.value : [], sort_definition: saveSettings.sort ? [ordering.value] : [] })
      createdViewId.value = created.id
    }
    if (saveSettings.default) await setDefaultSavedView(createdViewId.value)
    saveVisible.value = false; ElMessage.success('个人视图已保存。'); await loadSavedViews()
  } catch (error) { saveError.value = `${createdViewId.value ? '视图已保存，设置默认失败；重试只更新默认设置。' : ''}${message(error)}` }
  finally { saving.value = false }
}
function viewCommand(command: string) {
  if (command === 'board' || command === 'list') { view.value = command; page.value = 1; void syncUrl(); return }
  if (command === 'accepted') { clearFilters(); filters.status = 'QUOTE_ACCEPTED'; applyFilters(); return }
  if (command === 'retry') { void loadSavedViews(); return }
  const saved = savedViews.value.find(item => item.id === command)
  if (saved) applySavedView(saved)
}
function openAction(kind: 'assign' | 'mark_invalid', row?: InquiryRow) {
  const targets = row ? [row] : selectedRows.value
  if (loading.value || !allRowsAllow(targets, kind)) return
  if (kind === 'assign' ? !canAssign.value : !canMarkInvalid.value) return
  if (!row && !canBulk.value) return
  actionKind.value = kind; actionRows.value = [...targets]; bulkAction.value = !row
  Object.assign(form, { ownerId: '', reason: '', reasonCode: options.value?.invalid_reason_codes.includes('OTHER') ? 'OTHER' : options.value?.invalid_reason_codes[0] || '', reasonDetail: '' })
  actionError.value = ''; actionVisible.value = true
}
async function submitAction() {
  if (acting.value || !allRowsAllow(actionRows.value, actionKind.value)) return
  if (bulkAction.value && !canBulk.value) return
  const assigning = actionKind.value === 'assign'
  if (assigning ? !canAssign.value : !canMarkInvalid.value) return
  if (assigning && !options.value?.owners.some(owner => owner.id === form.ownerId)) { actionError.value = '请选择可分配的负责人。'; return }
  if (!assigning && !options.value?.invalid_reason_codes.includes(form.reasonCode)) { actionError.value = '请选择无效原因。'; return }
  acting.value = true; actionError.value = ''
  const items = actionRows.value.map(row => ({ id: row.id, etag: row.etag }))
  const first = items[0]!
  try {
    if (assigning) {
      if (bulkAction.value) await bulkAssignInquiries(items, form.ownerId, form.reason.trim())
      else await assignInquiry(first.id, first.etag, form.ownerId, form.reason.trim())
    } else {
      if (bulkAction.value) await bulkMarkInquiryInvalid(items, form.reasonCode, form.reasonDetail.trim())
      else await markInquiryInvalid(first.id, first.etag, form.reasonCode, form.reasonDetail.trim())
    }
    actionVisible.value = false; acting.value = false; ElMessage.success(assigning ? '负责人已分配。' : '询盘已标记为无效。'); await refreshAll()
  } catch (error) { actionError.value = message(error) } finally { acting.value = false }
}
async function deleteRow(row: InquiryRow) {
  if (!canDelete.value || acting.value || deleteLoading.value) return
  deleteTarget.value = row; deletePreview.value = null; deleteEtag.value = ''; deleteError.value = ''; deleteVisible.value = true
  await loadDeletePreview()
}
async function loadDeletePreview() {
  const target = deleteTarget.value
  if (!target || deleteLoading.value) return
  deleteLoading.value = true; deleteError.value = ''
  try {
    const current = await fetchInquiryDeletionPreview(target.id)
    if (deleteTarget.value?.id !== target.id || !deleteVisible.value) return
    if (!current.etag) throw new Error('缺少记录版本')
    deletePreview.value = current.data; deleteEtag.value = current.etag
  } catch (error) { deleteError.value = message(error) }
  finally { deleteLoading.value = false }
}
async function submitDelete() {
  if (!canDelete.value || acting.value || deleteLoading.value || !deletePreview.value || !deleteTarget.value || !deleteEtag.value) return
  acting.value = true; deleteError.value = ''
  try {
    await deleteInquiry(deleteTarget.value.id, deleteEtag.value)
    deleteVisible.value = false; acting.value = false; ElMessage.success('询盘已永久删除。'); await refreshAll()
  } catch (error) { deleteError.value = message(error); deleteEtag.value = '' }
  finally { acting.value = false }
}
function rowCommand(command: string, row: InquiryRow) {
  if (command === 'priority' && canChange.value && row.allowed_actions.set_priority && row.etag) {
    priorityRow.value = row; priorityValue.value = row.priority || ''; priorityVisible.value = true
  }
  if (command === 'assign' || command === 'mark_invalid') openAction(command, row)
  if (command === 'delete') void deleteRow(row)
  if (command === 'quote' && row.allowed_actions.create_quotation && row.etag) { quoteRow.value = row; quoteVisible.value = true }
}
function hasRowActions(row: InquiryRow) { return (canAssign.value && row.allowed_actions.assign) || (canMarkInvalid.value && row.allowed_actions.mark_invalid) || (canChange.value && row.allowed_actions.set_priority) || row.allowed_actions.create_quotation || auth.canFor('inquiries.delete_inquiry', row) }
async function submitPriority() {
  const row = priorityRow.value
  if (!row || !row.etag || !canChange.value || !row.allowed_actions.set_priority || prioritySaving.value) return
  if (priorityValue.value && !options.value?.priorities?.some(item => item.code === priorityValue.value)) {
    ElMessage.warning('请选择有效的优先级。'); return
  }
  prioritySaving.value = true
  try {
    await setInquiryPriority(row.id, row.etag, priorityValue.value)
    priorityVisible.value = false; prioritySaving.value = false; ElMessage.success('优先级已保存。'); await refreshAll()
  } catch (error) { ElMessage.error(message(error)) } finally { prioritySaving.value = false }
}
async function loadOptions() {
  try {
    const current = await fetchInquiryOptions({}); options.value = current
    try {
      const published = await sourceOptions.load()
      if (sourceOptions.configVersion.value !== null) options.value = { ...current, sources: published.map(item => ({ item_code: item.code, display_name: item.label, sort_order: item.sort_order })) }
    } catch { /* 保留服务端兼容选项。 */ }
  } catch { ElMessage.warning('筛选选项加载失败，可刷新页面重试。') }
}
watch(columns, () => { try { localStorage.setItem(storageKey, JSON.stringify(columns.value)) } catch { ElMessage.warning('浏览器无法保存列设置，本次设置仍然有效。') } }, { deep: true })
watch(() => route.query, () => { if (initialized) { restoreQuery(); void load() } })
onMounted(async () => {
  void loadOptions(); void loadSummary()
  await loadSavedViews()
  if (disposed) return
  initialized = true
  const defaultView = savedViews.value.find(item => item.is_default)
  if (!Object.keys(route.query).length && defaultView) applySavedView(defaultView)
  else { restoreQuery(); await load() }
})
onBeforeRouteLeave(() => !(acting.value || saving.value || prioritySaving.value))
onBeforeRouteUpdate(() => !(acting.value || saving.value || prioritySaving.value))
onBeforeUnmount(() => { disposed = true; requestVersion++; summaryVersion++ })
</script>

<template>
  <section class="inquiry-page" aria-label="询盘列表">
    <CrmPageHeader title="询盘列表" :count="counts.all ?? undefined" count-label="条询盘">
      <template #actions><el-button v-if="auth.hasPermission('inquiries.view_inquiry')" class="export-button" :loading="exporting" @click="downloadExport"><img :src="exportIcon" alt="" />导出</el-button><el-button v-if="auth.hasPermission('inquiries.add_inquiry')" type="primary" class="create-button" :icon="Plus" @click="routeTo('inquiry-create')">新建询盘</el-button></template>
    </CrmPageHeader>
    <nav class="quick-filters" aria-label="询盘快捷筛选">
      <button v-for="item in shortcuts" :key="item.key" :style="{ width: `${item.width}px` }" :class="{ active: activeShortcut === item.key }" :aria-pressed="activeShortcut === item.key" @click="applyShortcut(item.key)">
        {{ item.label }}<span :title="item.count === null ? '统计暂不可用，可刷新重试' : '当前账号可见范围内的数量'">{{ item.count ?? '—' }}</span>
      </button>
    </nav>
    <div class="filters">
      <el-input v-model="filters.q" class="search-filter" aria-label="搜索询盘" placeholder="搜索客户名称、询盘编号、主题" clearable :prefix-icon="Search" @keyup.enter="applyFilters" @clear="applyFilters" />
      <el-select popper-class="inquiry-v4-select" v-model="filters.status" class="status-filter" aria-label="状态筛选" placeholder="状态：全部" clearable @change="applyFilters"><el-option v-for="item in options?.statuses" :key="item.code" :label="item.display_name" :value="item.code" /></el-select>
      <el-select popper-class="inquiry-v4-select" v-model="filters.source_code" class="source-filter" aria-label="来源筛选" placeholder="来源：全部" clearable @change="applyFilters"><el-option v-for="item in options?.sources" :key="item.item_code" :label="item.display_name" :value="item.item_code" /></el-select>
      <el-select popper-class="inquiry-v4-select" v-model="filters.country_code" class="country-filter" aria-label="国家地区筛选" placeholder="国家 / 地区：全部" filterable clearable @change="applyFilters"><el-option v-for="country in options?.countries" :key="country" :label="country" :value="country" /></el-select>
      <el-popover v-model:visible="moreVisible" trigger="click" placement="bottom-end" :width="520" :show-arrow="false" popper-class="inquiry-v4-popover inquiry-v4-filters">
        <template #reference><el-button class="more-filter"><img :src="filterIcon" alt="" />更多筛选<span v-if="extraCount">({{ extraCount }})</span></el-button></template>
        <h2>更多筛选</h2>
        <el-form label-position="top" class="inquiry-filter-form" @submit.prevent="applyMore">
          <el-form-item label="负责人"><el-select popper-class="inquiry-v4-select" v-model="moreFilters.owner_employee_id" placeholder="全部负责人" filterable clearable><el-option v-for="item in options?.owners" :key="item.id" :label="item.display_name" :value="item.id" /></el-select></el-form-item>
          <el-form-item label="优先级"><el-select popper-class="inquiry-v4-select" v-model="moreFilters.priority" placeholder="全部优先级" clearable><el-option v-for="item in options?.priorities" :key="item.code" :value="item.code" :label="item.display_name" /><el-option value="UNSET" label="未设置" /></el-select></el-form-item>
          <el-form-item label="处理时限状态"><el-select popper-class="inquiry-v4-select" v-model="moreFilters.sla_state" placeholder="全部" clearable><el-option label="即将超时、已超时" value="RISK"/><el-option label="即将超时" value="DUE_SOON"/><el-option label="已超时" value="BREACHED"/><el-option label="无进行中的计时" value="NONE"/></el-select></el-form-item>
          <el-form-item label="接收日期"><el-date-picker popper-class="inquiry-v4-select" v-model="receivedRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" :shortcuts="dateShortcuts"/></el-form-item>
          <el-form-item label="预估金额"><el-input v-model="amountInput" aria-label="预估金额筛选" placeholder="USD 10,000 以上" clearable @keyup.enter="applyMore"/></el-form-item>
          <el-form-item label="产品关键词"><el-input v-model="moreFilters.product_q" placeholder="折叠椅 / 露营桌" clearable @keyup.enter="applyMore"/></el-form-item>
          <p v-if="filterError" class="filter-error" role="alert">{{ filterError }}</p>
          <div class="popover-footer"><el-button @click="resetMore">重置</el-button><el-button type="primary" @click="applyMore">应用筛选</el-button></div>
        </el-form>
      </el-popover>
    </div>
    <DataTableToolbar class="inquiry-toolbar is-compact" :selected-count="selectedRows.length">
      <template #selection>
        <el-button v-if="canAssign && canBulk" class="assign-button" :disabled="loading || !canBulkAssign" @click="openAction('assign')"><img :src="assignIcon" alt="" />分配负责人</el-button>
        <el-button v-if="canMarkInvalid && canBulk" class="invalid-button" :disabled="loading || !canBulkInvalid" @click="openAction('mark_invalid')">标记无效</el-button>
      </template>
      <template #actions>
        <el-dropdown :persistent="false" popper-class="inquiry-v4-select" trigger="click" @command="(value: string) => { ordering = value; applyFilters() }"><el-button class="sort-button"><img :src="sortIcon" alt="" />排序<el-icon><ArrowDown /></el-icon></el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-for="item in sortChoices" :key="item.value" :command="item.value" :class="{ 'is-active': ordering === item.value }">{{ ordering === item.value ? '✓ ' : '' }}{{ item.label }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
        <el-popover trigger="click" placement="bottom-end" :width="320" :show-arrow="false" popper-class="inquiry-v4-popover inquiry-v4-columns"><template #reference><el-button class="columns-button"><img :src="columnsIcon" alt=""/>列设置</el-button></template>
          <h2>显示列</h2><p>拖动调整顺序，勾选控制显示。</p>
          <div class="columns-list"><el-checkbox :model-value="true" disabled>客户名称 / 询盘编号</el-checkbox><el-checkbox-group v-model="columns"><div v-for="item in orderedColumnChoices" :key="item.key" :draggable="columns.includes(item.key)" @dragstart="draggingColumn = item.key" @dragend="draggingColumn = ''" @dragover.prevent @drop.prevent="dropColumn(item.key)"><el-checkbox :label="item.label" :value="item.key"/></div></el-checkbox-group></div>
        </el-popover>
        <el-dropdown :persistent="false" trigger="click" popper-class="inquiry-v4-select" @command="(value: 'normal' | 'compact') => density = value"><el-button aria-label="列表密度">密度<el-icon><ArrowDown/></el-icon></el-button><template #dropdown><el-dropdown-menu><el-dropdown-item command="normal">{{ density === 'normal' ? '✓ ' : '' }}标准</el-dropdown-item><el-dropdown-item command="compact">{{ density === 'compact' ? '✓ ' : '' }}紧凑</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
        <div class="saved-view-actions"><el-button v-if="canSave" class="save-button" @click="openSave"><img :src="bookmarkIcon" alt="" />保存视图</el-button><el-dropdown :persistent="false" popper-class="inquiry-v4-select" trigger="click" @command="viewCommand"><el-button :class="canSave ? 'saved-menu-button' : 'views-button'" aria-label="切换个人视图">{{ canSave ? '' : '视图' }}<el-icon><ArrowDown /></el-icon></el-button><template #dropdown><el-dropdown-menu><el-dropdown-item :command="view === 'list' ? 'board' : 'list'">{{ view === 'list' ? '查看看板' : '返回列表' }}</el-dropdown-item><el-dropdown-item command="accepted">报价已接受</el-dropdown-item><el-dropdown-item v-for="saved in savedViews" :key="saved.id" :command="saved.id">{{ saved.view_name }}{{ saved.is_default ? '（默认）' : '' }}</el-dropdown-item><el-dropdown-item v-if="savedViewsError" command="retry" divided>个人视图加载失败，重试</el-dropdown-item><el-dropdown-item v-else-if="canReadViews && !savedViews.length" disabled divided>暂无个人视图</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
        <el-button class="refresh-button" :icon="Refresh" :loading="loading" aria-label="刷新询盘" title="刷新" @click="refreshAll" />
      </template>
    </DataTableToolbar>
    <div v-if="view === 'list'" class="data-surface">
      <el-table ref="table" v-loading="loading" :data="rows" row-key="id" height="100%" class="inquiry-table" :class="{ 'is-compact': density === 'compact' }" :row-class-name="({ row }: { row: InquiryRow }) => selectedRows.some(item => item.id === row.id) ? 'is-selected' : ''" @selection-change="selectedRows = $event">
        <el-table-column type="selection" width="50" />
        <el-table-column label="客户名称 / 询盘编号" min-width="249"><template #default="{ row }"><button class="identity" @click="routeTo('inquiry-detail', row.id)"><strong :title="row.customer.name">{{ row.customer.name || '—' }}</strong><small>{{ row.inquiry_number }}</small></button></template></el-table-column>
        <el-table-column v-for="column in tableColumns" :key="column.key" :label="column.label" :width="column.width" show-overflow-tooltip><template #default="{ row }">
            <template v-if="column.key === 'country'">{{ row.customer.country_code || '—' }}</template>
            <template v-else-if="column.key === 'source'">{{ row.source.display_name || '—' }}</template>
            <template v-else-if="column.key === 'priority'"><StatusTag v-if="row.priority" :label="row.priority_display || row.priority" :tone="priorityTone(row.priority)" /><span v-else class="missing-value">—</span></template>
            <template v-else-if="column.key === 'owner'"><span :class="{ 'unassigned': !row.owner }">{{ row.owner?.display_name || '未分配' }}</span></template>
            <template v-else-if="column.key === 'amount'"><strong class="estimated-amount" :class="{ 'missing-value': formatEstimatedAmount(row) === '—' }">{{ formatEstimatedAmount(row) }}</strong></template>
            <template v-else-if="column.key === 'product'">{{ row.product_summary.first_description || '—' }}<small v-if="row.product_summary.item_count > 1" class="secondary">等 {{ row.product_summary.item_count }} 项</small></template>
            <template v-else-if="column.key === 'received'"><span class="received-date">{{ formatReceived(row.received_at).date }}</span><small class="secondary">{{ formatReceived(row.received_at).time }}</small></template>
            <template v-else-if="column.key === 'sla'"><span class="handling-cell" :title="row.sla_summary.working_time ? '按工作时间计算，午休及休息时间不计时' : '按原连续时间规则计算'" :class="`sla-${slaPresentation(row.sla_summary).tone}`"><small v-if="row.sla_summary.stage_code">{{ handlingStageLabel(row.sla_summary.stage_code) }}<span v-if="(row.sla_summary.active_count ?? 0) > 1"> 等{{ row.sla_summary.active_count }}项</span></small><span>{{ slaPresentation(row.sla_summary).label }}</span></span></template>
            <template v-else-if="column.key === 'status'"><StatusTag :label="row.display_stage_label || row.status_display || '—'" :tone="statusTone(row.status)" /></template>
            <template v-else-if="column.key === 'reminder'"><StatusTag v-if="row.sla_summary.state !== 'NONE'" :label="slaPresentation(row.sla_summary).reminder" :tone="slaPresentation(row.sla_summary).tone" /><span v-else class="missing-value">—</span></template>
        </template></el-table-column>
        <el-table-column label="操作" width="100" align="center"><template #default="{ row }"><el-dropdown :persistent="false" popper-class="inquiry-v4-select" v-if="hasRowActions(row)" trigger="click" @command="(command: string) => rowCommand(command, row)"><button class="row-more" :aria-label="`${row.inquiry_number} 更多操作`" :disabled="loading || acting"><More theme="filled" :size="24" /></button><template #dropdown><el-dropdown-menu><el-dropdown-item @click="routeTo('inquiry-detail', row.id)">查看询盘</el-dropdown-item><el-dropdown-item v-if="canChange && row.allowed_actions.set_priority" command="priority">设置优先级</el-dropdown-item><el-dropdown-item v-if="canAssign && row.allowed_actions.assign" command="assign">分配负责人</el-dropdown-item><el-dropdown-item v-if="row.allowed_actions.create_quotation" command="quote">创建报价</el-dropdown-item><el-dropdown-item v-if="canMarkInvalid && row.allowed_actions.mark_invalid" command="mark_invalid">标记无效</el-dropdown-item><el-dropdown-item v-if="canDelete && auth.canFor('inquiries.delete_inquiry', row)" command="delete" divided>永久删除</el-dropdown-item></el-dropdown-menu></template></el-dropdown><button v-else class="view-link" @click="routeTo('inquiry-detail', row.id)">查看</button></template></el-table-column>
        <template #empty><div class="table-empty" role="status"><template v-if="errorMessage"><p>{{ errorMessage }}</p><el-button @click="refreshAll">重新加载</el-button></template><template v-else-if="!loading"><p>暂无符合条件的询盘</p><el-button @click="resetFilters">清除筛选</el-button></template></div></template>
      </el-table>
      <footer class="table-footer"><span aria-live="polite">共 {{ total }} 条</span><div class="pagination"><el-select popper-class="inquiry-v4-select" v-model="pageSize" aria-label="每页条数" :disabled="loading" @change="changeSize"><el-option v-for="size in [20, 50, 100]" :key="size" :value="size" :label="`${size} 条 / 页`" /></el-select><el-button :icon="ArrowLeft" :disabled="loading || page <= 1" aria-label="上一页" @click="changePage(page - 1)" /><el-button v-for="number in visiblePages" :key="number" :class="{ active: page === number }" :aria-current="page === number ? 'page' : undefined" :aria-label="`第 ${number} 页`" :disabled="loading" @click="changePage(number)">{{ number }}</el-button><el-button :icon="ArrowRight" :disabled="loading || page >= totalPages" aria-label="下一页" @click="changePage(page + 1)" /></div></footer>
    </div>
    <div v-else v-loading="loading" class="board"><el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" /><section v-for="lane in boardLanes" :key="lane.code" class="lane"><h2>{{ lane.label }} <span>{{ lane.count }}</span></h2><button v-for="card in lane.cards" :key="card.id" class="board-card" @click="routeTo('inquiry-detail', card.id)"><strong>{{ card.customer.name }}</strong><small>{{ card.inquiry_number }}</small><p>{{ card.product_summary.first_description || card.subject }}</p><footer>{{ card.owner?.display_name || '未分配' }}<StatusTag :label="slaPresentation(card.sla_summary).reminder" :tone="slaPresentation(card.sla_summary).tone" /></footer></button><el-empty v-if="!lane.cards.length" description="暂无数据" :image-size="50" /></section></div>
    <InquiryActionDialog v-model="actionVisible" :title="`${bulkAction ? '批量' : ''}${actionKind === 'assign' ? '分配负责人' : '标记无效'}`" :subtitle="`已选择 ${actionRows.length} 条询盘`" :width="actionKind === 'assign' ? 520 : 500" :height="actionKind === 'assign' ? 468 : 482" :confirm-width="bulkAction ? 156 : 96" :busy="acting" :disabled="!options" :error="actionError" :danger="actionKind !== 'assign'" :confirm-label="`${actionKind === 'assign' ? '确认分配' : '确认标记'}${bulkAction ? ` ${actionRows.length} 条` : ''}`" @confirm="submitAction">
      <InquiryNotice v-if="actionKind === 'assign'" :title="bulkAction ? '批量操作采用全部成功或全部回滚' : '确认后更新询盘负责人'">{{ bulkAction ? '若任一询盘无权限或版本冲突，本次分配不会部分生效。' : '分配人、原负责人、新负责人和分配时间将保留在历史记录中。' }}</InquiryNotice>
      <InquiryNotice v-else tone="warning" title="关闭后仍保留全部询盘记录">无效询盘不计入转化率；系统记录操作人、原因和时间。</InquiryNotice>
      <el-form label-position="top" :disabled="acting" @submit.prevent="submitAction"><template v-if="actionKind === 'assign'"><el-form-item label="负责人" required><el-select popper-class="inquiry-v4-select" v-model="form.ownerId" filterable placeholder="请选择负责人"><el-option v-for="owner in options?.owners" :key="owner.id" :value="owner.id" :label="`${owner.display_name}（${owner.employee_code}）`"/></el-select></el-form-item><el-form-item label="分配说明"><el-input v-model="form.reason" type="textarea" maxlength="500" :input-style="{ height: '72px' }"/></el-form-item></template><template v-else><el-form-item label="无效原因" required><el-select popper-class="inquiry-v4-select" v-model="form.reasonCode"><el-option v-for="reason in options?.invalid_reason_codes" :key="reason" :value="reason" :label="invalidReasonLabels[reason] || reason"/></el-select></el-form-item><el-form-item label="说明"><el-input v-model="form.reasonDetail" type="textarea" maxlength="1000" :input-style="{ height: '88px' }"/></el-form-item></template></el-form>
    </InquiryActionDialog>
    <InquiryActionDialog v-model="deleteVisible" title="永久删除询盘" :subtitle="deletePreview?.inquiry_number || deleteTarget?.inquiry_number || ''" :width="520" :height="406" confirm-label="确认永久删除" :confirm-width="126" danger :busy="acting" :loading="deleteLoading" :disabled="!deletePreview || !deleteEtag" :error="deleteError" @confirm="submitDelete">
      <InquiryNotice tone="danger" title="删除后无法恢复">该询盘及关联的报价、样品、任务和业务关系将一并删除。</InquiryNotice>
      <p v-if="deletePreview" class="delete-impact">关联概览：{{ deletePreview.quotation_count }} 份报价 · {{ deletePreview.sample_count }} 个样品申请 · {{ deletePreview.task_count }} 条任务 · {{ deletePreview.inquiry_file_link_count }} 个询盘附件关联</p>
      <p class="inquiry-dialog-hint delete-hint">业务关闭请优先使用“标记无效”；仅在误建且确认无保留价值时永久删除。其他依赖关系也会按现有删除规则处理。</p>
      <el-button v-if="deleteError" :disabled="acting" @click="loadDeletePreview">重新核对关联记录</el-button>
    </InquiryActionDialog>
    <InquiryActionDialog v-model="saveVisible" title="保存个人视图" subtitle="保存当前筛选、排序和显示列" :width="500" :height="430" confirm-label="保存视图" :busy="saving" :error="saveError" @confirm="submitSave">
      <el-form label-position="top" :disabled="saving || !!createdViewId" class="save-view-form" @submit.prevent="submitSave"><el-form-item label="视图名称" required><el-input v-model="viewName" placeholder="输入视图名称" maxlength="100"/></el-form-item><el-form-item label="可见范围"><el-input model-value="仅自己可见" readonly/></el-form-item><div class="save-view-checks"><el-checkbox v-model="saveSettings.sort">同时保存当前排序</el-checkbox><el-checkbox v-model="saveSettings.columns">同时保存显示列与密度</el-checkbox><el-checkbox v-model="saveSettings.default" :disabled="!canSetDefault">设为进入询盘列表时的默认视图</el-checkbox></div></el-form>
    </InquiryActionDialog>
    <AppWindowDialog v-model="priorityVisible" title="设置优先级" :width="420" :height="260" class="inquiry-list-dialog" :close-on-click-modal="!prioritySaving" :close-on-press-escape="!prioritySaving" :show-close="!prioritySaving" destroy-on-close><p>{{ priorityRow?.inquiry_number }}</p><el-form label-position="top" @submit.prevent="submitPriority"><el-form-item label="优先级"><el-select popper-class="inquiry-v4-select" v-model="priorityValue" :disabled="prioritySaving"><el-option value="" label="未设置" /><el-option v-for="item in options?.priorities" :key="item.code" :value="item.code" :label="item.display_name" /></el-select></el-form-item></el-form><template #footer><el-button :disabled="prioritySaving" @click="priorityVisible = false">取消</el-button><el-button type="primary" :loading="prioritySaving" @click="submitPriority">保存</el-button></template></AppWindowDialog>
    <QuotationFromInquiryDialog v-if="quoteRow" v-model="quoteVisible" :inquiry-id="quoteRow.id" :inquiry-etag="quoteRow.etag" @created="refreshAll" />
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.inquiry-page {
  --el-color-primary: #{token.$crm-primary}; --el-color-primary-light-9: #fff4e6; --el-border-color: #ddd6c9; --el-border-radius-base: 5px;
  --el-fill-color-blank: #fcfbf7; --el-text-color-regular: #4d4c48; --el-text-color-placeholder: #968f84;
  height: 100%; min-height: 0; padding: 14px; display: flex; flex-direction: column;
  color: token.$crm-text-primary; background: token.$crm-color-page; font-family: token.$crm-font-body;
  :deep(.el-button) { margin-left: 0; font-family: inherit; font-size: 13px; height: 36px; }
  :deep(.el-button--primary) { --el-button-bg-color: #c84e28; --el-button-border-color: #c84e28; --el-button-hover-bg-color: #b94320; --el-button-hover-border-color: #b94320; --el-button-active-bg-color: #9f351a; }
  :deep(.el-button.is-disabled) { color: #b6aea1; background: #e8e1d5; border-color: #ddd6c9; }
  :deep(.el-input__wrapper), :deep(.el-select__wrapper) { height: 38px; min-height: 38px; background: #fcfbf7; border-radius: 5px; box-shadow: 0 0 0 1px #ddd6c9 inset; font-size: 13px; }
  :deep(.el-input__wrapper.is-focus), :deep(.el-select__wrapper.is-focused) { box-shadow: 0 0 0 2px #3898ec inset; }
  img { width: 16px; height: 16px; }
  :deep(.el-button > span) { gap: 8px; }
  button:focus-visible { outline: 2px solid #3898ec; outline-offset: 2px; }
}
.create-button { width: 140px; }
.export-button { width: 110px; }
.estimated-amount { font-size: 13px; }
.quick-filters { display: flex; height: 46px; flex: none; margin-top: 4px; border: 1px solid #eae4da; border-radius: 5px; background: #f0eadf; overflow: hidden;
  button { position: relative; height: 46px; display: flex; align-items: center; justify-content: center; gap: 14px; padding: 0; border: 0; background: transparent; color: #6f6a61; font: 500 13px token.$crm-font-body; cursor: pointer;
    span { font-size: 12px; }
    &:hover { background: #fff6ea; }
    &.active { color: #1f1d18; font-weight: 700; span { color: #c84e28; } &::after { content: ''; position: absolute; height: 4px; background: #c84e28; bottom: 1px; left: 0; right: 0; } }
  }
}
.filters { flex: none; display: flex; align-items: center; gap: 14px; height: 38px; margin-top: 17px;
  .search-filter { width: 410px; } .status-filter { width: 160px; } .source-filter { width: 142px; } .country-filter { width: 176px; } .more-filter { width: 130px; height: 38px; }
}
.inquiry-toolbar { flex: none; margin-top: 15px; .assign-button { width: 172px; } .invalid-button { width: 116px; } .sort-button { width: 90px; padding: 0 8px; } .columns-button { width: 104px; padding: 0 12px; } .refresh-button { width: 48px; padding: 0; } }
.saved-view-actions { display: flex; .save-button { width: 110px; border-radius: 5px 0 0 5px; padding: 0 10px; } .saved-menu-button { width: 34px; padding: 0; border-radius: 0 5px 5px 0; border-left: 0; } }
.inquiry-page .data-surface { flex: 1; min-height: 0; margin-top: 22px; border: 1px solid #ddd6c9; border-radius: 6px; background: #fcfbf7; overflow: hidden; display: flex; flex-direction: column;
  .inquiry-table { flex: 1; min-height: 0; --el-table-bg-color: #fcfbf7; --el-table-tr-bg-color: #fcfbf7; --el-table-header-bg-color: #f0eadf; --el-table-border-color: #eae4da; --el-table-row-hover-bg-color: #fff6ea; color: #4d4c48; }
  :deep(.el-table__inner-wrapper::before) { display: none; }
  :deep(th.el-table__cell) { height: 44px; padding: 0; color: #6f6a61; background: #f0eadf; font-weight: 500; }
  :deep(td.el-table__cell) { height: 52px; padding: 0; border-right: 1px solid #eae4da; }
  :deep(.inquiry-table.is-compact td.el-table__cell) { height: 40px; }
  :deep(td.el-table__cell:last-child) { border-right: 0; }
  :deep(.el-table .cell) { padding: 0 16px; font-size: 12px; line-height: 18px; }
  :deep(.el-table th .cell) { font-size: 11px; line-height: 16px; }
  :deep(.el-table__row.is-selected > td) { background: #fff4e6; }
  :deep(.el-checkbox__inner) { height: 14px; width: 14px; border-radius: 2px; }
  :deep(.el-table__empty-block) { min-height: 240px; }
}
.identity { display: block; width: 100%; padding: 0; border: 0; text-align: left; background: transparent; cursor: pointer; font-family: inherit;
  strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; line-height: 20px; color: #1f1d18; font-weight: 700; }
  small { display: block; color: #968f84; font-size: 11px; line-height: 16px; }
  &:hover strong { color: #c84e28; }
}
.secondary { display: block; color: #968f84; font-size: 11px; line-height: 16px; }
.received-date { font-size: 13px; }
.handling-cell { display: inline-flex; flex-direction: column; max-width: 100%; line-height: 16px; small { font-size: 11px; line-height: 14px; overflow: hidden; text-overflow: ellipsis; } }
.missing-value { color: #968f84; } .unassigned, .sla-warning { color: #b8781e; } .sla-danger { color: #b53333; } .sla-success { color: #4f7d4b; }
.row-more { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; padding: 0; border: 0; border-radius: 5px; color: #6f6a61; background: transparent; cursor: pointer; &:hover { background: #f0eadf; } }
.view-link { border: 0; background: transparent; color: #c84e28; cursor: pointer; }
.table-footer { height: 52px; flex: none; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; border-top: 1px solid #eae4da; font-size: 12px; color: #6f6a61; }
.pagination { display: flex; align-items: center; gap: 10px; :deep(.el-select) { width: 136px; } :deep(.el-button) { width: 38px; padding: 0; font-size: 12px; } .active { background: #fcfbf7; border-color: #c84e28; color: #1f1d18; } }
.table-empty { line-height: 24px; p { margin-bottom: 16px; } }
.board { display: flex; gap: 16px; flex: 1; min-height: 0; overflow: auto; margin-top: 22px; .lane { flex: 1; min-width: 260px; padding: 16px; background: #f0eadf; border-radius: 6px; overflow-y: auto; } h2 { font-size: 14px; display: flex; justify-content: space-between; } }
.board-card { display: block; width: 100%; margin-top: 12px; padding: 16px; text-align: left; border: 1px solid #ddd6c9; border-radius: 6px; background: #fcfbf7; font-family: inherit; cursor: pointer; small { display: block; color: #968f84; margin-top: 8px; } footer { display: flex; justify-content: space-between; align-items: center; } }
</style>

<style lang="scss">
.inquiry-list-popover, .inquiry-list-dialog {
  --el-color-primary: #c84e28; --el-color-primary-light-9: #fff4e6; --el-fill-color-blank: #fcfbf7; --el-border-color: #ddd6c9; --el-border-radius-base: 5px;
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif; color: #4d4c48;
  .el-select, .el-date-editor { width: 100%; }
  .el-form-item { margin-bottom: 16px; }
  .popover-footer { display: flex; justify-content: flex-end; gap: 12px; }
  .columns-list, .el-checkbox-group { display: flex; flex-direction: column; }
  .el-button { height: 36px; }
  .inquiry-filter-form { max-height: 680px; overflow-y: auto; padding-right: 4px; }
}
</style>

<style lang="scss">
@use '@/styles/crm/tokens' as token;
.el-popover.inquiry-v4-popover {
  --el-color-primary: #c96442; --el-border-color: #e8e6dc; --el-border-radius-base: 6px; --el-fill-color-blank: #fff;
  padding: 16px 17px; border: 1px solid #e8e6dc; border-radius: 8px; background: #faf9f5; box-shadow: 0 6px 24px rgba(20,20,19,.08); color: #141413; font: 13px token.$crm-font-body;
  h2 { margin: 0 0 12px; font: 700 18px/31px token.$crm-font-display; }
  .el-input__wrapper,.el-select__wrapper,.el-range-editor { min-height: 40px; background: #fff; box-shadow: 0 0 0 1px #e8e6dc inset; border-radius: 6px; }
  .el-input__wrapper.is-focus,.el-select__wrapper.is-focused { box-shadow: 0 0 0 1px token.$crm-focus inset; }
  .el-select,.el-input,.el-date-editor { width: 100%; min-width: 0; }
  .el-form-item { min-width: 0; margin: 0; }
  .el-form-item__label { margin: 0; padding-bottom: 7px; font: 500 12px/20px token.$crm-font-body; }
  .el-input__inner,.el-select__placeholder,.el-range-input { font: 13px token.$crm-font-body; }
  .el-button { min-width: 92px; height: 38px; padding: 0 18px; margin: 0; border-radius: 6px; font-size: 13px; background: #faf9f5; }
  .el-button--primary { background: #c96442; color: #faf9f5; }
  .el-checkbox { margin: 0; height: 38px; }
  .el-checkbox__label { font-size: 13px; color: #141413; }
  .el-checkbox__inner { width: 16px; height: 16px; border-radius: 3px; }
  .el-checkbox__input.is-checked.is-disabled .el-checkbox__inner { background: #c96442; border-color: #c96442; }
}
.inquiry-v4-filters { height: 392px;
  .inquiry-filter-form { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; }
  .popover-footer,.filter-error { grid-column: 1 / -1; }
  .popover-footer { display: flex; justify-content: flex-end; gap: 12px; }
  .filter-error { margin: 0; color: token.$crm-danger; font-size: 12px; line-height: 18px; }
  .el-range-editor { padding: 0 8px; .el-range__icon { display: none; } .el-range-input { width: 42%; font-size: 12px; } }
}
.inquiry-v4-columns { height: 454px; display: flex; flex-direction: column;
  h2 { margin-bottom: 8px !important; } p { margin: 0 0 12px; color: #5e5d59; font-size: 12px; line-height: 20px; }
  .columns-list { overflow-y: auto; flex: 1; min-height: 0; }
  .el-checkbox-group { display: flex; flex-direction: column; }
  [draggable="true"] { cursor: grab; }
}
.inquiry-action-dialog {
  .delete-impact { margin: 14px 0; font-size: 13px; line-height: 22px; font-weight: 600; }
  .delete-hint { margin-top: 14px; }
  .el-form.save-view-form { margin-top: 0; .el-form-item:last-of-type { margin-bottom: 8px; } }
  .save-view-checks { display: flex; flex-direction: column; gap: 8px; .el-checkbox { margin: 0; height: 24px; } .el-checkbox__label { font-size: 13px; color: #141413; } }
}
.inquiry-v4-select { --el-color-primary: #c96442; --el-fill-color-light: #f5e8e2; font-family: token.$crm-font-body; }
</style>
