<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ArrowLeft, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import SupplierCreateDrawer from '@/components/procurement/SupplierCreateDrawer.vue'

import { fetchSupplierOptions, fetchSuppliers, fetchSupplierStats } from '@/api/suppliers'
import { useAuthStore } from '@/stores/auth'
import type {
  Supplier,
  SupplierCategory,
  SupplierOptions,
  SupplierPaymentCycle,
  SupplierStats,
  SupplierType,
} from '@/types/supplier'

const router = useRouter()
const route = useRoute()
const createVisible = ref(false)
const editSupplierId = ref('')
const authStore = useAuthStore()
const isSuperuser = computed(() => authStore.user?.is_superuser === true)
const can = (permission: string) => isSuperuser.value || authStore.hasPermission(permission)
const canView = computed(() => can('procurement.view_supplier'))
const canAdd = computed(() => can('procurement.add_supplier'))
const canChange = computed(() => can('procurement.change_supplier'))

const suppliers = ref<Supplier[]>([])
const options = ref<SupplierOptions>({
  supplier_types: [],
  supplier_categories: [],
  payment_cycles: [],
  next_supplier_number: '',
})
const stats = ref<SupplierStats | null>(null)
const loading = ref(false)
const listError = ref('')
const optionsError = ref('')
const statsError = ref('')
const optionsLoading = ref(false)
const statsLoading = ref(false)
const loadError = computed(() => [listError.value, optionsError.value, statsError.value].filter(Boolean).join(' '))
const listLoaded = ref(false)
const displayedTotal = computed(() => listLoaded.value ? total.value : '—')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
let requestId = 0
let optionsVersion = 0
let statsVersion = 0
let disposed = false
const columns = [153,311,152,140,126,162,126,130,219,115]
const labels = ['供应商编号','供应商名称','供应商类型','供应商类别','付款周期','联系电话','状态','提交人','更新时间','操作']

const filters = reactive({
  keyword: '',
  supplierType: '' as SupplierType | '',
  category: '' as SupplierCategory | '',
  paymentCycle: '' as SupplierPaymentCycle | '',
  disabled: '' as boolean | '',
})

const summaryCards = computed(() => [
  { label: '供应商总数', value: stats.value?.total ?? '—', tone: 'primary' },
  { label: '材料供应商', value: stats.value?.material ?? '—', tone: 'success' },
  { label: '成品供应商', value: stats.value?.finished ?? '—', tone: 'warning' },
  { label: '已禁用', value: stats.value?.disabled ?? '—', tone: 'danger' },
])

function apiErrorMessage(error: unknown, fallback: string): string {
  const data = (error as {
    response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } }
  })?.response?.data
  const firstFieldError = data?.error?.field_errors
    ? Object.values(data.error.field_errors).flat()[0]
    : ''
  return firstFieldError || data?.error?.message || data?.detail || fallback
}

function formatDateTime(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date).replaceAll('/', '-')
}

async function loadList(): Promise<void> {
  if (!canView.value || disposed) return
  const currentRequestId = ++requestId
  loading.value = true
  listError.value = ''
  try {
    const response = await fetchSuppliers({
      page: page.value,
      page_size: pageSize.value,
      q: filters.keyword.trim() || undefined,
      supplier_type: filters.supplierType,
      category: filters.category,
      payment_cycle: filters.paymentCycle,
      is_disabled: typeof filters.disabled === 'boolean' ? filters.disabled : '',
      ordering: '-supplier_number',
    })
    if (disposed || currentRequestId !== requestId) return
    if (!Array.isArray(response.data) || !Number.isInteger(response.meta?.total) || response.meta.total < 0) throw new Error('供应商列表响应不完整')
    const lastPage = Math.max(1, Math.ceil(response.meta.total / pageSize.value))
    if (page.value > lastPage) { page.value = lastPage; await loadList(); return }
    listLoaded.value = true
    suppliers.value = response.data
    total.value = response.meta.total
  } catch (error) {
    if (disposed || currentRequestId !== requestId) return
    suppliers.value = []
    // 保留分页范围，避免分页组件在失败时自动跳回第一页并吞掉错误。
    listLoaded.value = false
    listError.value = apiErrorMessage(error, '供应商列表加载失败，请稍后重试。')
  } finally {
    if (!disposed && currentRequestId === requestId) loading.value = false
  }
}

