<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { MoreFilled, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import { createQuotationDraft, deleteQuotation, exportQuotations, fetchQuotation, fetchQuotationCreationOptions, fetchQuotationOptions, fetchQuotations } from '@/api/quotations'
import { fetchAllMasterDataRecords } from '@/api/referenceData'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import CrmPageHeader from '@/components/crm/CrmPageHeader.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import exportIcon from '@/assets/crm-v2/export.svg'
import searchIcon from '@/assets/crm-v2/search.svg'
import { useAuthStore } from '@/stores/auth'
import type { QuotationCreationOption, QuotationListItem, QuotationListOptions, QuotationListQuery } from '@/types/quotation'
import type { Currency } from '@/types/referenceData'

interface FilterForm {
  search: string
  display_status: string
  owner_employee_id: string
  currency_code: string
  valid_to: string
}

const authStore = useAuthStore()
const route = useRoute()
const router = useRouter()
let listRequest = 0
let disposed = false
const loading = ref(false)
const optionLoading = ref(false)
const exportLoading = ref(false)
const errorMessage = ref('')
const rows = ref<QuotationListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const options = ref<QuotationListOptions | null>(null)
const filters = reactive<FilterForm>({ search: '', display_status: '', owner_employee_id: '', currency_code: '', valid_to: '' })
const moreFiltersVisible = ref(false)
const createVisible = ref(false)
const createLoading = ref(false)
const createCustomerLoading = ref(false)
const createEntityLoading = ref(false)
const createCustomers = ref<QuotationCreationOption[]>([])
const createCurrencies = ref<Currency[]>([])
const createForm = reactive({ customer_account_id: '', transaction_entity_id: '', subject: '', currency_code: '', valid_until: '' })

const canCreate = computed(() => authStore.hasPermission('quotations.add_quotation'))
const canExport = computed(() => authStore.hasPermission('quotations.export_quotation'))
const canDelete = computed(() => authStore.hasPermission('quotations.delete_quotation'))
function buildQuery(): QuotationListQuery {
  const query: QuotationListQuery = { page: page.value, page_size: pageSize.value, ordering: '-updated_at' }
  if (filters.search.trim()) query.q = filters.search.trim()
  if (filters.display_status) query.display_status = filters.display_status
  if (filters.owner_employee_id) query.owner_employee_id = filters.owner_employee_id
  if (filters.currency_code) query.currency_code = filters.currency_code
  if (filters.valid_to) query.valid_to = filters.valid_to
  if (typeof route.query.customer_id === 'string') query.customer_id = route.query.customer_id
  return query
}

function getErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务后重试。'
  const detail = (error.response.data as { detail?: string; error?: { message?: string } })
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有查看报价的权限。'
  if (error.response.status >= 500) return '报价服务暂时异常，请稍后重试。'
  return detail.error?.message || detail.detail || '请求失败，请检查筛选条件。'
}

async function loadRows() {
  const request = ++listRequest
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchQuotations(buildQuery())
    if (disposed || request !== listRequest) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (error) {
    if (disposed || request !== listRequest) return
    rows.value = []
    total.value = 0
    errorMessage.value = getErrorMessage(error)
  } finally {
    if (!disposed && request === listRequest) loading.value = false
  }
}

async function loadOptions() {
  optionLoading.value = true
  try {
    options.value = await fetchQuotationOptions()
  } catch (error) {
    ElMessage.warning(`报价筛选项加载失败：${getErrorMessage(error)}`)
  } finally {
    optionLoading.value = false
  }
}

function search() {
  page.value = 1
  void loadRows()
}

function handleSearchEnter(event: KeyboardEvent) {
  if (event.isComposing) return
  event.preventDefault()
  search()
}

function reset() {
  Object.assign(filters, { search: '', display_status: '', owner_employee_id: '', currency_code: '', valid_to: '' })
  search()
}

function reloadQuotationList() {
  void loadRows()
}

function statusClass(status: string): string {
  return `status--${status.toLowerCase().replaceAll('_', '-')}`
}

function formatAmount(row: QuotationListItem): string {
  const version = row.current_version
  if (!version) return '未填写'
  return `${version.currency_code} ${Number(version.total_amount).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
}

function formatUpdated(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未记录'
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}`
}

async function exportList() {
  if (!canExport.value) return
  exportLoading.value = true
  try {
    const blob = await exportQuotations(buildQuery())
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `报价列表_${new Date().toISOString().slice(0, 10)}.xlsx`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('报价列表已导出。')
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    exportLoading.value = false
  }
}

