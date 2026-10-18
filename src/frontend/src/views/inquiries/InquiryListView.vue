<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { ArrowLeft, ArrowRight, Plus } from '@element-plus/icons-vue'
import { More } from '@icon-park/vue-next'
import { assignInquiry, deleteInquiry, exportInquiries, fetchInquiryDeletionPreview, fetchInquiryBoard, fetchInquiryOptions, fetchInquiries, markInquiryInvalid, setInquiryPriority } from '@/api/inquiries'
import { useOptions } from '@/composables/useOptions'
import { useAuthStore } from '@/stores/auth'
import type { InquiryDeletionPreview, InquiryOptions, InquiryRow } from '@/types/inquiry'
import InquiryActionDialog from '@/components/inquiries/InquiryActionDialog.vue'
import InquiryNotice from '@/components/inquiries/InquiryNotice.vue'
import CrmPageHeader from '@/components/crm/CrmPageHeader.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import StatusTag from '@/components/customers/CustomerActivityTag.vue'
import QuotationFromInquiryDialog from '@/components/quotations/QuotationFromInquiryDialog.vue'
import filterIcon from '@/assets/crm-v2/filter.svg'
import exportIcon from '@/assets/crm-v2/export.svg'
import searchIcon from '@/assets/crm-v2/search.svg'
import { allRowsAllow, columnChoices, filterKeys, formatEstimatedAmount, formatReceived, readListQuery, slaPresentation, statusTone, priorityTone } from './inquiryListState'
import { handlingStageLabel } from './inquiryWorktime'
import { vGlassSpotlight } from '@/directives/glassSpotlight'

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
const boardLanes = ref<Array<{ code: string; label: string; count: number; cards: InquiryRow[] }>>([])
const moreVisible = ref(false)
const moreFilters = reactive({ ...filters })
const amountInput = ref('')
const filterError = ref('')
const actionError = ref('')
const deleteVisible = ref(false)
const deleteLoading = ref(false)
const deleteError = ref('')
const deleteTarget = ref<InquiryRow | null>(null)
const deletePreview = ref<InquiryDeletionPreview | null>(null)
const deleteEtag = ref('')
const tableColumns = columnChoices.map(item => ({ key: item.key, label: item.label, width: ({ country:113, source:110, priority:114, owner:119, amount:162, product:160, received:180, sla:130, status:130, reminder:130 } as Record<string, number>)[item.key] }))
const dateShortcuts = [{ text: '最近 30 天', value: () => { const end = new Date(); const start = new Date(); start.setDate(start.getDate() - 29); return [start, end] } }]
watch(moreVisible, opened => {
  if (!opened) return
  Object.assign(moreFilters, filters); filterError.value = ''
  amountInput.value = filters.amount_min ? `${filters.amount_currency} ${filters.amount_min}` : ''
  receivedRange.value = filters.received_from && filters.received_to ? [filters.received_from.slice(0,10), filters.received_to.slice(0,10)] : null
})
const receivedRange = ref<[string, string] | null>(filters.received_from && filters.received_to ? [filters.received_from.slice(0, 10), filters.received_to.slice(0, 10)] : null)
const exporting = ref(false)
const actionVisible = ref(false)
const actionKind = ref<'assign' | 'mark_invalid'>('assign')
const actionRows = ref<InquiryRow[]>([])
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
let disposed = false
let initialized = false
const canAssign = computed(() => auth.hasPermission('inquiries.assign_inquiry'))
const canChange = computed(() => auth.hasPermission('inquiries.change_inquiry'))
const canDelete = computed(() => auth.hasPermission('inquiries.delete_inquiry'))
const canMarkInvalid = computed(() => auth.hasPermission(auth.user?.sales_access_enabled ? 'access_control.markinvalid_inquiry' : 'inquiries.change_inquiry'))
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const visiblePages = computed(() => { const start = Math.max(1, Math.min(page.value - 2, totalPages.value - 4)); return Array.from({ length: Math.min(5, totalPages.value) }, (_, index) => start + index) })
const extraCount = computed(() => [filters.owner_employee_id, filters.assignment_status, filters.sla_state, filters.product_q, filters.received_from || filters.received_to, filters.has_quotation, filters.priority, filters.amount_min].filter(Boolean).length)
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
  loading.value = true; errorMessage.value = ''
  try {
    if (view.value === 'board') {
      const result = await fetchInquiryBoard(query())
      if (disposed || version !== requestVersion) return
      boardLanes.value = result.lanes
      total.value = result.lanes.reduce((count, lane) => count + lane.count, 0)
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
function searchInquiries() {
  filters.q = filters.q.trim()
  applyFilters()
}
function handleSearchEnter(event: KeyboardEvent) {
  if (event.isComposing) return
  event.preventDefault()
  searchInquiries()
}
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
function changePage(value: number) { if (loading.value || value < 1 || value > totalPages.value) return; page.value = value; void syncUrl() }
function changeSize() { page.value = 1; void syncUrl() }
function routeTo(name: 'inquiry-create' | 'inquiry-detail', id?: string) { void router.push({ name, params: id ? { inquiryId: id } : {} }) }
function openAction(kind: 'assign' | 'mark_invalid', row: InquiryRow) {
  const targets = [row]
  if (loading.value || !allRowsAllow(targets, kind)) return
  if (kind === 'assign' ? !canAssign.value : !canMarkInvalid.value) return
  actionKind.value = kind; actionRows.value = [...targets]
  Object.assign(form, { ownerId: '', reason: '', reasonCode: options.value?.invalid_reason_codes.includes('OTHER') ? 'OTHER' : options.value?.invalid_reason_codes[0] || '', reasonDetail: '' })
  actionError.value = ''; actionVisible.value = true
}
async function submitAction() {
  if (acting.value || !allRowsAllow(actionRows.value, actionKind.value)) return
  const assigning = actionKind.value === 'assign'
  if (assigning ? !canAssign.value : !canMarkInvalid.value) return
  if (assigning && !options.value?.owners.some(owner => owner.id === form.ownerId)) { actionError.value = '请选择可分配的负责人。'; return }
  if (!assigning && !options.value?.invalid_reason_codes.includes(form.reasonCode)) { actionError.value = '请选择无效原因。'; return }
  acting.value = true; actionError.value = ''
  const first = actionRows.value[0]!
  try {
    if (assigning) {
      await assignInquiry(first.id, first.etag, form.ownerId, form.reason.trim())
    } else {
      await markInquiryInvalid(first.id, first.etag, form.reasonCode, form.reasonDetail.trim())
    }
    actionVisible.value = false; acting.value = false; ElMessage.success(assigning ? '负责人已分配。' : '询盘已标记为无效。'); await load()
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
    deleteVisible.value = false; acting.value = false; ElMessage.success('询盘已永久删除。'); await load()
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
    priorityVisible.value = false; prioritySaving.value = false; ElMessage.success('优先级已保存。'); await load()
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
watch(() => route.query, () => { if (initialized) { restoreQuery(); void load() } })
onMounted(async () => {
  void loadOptions()
  initialized = true
  restoreQuery()
  await load()
})
onBeforeRouteLeave(() => !(acting.value || prioritySaving.value))
onBeforeRouteUpdate(() => !(acting.value || prioritySaving.value))
onBeforeUnmount(() => { disposed = true; requestVersion++ })
</script>

<template>
  <section class="inquiry-page erp-glass-list" aria-label="询盘列表">
    <section v-glass-spotlight class="erp-list-filter" aria-label="筛选询盘">
    <CrmPageHeader class="erp-list-heading" title="询盘列表" :count="total" count-label="条询盘" />
    <div class="filters erp-list-filters">
      <el-input
        v-model="filters.q"
        class="search-filter"
        aria-label="搜索询盘"
        title="支持客户名称、询盘编号、主题或描述"
        placeholder="搜索客户、编号等"
        clearable
        @keydown.enter="handleSearchEnter"
        @clear="searchInquiries"
      >
        <template #suffix>
          <button type="button" class="inquiry-search-button" aria-label="搜索询盘列表" @click="searchInquiries">
            <img :src="searchIcon" alt="" aria-hidden="true" />
          </button>
        </template>
      </el-input>
      <el-select popper-class="inquiry-v4-select" v-model="filters.status" class="status-filter" aria-label="状态筛选" placeholder="状态：全部" clearable @change="applyFilters"><el-option v-for="item in options?.statuses" :key="item.code" :label="item.display_name" :value="item.code" /></el-select>
      <el-select popper-class="inquiry-v4-select" v-model="filters.source_code" class="source-filter" aria-label="来源筛选" placeholder="来源：全部" clearable @change="applyFilters"><el-option v-for="item in options?.sources" :key="item.item_code" :label="item.display_name" :value="item.item_code" /></el-select>
      <el-select popper-class="inquiry-v4-select" v-model="filters.country_code" class="country-filter" aria-label="国家地区筛选" placeholder="国家/地区：全部" filterable clearable @change="applyFilters"><el-option v-for="country in options?.countries" :key="country" :label="country" :value="country" /></el-select>
      <el-popover v-model:visible="moreVisible" trigger="click" placement="bottom-end" :width="520" :show-arrow="false" popper-class="inquiry-v4-popover inquiry-v4-filters erp-list-filter-popover">
        <template #reference><el-button class="more-filter erp-button-motion"><img :src="filterIcon" alt="" />更多筛选<span v-if="extraCount">({{ extraCount }})</span></el-button></template>
        <h2>更多筛选</h2>
        <el-form label-position="top" class="inquiry-filter-form" @submit.prevent="applyMore">
          <el-form-item label="负责人"><el-select popper-class="inquiry-v4-select" v-model="moreFilters.owner_employee_id" placeholder="全部负责人" filterable clearable><el-option v-for="item in options?.owners" :key="item.id" :label="item.display_name" :value="item.id" /></el-select></el-form-item>
          <el-form-item label="优先级"><el-select popper-class="inquiry-v4-select" v-model="moreFilters.priority" placeholder="全部优先级" clearable><el-option v-for="item in options?.priorities" :key="item.code" :value="item.code" :label="item.display_name" /><el-option value="UNSET" label="未设置" /></el-select></el-form-item>
          <el-form-item label="处理时限状态"><el-select popper-class="inquiry-v4-select" v-model="moreFilters.sla_state" placeholder="全部" clearable><el-option label="即将超时、已超时" value="RISK"/><el-option label="即将超时" value="DUE_SOON"/><el-option label="已超时" value="BREACHED"/><el-option label="无进行中的计时" value="NONE"/></el-select></el-form-item>
          <el-form-item label="接收日期"><el-date-picker popper-class="inquiry-v4-select" v-model="receivedRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" :shortcuts="dateShortcuts"/></el-form-item>
          <el-form-item label="预估金额"><el-input v-model="amountInput" aria-label="预估金额筛选" placeholder="USD 10,000 以上" clearable @keyup.enter="applyMore"/></el-form-item>
          <el-form-item label="产品关键词"><el-input v-model="moreFilters.product_q" placeholder="折叠椅 / 露营桌" clearable @keyup.enter="applyMore"/></el-form-item>
          <p v-if="filterError" class="filter-error" role="alert">{{ filterError }}</p>
          <div class="popover-footer"><el-button class="erp-button-motion" @click="resetMore">重置</el-button><el-button class="erp-button-motion" type="primary" @click="applyMore">应用筛选</el-button></div>
        </el-form>
      </el-popover>
      <div class="erp-list-filter-actions"><el-button class="erp-button-motion" @click="resetFilters">重置</el-button><el-button class="erp-button-motion" type="primary" @click="searchInquiries">应用筛选</el-button></div>
    </div>
    </section>
    <section class="data-surface erp-list-data" aria-label="询盘数据">
      <div class="inquiry-actions erp-list-toolbar">
        <el-button v-if="auth.hasPermission('inquiries.add_inquiry')" type="primary" class="create-button erp-button-motion" :icon="Plus" @click="routeTo('inquiry-create')">新建询盘</el-button>
        <el-button v-if="auth.hasPermission('inquiries.view_inquiry')" class="export-button erp-button-motion" :loading="exporting" @click="downloadExport"><img v-if="!exporting" :src="exportIcon" alt="" />导出</el-button>
      </div>
    <div v-if="view === 'list'" class="inquiry-list-body">
      <div class="erp-list-table-frame">
      <el-table v-loading="loading" :data="rows" row-key="id" height="100%" class="inquiry-table is-compact">
        <el-table-column prop="inquiry_number" label="询盘编号" width="180" show-overflow-tooltip />
        <el-table-column label="客户名称" min-width="249"><template #default="{ row }"><button class="identity" @click="routeTo('inquiry-detail', row.id)"><strong :title="row.customer.name">{{ row.customer.name || '—' }}</strong></button></template></el-table-column>
        <el-table-column v-for="column in tableColumns" :key="column.key" :label="column.label" :width="column.width" show-overflow-tooltip><template #default="{ row }">
            <template v-if="column.key === 'country'">{{ row.customer.country_code || '—' }}</template>
            <template v-else-if="column.key === 'source'">{{ row.source.display_name || '—' }}</template>
            <template v-else-if="column.key === 'priority'"><StatusTag v-if="row.priority" :label="row.priority_display || row.priority" :tone="priorityTone(row.priority)" /><span v-else class="missing-value">—</span></template>
            <template v-else-if="column.key === 'owner'"><span :class="{ 'unassigned': !row.owner }">{{ row.owner?.display_name || '未分配' }}</span></template>
            <template v-else-if="column.key === 'amount'"><strong class="estimated-amount" :class="{ 'missing-value': formatEstimatedAmount(row) === '—' }">{{ formatEstimatedAmount(row) }}</strong></template>
            <template v-else-if="column.key === 'product'">{{ row.product_summary.first_description || '—' }}<small v-if="row.product_summary.item_count > 1" class="secondary">等 {{ row.product_summary.item_count }} 项</small></template>
            <template v-else-if="column.key === 'received'"><span class="received-date">{{ formatReceived(row.received_at).date }} {{ formatReceived(row.received_at).time }}</span></template>
            <template v-else-if="column.key === 'sla'"><span class="handling-cell" :title="row.sla_summary.working_time ? '按工作时间计算，午休及休息时间不计时' : '按原连续时间规则计算'" :class="`sla-${slaPresentation(row.sla_summary).tone}`"><small v-if="row.sla_summary.stage_code">{{ handlingStageLabel(row.sla_summary.stage_code) }}<span v-if="(row.sla_summary.active_count ?? 0) > 1"> 等{{ row.sla_summary.active_count }}项</span></small><span>{{ slaPresentation(row.sla_summary).label }}</span></span></template>
            <template v-else-if="column.key === 'status'"><StatusTag :label="row.display_stage_label || row.status_display || '—'" :tone="statusTone(row.status)" /></template>
            <template v-else-if="column.key === 'reminder'"><StatusTag v-if="row.sla_summary.state !== 'NONE'" :label="slaPresentation(row.sla_summary).reminder" :tone="slaPresentation(row.sla_summary).tone" /><span v-else class="missing-value">—</span></template>
        </template></el-table-column>
        <el-table-column label="操作" width="100" align="center" fixed="right"><template #default="{ row }"><el-dropdown :persistent="false" popper-class="inquiry-v4-select" v-if="hasRowActions(row)" trigger="click" @command="(command: string) => rowCommand(command, row)"><button class="row-more" :aria-label="`${row.inquiry_number} 更多操作`" :disabled="loading || acting"><More theme="filled" :size="24" /></button><template #dropdown><el-dropdown-menu><el-dropdown-item @click="routeTo('inquiry-detail', row.id)">查看询盘</el-dropdown-item><el-dropdown-item v-if="canChange && row.allowed_actions.set_priority" command="priority">设置优先级</el-dropdown-item><el-dropdown-item v-if="canAssign && row.allowed_actions.assign" command="assign">分配负责人</el-dropdown-item><el-dropdown-item v-if="row.allowed_actions.create_quotation" command="quote">创建报价</el-dropdown-item><el-dropdown-item v-if="canMarkInvalid && row.allowed_actions.mark_invalid" command="mark_invalid">标记无效</el-dropdown-item><el-dropdown-item v-if="canDelete && auth.canFor('inquiries.delete_inquiry', row)" command="delete" divided>永久删除</el-dropdown-item></el-dropdown-menu></template></el-dropdown><button v-else class="view-link" @click="routeTo('inquiry-detail', row.id)">查看</button></template></el-table-column>
        <template #empty><div class="table-empty" role="status"><template v-if="errorMessage"><p>{{ errorMessage }}</p><el-button @click="load">重新加载</el-button></template><template v-else-if="!loading"><p>暂无符合条件的询盘</p><el-button @click="resetFilters">清除筛选</el-button></template></div></template>
      </el-table>
      </div>
      <footer class="table-footer erp-list-footer"><span aria-live="polite">共 {{ total }} 条</span><div class="pagination"><el-select popper-class="inquiry-v4-select" v-model="pageSize" aria-label="每页条数" :disabled="loading" @change="changeSize"><el-option v-for="size in [20, 50, 100]" :key="size" :value="size" :label="`${size} 条 / 页`" /></el-select><el-button :icon="ArrowLeft" :disabled="loading || page <= 1" aria-label="上一页" @click="changePage(page - 1)" /><el-button v-for="number in visiblePages" :key="number" :class="{ active: page === number }" :aria-current="page === number ? 'page' : undefined" :aria-label="`第 ${number} 页`" :disabled="loading" @click="changePage(number)">{{ number }}</el-button><el-button :icon="ArrowRight" :disabled="loading || page >= totalPages" aria-label="下一页" @click="changePage(page + 1)" /></div></footer>
    </div>
    <div v-else v-loading="loading" class="board"><el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" /><section v-for="lane in boardLanes" :key="lane.code" class="lane"><h2>{{ lane.label }} <span>{{ lane.count }}</span></h2><button v-for="card in lane.cards" :key="card.id" class="board-card" @click="routeTo('inquiry-detail', card.id)"><strong>{{ card.customer.name }}</strong><small>{{ card.inquiry_number }}</small><p>{{ card.product_summary.first_description || card.subject }}</p><footer>{{ card.owner?.display_name || '未分配' }}<StatusTag :label="slaPresentation(card.sla_summary).reminder" :tone="slaPresentation(card.sla_summary).tone" /></footer></button><el-empty v-if="!lane.cards.length" description="暂无数据" :image-size="50" /></section></div>
    </section>
    <InquiryActionDialog v-model="actionVisible" :title="actionKind === 'assign' ? '分配负责人' : '标记无效'" :subtitle="`已选择 ${actionRows.length} 条询盘`" :width="actionKind === 'assign' ? 520 : 500" :height="actionKind === 'assign' ? 468 : 482" :confirm-width="96" :busy="acting" :disabled="!options" :error="actionError" :danger="actionKind !== 'assign'" :confirm-label="`${actionKind === 'assign' ? '确认分配' : '确认标记'}`" @confirm="submitAction">
      <InquiryNotice v-if="actionKind === 'assign'" title="确认后更新询盘负责人">分配人、原负责人、新负责人和分配时间将保留在历史记录中。</InquiryNotice>
      <InquiryNotice v-else tone="warning" title="关闭后仍保留全部询盘记录">无效询盘不计入转化率；系统记录操作人、原因和时间。</InquiryNotice>
      <el-form label-position="top" :disabled="acting" @submit.prevent="submitAction"><template v-if="actionKind === 'assign'"><el-form-item label="负责人" required><el-select popper-class="inquiry-v4-select" v-model="form.ownerId" filterable placeholder="请选择负责人"><el-option v-for="owner in options?.owners" :key="owner.id" :value="owner.id" :label="`${owner.display_name}（${owner.employee_code}）`"/></el-select></el-form-item><el-form-item label="分配说明"><el-input v-model="form.reason" type="textarea" maxlength="500" :input-style="{ height: '72px' }"/></el-form-item></template><template v-else><el-form-item label="无效原因" required><el-select popper-class="inquiry-v4-select" v-model="form.reasonCode"><el-option v-for="reason in options?.invalid_reason_codes" :key="reason" :value="reason" :label="invalidReasonLabels[reason] || reason"/></el-select></el-form-item><el-form-item label="说明"><el-input v-model="form.reasonDetail" type="textarea" maxlength="1000" :input-style="{ height: '88px' }"/></el-form-item></template></el-form>
    </InquiryActionDialog>
    <InquiryActionDialog v-model="deleteVisible" title="永久删除询盘" :subtitle="deletePreview?.inquiry_number || deleteTarget?.inquiry_number || ''" :width="520" :height="406" confirm-label="确认永久删除" :confirm-width="126" danger :busy="acting" :loading="deleteLoading" :disabled="!deletePreview || !deleteEtag" :error="deleteError" @confirm="submitDelete">
      <InquiryNotice tone="danger" title="删除后无法恢复">该询盘及关联的报价、样品、任务和业务关系将一并删除。</InquiryNotice>
      <p v-if="deletePreview" class="delete-impact">关联概览：{{ deletePreview.quotation_count }} 份报价 · {{ deletePreview.sample_count }} 个样品申请 · {{ deletePreview.task_count }} 条任务 · {{ deletePreview.inquiry_file_link_count }} 个询盘附件关联</p>
      <p class="inquiry-dialog-hint delete-hint">业务关闭请优先使用“标记无效”；仅在误建且确认无保留价值时永久删除。其他依赖关系也会按现有删除规则处理。</p>
      <el-button v-if="deleteError" :disabled="acting" @click="loadDeletePreview">重新核对关联记录</el-button>
    </InquiryActionDialog>
    <AppWindowDialog v-model="priorityVisible" title="设置优先级" :width="420" :height="260" class="inquiry-list-dialog" :close-on-click-modal="!prioritySaving" :close-on-press-escape="!prioritySaving" :show-close="!prioritySaving" destroy-on-close><p>{{ priorityRow?.inquiry_number }}</p><el-form label-position="top" @submit.prevent="submitPriority"><el-form-item label="优先级"><el-select popper-class="inquiry-v4-select" v-model="priorityValue" :disabled="prioritySaving"><el-option value="" label="未设置" /><el-option v-for="item in options?.priorities" :key="item.code" :value="item.code" :label="item.display_name" /></el-select></el-form-item></el-form><template #footer><el-button :disabled="prioritySaving" @click="priorityVisible = false">取消</el-button><el-button type="primary" :loading="prioritySaving" @click="submitPriority">保存</el-button></template></AppWindowDialog>
    <QuotationFromInquiryDialog v-if="quoteRow" v-model="quoteVisible" :inquiry-id="quoteRow.id" :inquiry-etag="quoteRow.etag" @created="load" />
  </section>
</template>

<style scoped lang="scss">
.inquiry-list-body { display: flex; flex: 1; flex-direction: column; min-height: 0; }
.create-button { width: 112px; }
.export-button { width: 76px; }
.inquiry-search-button {
  display: inline-flex; width: 20px; height: 24px; align-items: center; justify-content: center;
  margin: 0; padding: 0; border: 0; color: inherit; background: transparent; cursor: pointer;
  img { width: 16px; height: 16px; }
}
button:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
.filters {
  .search-filter { width: 250px; max-width: 100%; flex: none; }
  .status-filter { width: 128px; flex: none; }
  .source-filter { width: 120px; flex: none; }
  .country-filter { width: 160px; flex: none; }
  .more-filter { min-width: 102px; flex: none; }
}
.identity { display: block; width: 100%; padding: 0; border: 0; text-align: left; background: transparent; cursor: pointer; font-family: inherit;
  strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; line-height: 20px; color: var(--erp-table-text); font-weight: 700; }
  small { display: block; color: var(--erp-table-text); font-size: 11px; line-height: 16px; }
  &:hover strong { text-decoration: underline; }
}
.estimated-amount, .received-date { font-size: 13px; }
.received-date { white-space: nowrap; }
.secondary { display: block; color: var(--erp-table-text); font-size: 11px; line-height: 16px; }
.handling-cell { display: inline-flex; flex-direction: column; max-width: 100%; line-height: 16px; small { font-size: 11px; line-height: 14px; overflow: hidden; text-overflow: ellipsis; } }
.missing-value, .unassigned { color: var(--erp-table-text); }
.sla-warning { color: var(--erp-color-warning); } .sla-danger { color: var(--erp-color-danger); } .sla-success { color: var(--erp-color-success); }
.row-more { display: flex; align-items: center; justify-content: center; width: 32px; height: 32px; padding: 0; border: 0; border-radius: var(--erp-radius-control); color: var(--erp-table-text); background: transparent; cursor: pointer; &:hover { background: var(--erp-table-hover); } }
.view-link { border: 0; background: transparent; color: var(--erp-table-text); cursor: pointer; }
.table-empty { line-height: 24px; p { margin-bottom: 16px; } }
.board { display: flex; gap: 16px; flex: 1; min-height: 0; overflow: auto; padding-bottom: 10px;
  .lane { flex: 1; min-width: 260px; padding: 16px; background: var(--erp-glass-inner-background); border-radius: var(--erp-radius-control); overflow-y: auto; }
  h2 { font-size: 14px; display: flex; justify-content: space-between; }
}
.board-card { display: block; width: 100%; margin-top: 12px; padding: 16px; text-align: left; border: 1px solid var(--erp-color-border); border-radius: var(--erp-radius-control); background: var(--erp-color-surface); font-family: inherit; cursor: pointer;
  small { display: block; color: var(--erp-color-text-secondary); margin-top: 8px; }
  footer { display: flex; justify-content: space-between; align-items: center; }
}
</style>

<style lang="scss">
.inquiry-list-popover, .inquiry-list-dialog {
  --el-color-primary: var(--erp-color-brand); --el-color-primary-light-9: var(--erp-color-selected); --el-fill-color-blank: var(--erp-color-surface); --el-border-color: var(--erp-color-border); --el-border-radius-base: var(--erp-radius-control);
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif; color: var(--erp-color-text-primary);
  .el-select, .el-date-editor { width: 100%; }
  .el-form-item { margin-bottom: 16px; }
  .popover-footer { display: flex; justify-content: flex-end; gap: 12px; }
  .el-button { height: 36px; }
  .inquiry-filter-form { max-height: 680px; overflow-y: auto; padding-right: 4px; }
}
</style>

<style lang="scss">
@use '@/styles/crm/tokens' as token;
.el-popover.inquiry-v4-popover {
  --el-color-primary: var(--erp-color-brand); --el-border-color: var(--erp-color-border); --el-border-radius-base: var(--erp-radius-control); --el-fill-color-blank: var(--erp-color-surface);
  padding: 16px 17px; border: 1px solid var(--erp-color-border); border-radius: 8px; background: var(--erp-color-subtle); box-shadow: 0 6px 24px color-mix(in srgb, var(--erp-shadow-color) 8%, transparent); color: var(--erp-color-text-primary); font: 13px token.$crm-font-body;
  h2 { margin: 0 0 12px; font: 700 18px/31px token.$crm-font-display; }
  .el-input__wrapper,.el-select__wrapper,.el-range-editor { height: 32px; min-height: 32px; background: var(--erp-input-background); box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-border) inset; border-radius: var(--erp-radius-control); }
  .el-input__wrapper.is-focus,.el-select__wrapper.is-focused { box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-focus-border) inset; }
  .el-select,.el-input,.el-date-editor { width: 100%; min-width: 0; }
  .el-form-item { min-width: 0; margin: 0; }
  .el-form-item__label { margin: 0; padding-bottom: 7px; font: 500 12px/20px token.$crm-font-body; }
  .el-input__inner,.el-select__placeholder,.el-range-input { font: 13px token.$crm-font-body; }
  .el-button { min-width: 92px; height: 38px; padding: 0 18px; margin: 0; border-radius: 6px; font-size: 13px; background: var(--erp-color-subtle); }
  .el-button--primary { background: var(--erp-button-primary-surface); color: var(--erp-button-primary-text); }
}
.inquiry-v4-filters { height: 392px;
  .inquiry-filter-form { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 12px; }
  .popover-footer,.filter-error { grid-column: 1 / -1; }
  .popover-footer { display: flex; justify-content: flex-end; gap: 12px; }
  .filter-error { margin: 0; color: token.$crm-danger; font-size: 12px; line-height: 18px; }
  .el-range-editor { padding: 0 8px; .el-range__icon { display: none; } .el-range-input { width: 42%; font-size: 12px; } }
}
.inquiry-action-dialog {
  .delete-impact { margin: 14px 0; font-size: 13px; line-height: 22px; font-weight: 600; }
  .delete-hint { margin-top: 14px; }
}
.inquiry-v4-select { font-family: token.$crm-font-body; }
</style>