async function loadOptions(): Promise<void> {
  const version = ++optionsVersion
  optionsLoading.value = true
  optionsError.value = ''
  try {
    const response = await fetchSupplierOptions()
    if (disposed || version !== optionsVersion) return
    if (![response.supplier_types, response.supplier_categories, response.payment_cycles].every(Array.isArray)) throw new Error('筛选选项响应不完整')
    options.value = response
  } catch (error) {
    if (!disposed && version === optionsVersion) optionsError.value = apiErrorMessage(error, '筛选选项加载失败，请刷新重试。')
  } finally { if (!disposed && version === optionsVersion) optionsLoading.value = false }
}
async function loadStats(): Promise<void> {
  const version = ++statsVersion
  statsLoading.value = true
  statsError.value = ''
  stats.value = null
  try {
    const response = await fetchSupplierStats()
    if (disposed || version !== statsVersion) return
    if (![response.total, response.material, response.finished, response.disabled].every(v => Number.isInteger(v) && v >= 0)) throw new Error('供应商统计响应不完整')
    stats.value = response
  } catch (error) {
    if (!disposed && version === statsVersion) statsError.value = apiErrorMessage(error, '供应商统计加载失败，请刷新重试。')
  } finally { if (!disposed && version === statsVersion) statsLoading.value = false }
}
async function reloadAll(): Promise<void> {
  if (!canView.value || disposed) return
  await Promise.all([loadList(), loadOptions(), loadStats()])
}

function search(): void {
  page.value = 1
  void loadList()
}

function resetFilters(): void {
  filters.keyword = ''
  filters.supplierType = ''
  filters.category = ''
  filters.paymentCycle = ''
  filters.disabled = ''
  search()
}

function openCreate(): void {
  if (canView.value && canAdd.value && !createVisible.value) {
    editSupplierId.value = ''
    createVisible.value = true
  }
}

// 兼容原新建链接，统一进入列表内抽屉。
watch(() => [route.query.create, route.query.edit], ([create, edit]) => {
  if (typeof edit === 'string' && edit.trim() && canView.value && canChange.value) {
    editSupplierId.value = edit
    createVisible.value = true
  } else if (create === '1') openCreate()
}, { immediate: true })

function openEdit(row: Supplier): void {
  if (canView.value && canChange.value && row.id && !createVisible.value) {
    editSupplierId.value = row.id
    createVisible.value = true
  }
}

onMounted(() => {
  if (canView.value) void reloadAll()
})
function backToOrders(): void { void router.push({ name: 'purchase-orders' }) }
onBeforeUnmount(() => { disposed = true; requestId++; optionsVersion++; statsVersion++ })
</script>