function openDetail(row: QuotationListItem) {
  void router.push({ name: 'quotation-edit', params: { quotationId: row.id } })
}

function openPreview(row: QuotationListItem) {
  void router.push({ name: 'quotation-preview', params: { quotationId: row.id } })
}

async function deleteQuotationRow(row: QuotationListItem) {
  try {
    const current = await fetchQuotation(row.id)
    await ElMessageBox.confirm(
      `确定永久删除报价「${current.data.quotation_number}」吗？其全部版本、明细、关联样品和任务会一并删除，且无法恢复。`,
      '永久删除报价',
      { type: 'error', confirmButtonText: '确认永久删除', cancelButtonText: '取消' },
    )
    const result = await deleteQuotation(row.id, current.etag)
    ElMessage.success(`报价已永久删除，同时删除 ${result.deleted_count} 条关联数据。`)
    await loadRows()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error))
  }
}

function openVersions(row: QuotationListItem) {
  void router.push({ name: 'quotation-versions', params: { quotationId: row.id } })
}

function openCreate() {
  if (!canCreate.value) return
  if (!authStore.user?.employee) {
    ElMessage.error('当前账号未绑定有效员工档案，不能创建报价。')
    return
  }
  const presetCustomerId = typeof route.query.customer_id === 'string' ? route.query.customer_id : ''
  Object.assign(createForm, { customer_account_id: presetCustomerId, transaction_entity_id: '', subject: '', currency_code: '', valid_until: '' })
  createVisible.value = true
  void Promise.all([loadCreateCustomers(), loadCreateCurrencies()]).then(() => {
    if (createForm.customer_account_id) void loadCreateEntities()
  })
}

async function loadCreateCustomers() {
  createCustomerLoading.value = true
  try {
    createCustomers.value = await fetchQuotationCreationOptions()
  } catch (error) {
    ElMessage.error(`可建报价客户加载失败：${getErrorMessage(error)}`)
  } finally {
    createCustomerLoading.value = false
  }
}

async function loadCreateCurrencies() {
  try {
    createCurrencies.value = await fetchAllMasterDataRecords<Currency>('currencies', { status: 'ACTIVE' })
  } catch (error) {
    ElMessage.error(`可用币种加载失败：${getErrorMessage(error)}`)
  }
}

async function loadCreateEntities() {
  createForm.transaction_entity_id = ''
  if (!createForm.customer_account_id) return
  createEntityLoading.value = true
  try {
    const selected = createCustomers.value.find((customer) => customer.id === createForm.customer_account_id)
    if (!selected) throw new Error('未找到可创建报价的客户。')
    if (selected.entities.length === 1) createForm.transaction_entity_id = selected.entities[0].id
  } catch (error) {
    ElMessage.error(`客户交易主体加载失败：${getErrorMessage(error)}`)
  } finally {
    createEntityLoading.value = false
  }
}

async function submitCreate() {
  const employee = authStore.user?.employee
  if (!employee) return
  if (!createForm.customer_account_id || !createForm.transaction_entity_id || !createForm.subject.trim() || !createForm.currency_code.trim()) {
    ElMessage.warning('请填写客户、交易主体、报价主题和币种。')
    return
  }
  createLoading.value = true
  try {
    const quotation = await createQuotationDraft({
      customer_account_id: createForm.customer_account_id,
      transaction_entity_id: createForm.transaction_entity_id,
      owner_employee_id: employee.id,
      subject: createForm.subject.trim(),
      currency_code: createForm.currency_code.trim().toUpperCase(),
      valid_until: createForm.valid_until || null,
    })
    createVisible.value = false
    ElMessage.success('报价草稿已创建。')
    await router.push({ name: 'quotation-edit', params: { quotationId: quotation.data.id } })
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    createLoading.value = false
  }
}

onBeforeUnmount(() => { disposed = true; listRequest++ })
onMounted(async () => {
  await Promise.all([loadRows(), loadOptions()])
  if (route.query.create === '1') openCreate()
})
</script>