<template>
  <section class="supplier-page" data-testid="supplier-list-page">
    <div v-if="!canView" class="state-page"><h1>无权查看供应商</h1><p>请联系管理员开通“供应商查看”权限后重试。</p><ElButton :icon="ArrowLeft" @click="backToOrders">返回</ElButton></div>
    <template v-else>
      <header class="page-heading">
        <h1>供应商管理</h1><span class="total-count">共 {{ displayedTotal }} 条</span><span class="heading-space" />
        <ElButton class="back-button" :icon="ArrowLeft" @click="backToOrders">返回</ElButton>
        <ElButton v-if="canAdd" type="primary" :icon="Plus" class="create-button" @click="openCreate">新建供应商</ElButton>
      </header>
      <div class="summary-strip" aria-label="供应商统计" :aria-busy="statsLoading">
        <div v-for="(item, index) in summaryCards" :key="item.label" class="summary-item"><span>{{ item.label }}</span><strong :class="{ neutral: index === 1 }">{{ item.value }}</strong></div>
      </div>
      <form class="filters-row" aria-label="供应商查询" @submit.prevent="search">
        <ElInput v-model="filters.keyword" clearable :prefix-icon="Search" aria-label="搜索供应商" placeholder="搜索供应商编号、名称或联系电话" @keydown.enter.prevent="search" />
        <ElSelect v-model="filters.supplierType" clearable :loading="optionsLoading" aria-label="供应商类型" placeholder="类型：全部"><ElOption v-for="item in options.supplier_types" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
        <ElSelect v-model="filters.category" clearable :loading="optionsLoading" aria-label="供应商类别" placeholder="类别：全部"><ElOption v-for="item in options.supplier_categories" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
        <ElSelect v-model="filters.paymentCycle" clearable :loading="optionsLoading" aria-label="付款周期" placeholder="付款周期：全部"><ElOption v-for="item in options.payment_cycles" :key="item.value" :label="item.label" :value="item.value" /></ElSelect>
        <ElSelect v-model="filters.disabled" clearable aria-label="供应商状态" placeholder="状态：全部"><ElOption label="正常" :value="false" /><ElOption label="禁用" :value="true" /></ElSelect>
        <ElButton type="primary" native-type="submit">查询</ElButton><ElButton @click="resetFilters">重置</ElButton>
      </form>
      <div class="table-heading"><h2>供应商列表</h2><ElButton :icon="Refresh" :loading="loading || optionsLoading || statsLoading" @click="reloadAll">刷新</ElButton></div>
      <div v-if="loadError" class="load-error" role="alert">{{ loadError }}</div>
      <div class="table-card">
        <div v-loading="loading" class="supplier-table-scroll" :aria-busy="loading" tabindex="0" aria-label="供应商列表表格">
          <table class="supplier-table">
            <colgroup><col v-for="(width, index) in columns" :key="index" :style="{ width: width / 1634 * 100 + '%' }" /></colgroup>
            <thead><tr><th v-for="label in labels" :key="label" scope="col">{{ label }}</th></tr></thead>
            <tbody>
              <tr v-for="row in suppliers" :key="row.id" class="supplier-row">
                <td><button v-if="canChange" class="number-link" type="button" @click="openEdit(row)">{{ row.supplier_number }}</button><span v-else>{{ row.supplier_number }}</span></td>
                <td :title="row.supplier_name || '—'"><strong>{{ row.supplier_name || '—' }}</strong></td><td>{{ row.supplier_type_display || '—' }}</td><td :title="row.supplier_category_labels?.join('、') || '—'">{{ row.supplier_category_labels?.join('、') || '—' }}</td>
                <td>{{ row.payment_cycle_display || '—' }}</td><td>{{ row.phone || '—' }}</td>
                <td class="status-cell"><span class="status-badge" :class="{ disabled: row.is_disabled }">{{ row.is_disabled ? '禁用' : '正常' }}</span></td>
                <td>{{ row.submitted_by_name || '—' }}</td><td>{{ formatDateTime(row.updated_at) }}</td>
                <td class="action-cell"><ElButton v-if="canChange" link @click="openEdit(row)">编辑</ElButton><span v-else>—</span></td>
              </tr>
              <tr v-if="!suppliers.length"><td colspan="10" class="table-empty">{{ listError ? '记录加载失败，请刷新重试' : loading ? '正在加载供应商…' : '暂无符合条件的供应商' }}</td></tr>
            </tbody>
          </table>
        </div>
        <footer class="table-footer"><span>共 {{ displayedTotal }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" :disabled="loading" layout="sizes, prev, pager, next" @current-change="loadList" @size-change="search" /></footer>
      </div>
      <SupplierCreateDrawer v-if="canAdd || canChange" v-model:visible="createVisible" :supplier-id="editSupplierId" @created="reloadAll" />
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.supplier-page { box-sizing: border-box; min-width: 0; min-height: 0; height: calc(100dvh - 92px); display: flex; flex-direction: column; overflow: hidden; color: token.$crm-text-primary; background: token.$crm-color-page; font: 14px/20px token.$crm-font-body; --el-color-primary: #{token.$crm-primary}; --el-border-color: #{token.$crm-border-default}; --el-fill-color-blank: #{token.$crm-color-surface}; --el-text-color-regular: #{token.$crm-text-primary}; --el-text-color-placeholder: #{token.$crm-text-muted}; }
.supplier-page > :is(.page-heading, .summary-strip, .filters-row, .table-heading, .table-card, .template-note, .load-error) { min-width: 0; }

.supplier-page h1,.supplier-page h2 { margin: 0; }
.page-heading { flex: 0 0 46px; display: flex; align-items: center; gap: 24px; }
.page-heading h1 { font: 700 34px/44px token.$crm-font-display; letter-spacing: -1px; }
.total-count { color: token.$crm-text-secondary; white-space: nowrap; }
.heading-space { flex: 1; }
.supplier-page :deep(.el-button) { margin: 0; height: 32px; font: 500 13px token.$crm-font-body; border-radius: 5px; }
.page-heading .el-button { height: 32px; }
.back-button { width: 90px; } .create-button { width: 140px; }
.summary-strip { flex: 0 0 46px; margin-top: 4px; display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); border-radius: 5px; background: token.$crm-color-subtle; }
.summary-item { display: flex; gap: 8px; align-items: center; justify-content: center; position: relative; color: token.$crm-text-secondary; font-size: 13px; }
.summary-item + .summary-item::before { position: absolute; left: 0; top: 9px; width: 1px; height: 28px; background: token.$crm-border-default; content: ''; }
.summary-item strong { color: token.$crm-primary; font-size: 12px; font-weight: 500; } .summary-item .neutral { color: token.$crm-text-primary; }
.filters-row { flex: 0 0 32px; margin-top: 17px; display: grid; grid-template-columns: minmax(260px, 1fr) repeat(4, minmax(120px, .45fr)) 76px 76px; gap: 14px; height: 32px; }
.filters-row > * { min-width: 0; width: 100%; } .filters-row .el-button { height: 32px; }
.filters-row :deep(.el-input__wrapper),.filters-row :deep(.el-select__wrapper) { min-height: 32px; box-sizing: border-box; border-radius: 5px; font-size: 13px; padding: 0 12px; box-shadow: 0 0 0 1px token.$crm-border-default inset; }
.filters-row :deep(.el-input__wrapper.is-focus),.filters-row :deep(.el-select__wrapper.is-focused) { box-shadow: 0 0 0 1px token.$crm-focus inset; }
.filters-row :deep(.el-input__inner) { height: 30px; font-family: inherit; }
.filters-row :deep(.el-input__prefix-inner) { margin-right: 8px; font-size: 16px; }
.table-heading { flex: 0 0 32px; display: flex; align-items: center; justify-content: space-between; margin-top: 10px; }
.table-heading h2 { color: token.$crm-text-secondary; font-size: 14px; font-weight: 400; line-height: 20px; } .table-heading .el-button { width: 96px; height: 32px; }
.load-error { margin: 0 0 8px; color: token.$crm-danger; }
.table-card { flex: 1; min-height: 0; display: flex; flex-direction: column; margin-top: 14px; background: token.$crm-color-surface; border: 1px solid token.$crm-border-default; border-radius: 5px; overflow: hidden; }
.supplier-table-scroll { flex: 1; min-height: 0; overflow: auto; }
.supplier-table { width: 100%; table-layout: fixed; border-collapse: separate; border-spacing: 0; }
.supplier-table th,.supplier-table td { box-sizing: border-box; text-align: left; padding: 0 16px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border-right: 1px solid token.$crm-border-subtle; }
.supplier-table th:nth-child(4),.supplier-table td:nth-child(4) { padding-right: 8px !important; padding-left: 8px !important; }
.supplier-table th { height: 44px; color: token.$crm-text-secondary; background: token.$crm-color-subtle; position: sticky; top: 0; z-index: 1; font-size: 11px; font-weight: 500; line-height: 16px; }
.supplier-row td { height: 40px; border-bottom: 1px solid token.$crm-border-subtle; color: token.$crm-text-regular; font-size: 12px; line-height: 18px; }
.supplier-table th:last-child,.supplier-table td:last-child { border-right: 0; }
.supplier-page .supplier-table > thead > tr > th:last-child { right: 0; z-index: 3; }
.supplier-page .supplier-table > tbody > tr.supplier-row > td.action-cell { position: sticky; right: 0; z-index: 2; background: token.$crm-color-surface; }
.supplier-page .supplier-table > tbody > tr.supplier-row:hover > td.action-cell { background: token.$crm-color-row-hover; }
.supplier-row strong { color: token.$crm-text-primary; font-size: 13px; font-weight: 600; } .supplier-row:hover { background: token.$crm-color-row-hover; }
.number-link { padding: 0; border: 0; color: inherit; background: transparent; font: inherit; cursor: pointer; } .number-link:hover { color: token.$crm-primary; text-decoration: underline; }
.supplier-row .status-cell,.supplier-row .action-cell { padding: 0 5px !important; overflow: visible !important; text-align: center; text-overflow: clip !important; }
.status-badge { box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; min-width: 56px; height: 24px; padding: 0 8px; border-radius: 999px; color: token.$crm-text-inverse; background: token.$crm-success; font-size: 12px; font-weight: 500; line-height: 18px; } .status-badge.disabled { background: token.$crm-neutral; }
.action-cell .el-button { color: token.$crm-primary; } .action-cell > span { color: token.$crm-text-muted; }
.table-footer { flex: 0 0 48px; height: 48px; box-sizing: border-box; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; border-top: 1px solid token.$crm-border-default; color: token.$crm-text-secondary; font-size: 13px; }
.table-footer :deep(.el-pagination) { gap: 10px; --el-pagination-button-bg-color: #{token.$crm-color-surface}; --el-pagination-button-disabled-bg-color: #{token.$crm-color-surface}; --el-pagination-button-height: 32px; --el-pagination-button-width: 38px; font-weight: 400; }
.table-footer :deep(.el-pager li),.table-footer :deep(.btn-prev),.table-footer :deep(.btn-next) { margin-left: 0; border: 1px solid token.$crm-border-default; border-radius: 5px; }
.table-footer :deep(.el-pager li.is-active) { color: token.$crm-primary; border-color: token.$crm-primary; background: token.$crm-color-surface; }
.table-footer :deep(.el-select) { width: 136px; } .table-footer :deep(.el-select__wrapper) { min-height: 32px; font-size: 13px; }
.table-empty { height: 300px; text-align: center !important; color: token.$crm-text-muted; }
.state-page { padding: 100px 0; text-align: center; } .state-page h1 { font: 700 32px/44px token.$crm-font-display; } .state-page p { margin: 20px 0; }
</style>