<template>
  <section class="quotation-list-page erp-glass-list" aria-label="报价列表">
    <section v-glass-spotlight class="quotation-filter erp-list-filter" aria-label="筛选报价">
      <CrmPageHeader class="quotation-list-page__heading erp-list-heading" title="报价列表" :count="total" count-label="份报价" />
      <form class="quotation-filter__grid erp-list-filters" @submit.prevent="search">
        <ElInput v-model="filters.search" class="quotation-search" aria-label="搜索报价" placeholder="搜索客户、报价编号等" title="支持客户名称、报价编号或主题" clearable @keydown.enter="handleSearchEnter" @clear="search">
          <template #suffix><button type="button" class="quotation-search-button" aria-label="搜索报价列表" @click="search"><img :src="searchIcon" alt="" aria-hidden="true" /></button></template>
        </ElInput>
        <ElSelect v-model="filters.display_status" class="quotation-status-filter" aria-label="报价状态" placeholder="报价状态：全部" clearable :loading="optionLoading" @change="search"><ElOption v-for="item in options?.display_statuses" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
        <ElSelect v-model="filters.owner_employee_id" class="quotation-owner-filter" aria-label="报价负责人" placeholder="负责人：全部" clearable :loading="optionLoading" @change="search"><ElOption v-for="item in options?.owners" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect>
        <ElSelect v-model="filters.currency_code" class="quotation-currency-filter" aria-label="报价币种" placeholder="币种：全部" clearable :loading="optionLoading" @change="search"><ElOption v-for="item in options?.currencies" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
        <div class="erp-list-filter-actions">
          <ElPopover v-model:visible="moreFiltersVisible" trigger="click" placement="bottom-end" :width="360" popper-class="erp-list-filter-popover">
            <template #reference><ElButton class="erp-button-motion">更多筛选</ElButton></template>
            <div class="quotation-more-content"><ElDatePicker v-model="filters.valid_to" type="date" value-format="YYYY-MM-DD" placeholder="有效期截至" /><ElButton class="erp-button-motion" type="primary" @click="search">应用筛选</ElButton></div>
          </ElPopover>
          <ElButton class="erp-button-motion" @click="reset">重置</ElButton>
          <ElButton class="erp-button-motion" type="primary" @click="search">应用筛选</ElButton>
        </div>
      </form>
    </section>

    <ElAlert v-if="errorMessage" class="quotation-error" type="error" :title="errorMessage" :closable="false" show-icon><template #default><ElButton link @click="reloadQuotationList">重新加载</ElButton></template></ElAlert>

    <section class="quotation-table-card erp-list-data" aria-label="报价数据列表">
      <div class="quotation-list-actions erp-list-toolbar">
        <ElButton v-if="canCreate" class="quotation-create-button erp-button-motion" type="primary" :icon="Plus" @click="openCreate">新建报价</ElButton>
        <ElButton class="quotation-export-button erp-button-motion" :loading="exportLoading" :disabled="!canExport" @click="exportList"><img v-if="!exportLoading" class="quotation-button-icon" :src="exportIcon" alt="" aria-hidden="true" />导出</ElButton>
      </div>
      <div class="erp-list-table-frame">
      <ElTable v-loading="loading" :data="rows" row-key="id" height="100%" border :empty-text="errorMessage ? '报价列表加载失败' : '暂无报价，可点击新建报价。'">
        <ElTableColumn prop="quotation_number" label="报价编号" width="190"><template #default="{ row }"><button class="quotation-link" @click="openDetail(row)">{{ row.quotation_number }}</button></template></ElTableColumn>
        <ElTableColumn prop="customer_name" label="客户名称" min-width="308" show-overflow-tooltip />
        <ElTableColumn label="版本" width="64"><template #default="{ row }">{{ row.current_version ? `V${row.current_version.version_number}` : '—' }}</template></ElTableColumn>
        <ElTableColumn label="币种" width="74"><template #default="{ row }">{{ row.current_version?.currency_code || '—' }}</template></ElTableColumn>
        <ElTableColumn label="贸易条款" width="124" show-overflow-tooltip><template #default="{ row }">{{ row.current_version?.incoterm_label || '未填写' }}</template></ElTableColumn>
        <ElTableColumn label="负责人" width="92"><template #default="{ row }">{{ row.owner?.display_name || '未分配' }}</template></ElTableColumn>
        <ElTableColumn label="最近更新" width="156"><template #default="{ row }">{{ formatUpdated(row.current_version?.updated_at || row.updated_at) }}</template></ElTableColumn>
        <ElTableColumn label="有效期" width="156"><template #default="{ row }">{{ row.current_version?.valid_until || '未填写' }}</template></ElTableColumn>
        <ElTableColumn label="报价金额" width="180" align="right"><template #default="{ row }"><b>{{ formatAmount(row) }}</b></template></ElTableColumn>
        <ElTableColumn label="状态" width="126"><template #default="{ row }"><span class="quotation-status" :class="statusClass(row.display_status)">{{ row.display_status_label }}</span></template></ElTableColumn>
        <ElTableColumn label="操作" width="120" align="center" fixed="right"><template #default="{ row }"><ElDropdown :persistent="false" trigger="click"><button class="row-more" aria-label="报价操作"><ElIcon><MoreFilled /></ElIcon></button><template #dropdown><ElDropdownMenu><ElDropdownItem @click="openPreview(row)">预览报价</ElDropdownItem><ElDropdownItem :disabled="!row.allowed_actions.edit" @click="openDetail(row)">编辑报价</ElDropdownItem><ElDropdownItem @click="openVersions(row)">版本记录</ElDropdownItem><ElDropdownItem v-if="canDelete && authStore.canFor('quotations.delete_quotation', row)" divided @click="deleteQuotationRow(row)">永久删除</ElDropdownItem></ElDropdownMenu></template></ElDropdown></template></ElTableColumn>
        <template #empty>
          <ElEmpty :description="errorMessage ? '报价列表加载失败' : '暂无报价'" :image-size="72">
            <ElButton v-if="!errorMessage && canCreate" type="primary" @click="openCreate">新建报价</ElButton>
            <ElButton v-else-if="errorMessage" @click="reloadQuotationList">重新加载</ElButton>
          </ElEmpty>
        </template>
      </ElTable>
      </div>
      <div class="quotation-table-card__footer erp-list-footer"><span>共 {{ total }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" background layout="sizes, prev, pager, next" :page-sizes="[20, 50, 100]" :total="total" @current-change="() => { void loadRows() }" @size-change="() => { page = 1; void loadRows() }" /></div>
    </section>
    <AppWindowDialog v-model="createVisible" class="quotation-create-dialog" title="新建报价" :width="840" :height="680" :close-on-click-modal="false">
      <p class="quotation-create-form__lead">创建草稿后，继续填写产品明细和价格。</p>
      <ElForm label-position="top" class="quotation-create-form">
        <ElFormItem label="* 客户"><ElSelect v-model="createForm.customer_account_id" filterable :loading="createCustomerLoading" placeholder="搜索或选择客户" @change="loadCreateEntities"><ElOption v-for="customer in createCustomers" :key="customer.id" :label="customer.account_name" :value="customer.id" /></ElSelect></ElFormItem>
        <ElFormItem label="* 交易主体"><ElSelect v-model="createForm.transaction_entity_id" :loading="createEntityLoading" :disabled="!createForm.customer_account_id" placeholder="请先选择客户"><ElOption v-for="entity in createCustomers.find((customer) => customer.id === createForm.customer_account_id)?.entities || []" :key="entity.id" :label="entity.legal_name" :value="entity.id" /></ElSelect><small>选择该客户下用于报价的公司抬头。</small></ElFormItem>
        <ElFormItem label="* 报价主题"><ElInput v-model="createForm.subject" maxlength="250" placeholder="例如：户外折叠椅报价" /></ElFormItem>
        <div class="quotation-create-form__row"><ElFormItem label="* 币种"><ElSelect v-model="createForm.currency_code" filterable placeholder="请选择币种"><ElOption v-for="item in createCurrencies" :key="item.code" :label="`${item.code} · ${item.chinese_name || item.english_name}`" :value="item.code" /></ElSelect></ElFormItem><ElFormItem label="报价有效期　可选"><ElDatePicker v-model="createForm.valid_until" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" /><small>可不填；填写时不能早于今天。</small></ElFormItem></div>
      </ElForm>
      <template #footer><ElButton @click="createVisible = false">取消</ElButton><ElButton class="quotation-create-form__submit" :loading="createLoading" @click="submitCreate">创建草稿</ElButton></template>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
.quotation-search { width: min(250px, 100%); min-width: 0; flex: none; }
.quotation-status-filter { width: 148px; flex: none; }
.quotation-owner-filter { width: 128px; flex: none; }
.quotation-currency-filter { width: 120px; flex: none; }
.quotation-list-actions :deep(.quotation-create-button) { width: 112px; }
.quotation-list-actions :deep(.quotation-export-button) { width: 76px; }
.quotation-button-icon { width: 16px; height: 16px; }
.quotation-list-actions :deep(.el-button > span) { gap: 8px; }
.quotation-search-button {
  display: inline-flex; width: 20px; height: 24px; align-items: center; justify-content: center;
  margin: 0; padding: 0; border: 0; color: inherit; background: transparent; cursor: pointer;
}
.quotation-search-button img { width: 16px; height: 16px; }
.quotation-search-button:focus-visible, .quotation-link:focus-visible, .row-more:focus-visible {
  outline: 2px solid var(--erp-color-focus); outline-offset: 2px;
}
.quotation-more-content { display: flex; align-items: center; gap: 10px; }
.quotation-more-content :deep(.el-date-editor) { width: 230px; }
.quotation-error { flex: none; }
.quotation-link {
  max-width: 100%; overflow: hidden; padding: 0; border: 0; color: var(--erp-table-text);
  background: transparent; text-overflow: ellipsis; white-space: nowrap; cursor: pointer;
}
.quotation-link:hover { text-decoration: underline; text-underline-offset: 3px; }
.quotation-status {
  display: inline-flex; min-width: 72px; height: 24px; align-items: center; justify-content: center;
  padding: 0 8px; border: 1px solid var(--erp-tag-neutral-border); border-radius: var(--erp-radius-pill);
  color: var(--erp-tag-neutral-text); background: var(--erp-tag-neutral-background);
  font-size: 12px; line-height: 18px; white-space: nowrap;
}
.status--ready-to-send {
  color: var(--erp-tag-warning-text); background: var(--erp-tag-warning-background); border-color: var(--erp-tag-warning-border);
}
.status--sent {
  color: var(--erp-tag-info-text); background: var(--erp-tag-info-background); border-color: var(--erp-tag-info-border);
}
.status--accepted {
  color: var(--erp-tag-success-text); background: var(--erp-tag-success-background); border-color: var(--erp-tag-success-border);
}
.status--expired, .status--rejected, .status--withdrawn {
  color: var(--erp-tag-danger-text); background: var(--erp-tag-danger-background); border-color: var(--erp-tag-danger-border);
}
.row-more {
  width: 32px; height: 32px; display: inline-grid; place-items: center; padding: 0; border: 0;
  border-radius: var(--erp-radius-control); color: var(--erp-table-text); background: transparent; cursor: pointer;
}
.row-more:hover { background: var(--erp-table-selected); }
.row-more .el-icon { font-size: 17px; }

.quotation-create-form { margin-top: 24px; }
.quotation-create-form :deep(.el-select), .quotation-create-form :deep(.el-date-editor) { width: 100%; }
.quotation-create-form__row { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }
.quotation-create-form__submit { color: var(--erp-color-text-inverse) !important; border-color: var(--erp-button-primary-border) !important; background: var(--erp-button-primary-surface) !important; }
.quotation-create-form__lead { margin: -8px 0 0; color: var(--erp-color-text-regular); font-size: 14px; }
.quotation-create-form :deep(.el-form-item) { margin-bottom: 22px; }
.quotation-create-form :deep(.el-form-item__label) { padding-bottom: 8px; color: var(--erp-color-text-primary); font-size: 14px; font-weight: 600; }
.quotation-create-form :deep(.el-input__wrapper), .quotation-create-form :deep(.el-select__wrapper) {
  height: 32px; min-height: 32px; border-radius: var(--erp-radius-control); background: var(--erp-input-surface); box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-border) inset;
}
.quotation-create-form :deep(.el-input__wrapper.is-focus), .quotation-create-form :deep(.el-select__wrapper.is-focused) { box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-focus-border) inset; }
.quotation-create-form small { display: block; margin-top: 7px; color: var(--erp-color-text-regular); font-size: 12px; }
:global(.quotation-create-dialog) { border-radius: 6px; background: var(--erp-color-surface); }
:global(.quotation-create-dialog .el-dialog__header) { margin: 0; padding: 32px 44px 0; }
:global(.quotation-create-dialog .el-dialog__title) { font-family: 'Noto Serif SC', 'STSong', serif; font-size: 30px; font-weight: 600; }
:global(.quotation-create-dialog .el-dialog__body) { padding: 14px 44px 10px; }
:global(.quotation-create-dialog .el-dialog__footer) { margin: 0 44px; padding: 20px 0 24px; border-top: 1px solid var(--erp-color-border); }
:global(.quotation-create-dialog .el-dialog__footer .el-button) { width: 108px; height: 44px; border-radius: 4px; }
:global(.quotation-create-dialog .quotation-create-form__submit) { width: 140px !important; color: var(--erp-color-text-inverse) !important; border-color: var(--erp-button-primary-border) !important; background: var(--erp-button-primary-surface) !important; }
</style>
