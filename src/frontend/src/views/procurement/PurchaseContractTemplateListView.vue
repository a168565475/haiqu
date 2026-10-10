<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ArrowLeft, InfoFilled, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { ElIcon, ElPagination } from 'element-plus'
import { useRouter } from 'vue-router'
import '@fontsource-variable/noto-sans-sc'
import '@fontsource-variable/noto-serif-sc'

import {
  fetchPurchaseContractTemplates,
} from '@/api/purchaseOrders'
import type { PurchaseContractTemplate } from '@/types/purchaseOrder'
import { useAuthStore } from '@/stores/auth'
import PurchaseContractTemplateCreateDrawer from '@/components/procurement/PurchaseContractTemplateCreateDrawer.vue'
import PurchaseContractTemplateHistoryDrawer from '@/components/procurement/PurchaseContractTemplateHistoryDrawer.vue'

const router = useRouter()
const auth = useAuthStore()
const canCreate = computed(() => auth.moduleCan('procurement.add_purchasecontracttemplate', 'procurement.view_purchaseorder'))
const canEdit = computed(() => auth.moduleCan('procurement.change_purchasecontracttemplate', 'procurement.view_purchaseorder'))
const canManage = computed(() => Boolean(auth.user?.is_superuser || auth.moduleCan('procurement.view_purchasecontracttemplate', 'procurement.view_purchaseorder')))
const loading = ref(false)
const keyword = ref('')
const statusFilter = ref('')
const appliedFilters = reactive({ q: '', status: '' })
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const loadError = ref('')
const statsLoading = ref(false)
const statsError = ref('')
const stats = ref<Array<number | null>>([null, null, null])
const displayedTotal = computed(() => loading.value || loadError.value ? '—' : total.value)
let disposed = false
let listRequest = 0
let statsRequest = 0
const rows = ref<PurchaseContractTemplate[]>([])
const createVisible = ref(false)
const historyVisible = ref(false)
const historyTemplate = ref<PurchaseContractTemplate | null>(null)
const editingId = ref('')
const categories = [
  { value: 'TUBE', label: '管材' }, { value: 'HARDWARE', label: '五金' },
  { value: 'PLASTIC_PART', label: '塑料件' }, { value: 'PACKAGING', label: '包材' },
  { value: 'FABRIC', label: '面料' }, { value: 'AUXILIARY', label: '辅料' },
  { value: 'FINISHED_GOODS', label: '成品' },
]

function apiErrorMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { status?: number; data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response
  if (response?.status === 412) return '模板已被其他人修改，请关闭后重新打开。'
  const fieldError = response?.data?.error?.field_errors ? Object.values(response.data.error.field_errors).flat()[0] : ''
  return fieldError || response?.data?.error?.message || response?.data?.detail || fallback
}

async function load(targetPage = page.value): Promise<void> {
  if (!canManage.value || disposed) return
  const request = ++listRequest
  page.value = Math.max(1, Math.floor(targetPage) || 1)
  loading.value = true
  loadError.value = ''
  rows.value = []
  try {
    const result = await fetchPurchaseContractTemplates({ q: appliedFilters.q || undefined, status: appliedFilters.status || undefined, page: page.value, page_size: pageSize.value })
    if (disposed || request !== listRequest) return
    if (!Array.isArray(result.data) || !Number.isInteger(result.meta?.total) || result.meta.total < 0) throw new Error('列表数据格式异常')
    total.value = result.meta.total
    const lastPage = Math.max(1, Math.ceil(total.value / pageSize.value))
    if (page.value > lastPage) { await load(lastPage); return }
    rows.value = result.data
  } catch (error) {
    if (disposed || request !== listRequest) return
    if ((error as { response?: { status?: number } })?.response?.status === 404 && page.value > 1) { await load(1); return }
    loadError.value = apiErrorMessage(error, '采购模板加载失败，请刷新重试。')
  } finally {
    if (!disposed && request === listRequest) loading.value = false
  }
}

async function loadStats(): Promise<void> {
  if (!canManage.value || disposed) return
  const request = ++statsRequest
  statsLoading.value = true
  statsError.value = ''
  stats.value = [null, null, null]
  const results = await Promise.allSettled(['', 'ACTIVE', 'INACTIVE'].map(status => fetchPurchaseContractTemplates({ status: status || undefined, page_size: 1 })))
  if (disposed || request !== statsRequest) return
  stats.value = results.map(result => result.status === 'fulfilled' && Number.isInteger(result.value.meta?.total) && result.value.meta.total >= 0 ? result.value.meta.total : null)
  if (stats.value.includes(null)) statsError.value = '部分统计加载失败，请刷新重试。'
  statsLoading.value = false
}

async function reloadAll(): Promise<void> { await Promise.all([load(), loadStats()]) }
function search(): void {
  appliedFilters.q = keyword.value.trim()
  appliedFilters.status = statusFilter.value
  void load(1)
}
function resetFilters(): void { keyword.value = ''; statusFilter.value = ''; search() }
function categoryLabel(row: PurchaseContractTemplate): string {
  return row.supplier_categories?.length ? row.supplier_categories.map(value => categories.find(option => option.value === value)?.label || value).join('、') : '通用模板'
}
function formatDateTime(value: string): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (number: number) => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
function back(): void {
  const previous = router.options.history.state.back
  if (typeof previous === 'string' && previous.startsWith('/') && previous !== router.currentRoute.value.fullPath) router.back()
  else void router.push({ name: 'purchase-orders' })
}

function openCreate(): void {
  if (!canManage.value || createVisible.value || historyVisible.value) return
  editingId.value = ''
  createVisible.value = true
}
function openHistory(row: PurchaseContractTemplate): void {
  if (!canManage.value || createVisible.value || historyVisible.value || !row.id) return
  historyTemplate.value = row
  historyVisible.value = true
}
function openEdit(row: PurchaseContractTemplate): void {
  if (!canManage.value || createVisible.value || historyVisible.value || !row.id) return
  editingId.value = row.id
  createVisible.value = true
}

onMounted(() => { if (canManage.value) void reloadAll() })
onBeforeUnmount(() => { disposed = true; listRequest++; statsRequest++ })
</script>

<template>
  <section class="template-page" data-testid="template-management-page">
    <div v-if="!canManage" class="permission-state"><h1>无权查看采购合同模板</h1><p>请联系管理员开通采购查看权限后重试。</p><ElButton @click="back">返回</ElButton></div>
    <template v-else>
    <header class="page-heading">
      <h1>采购合同模板</h1><span class="total-count">共 {{ displayedTotal }} 套</span><span class="heading-space" />
      <ElButton class="back-button" :icon="ArrowLeft" @click="back">返回</ElButton><ElButton v-if="canCreate" class="create-button" type="primary" :icon="Plus" :disabled="createVisible || historyVisible" @click="openCreate">新建模板</ElButton>
    </header>
    <div class="summary-strip" aria-label="模板统计" :aria-busy="statsLoading"><div v-for="(label, index) in ['模板总数', '已启用', '已停用']" :key="label" class="summary-item"><span>{{ label }}</span><strong :class="{ neutral: index === 1 }">{{ stats[index] ?? '—' }}</strong></div></div>
    <form class="filters-row" aria-label="模板查询" @submit.prevent="search">
      <ElInput v-model="keyword" clearable :prefix-icon="Search" aria-label="搜索模板名称" placeholder="搜索模板名称" />
      <ElSelect v-model="statusFilter" clearable aria-label="模板状态" placeholder="状态：全部"><ElOption label="启用" value="ACTIVE" /><ElOption label="停用" value="INACTIVE" /></ElSelect>
      <ElButton type="primary" native-type="submit">查询</ElButton><ElButton @click="resetFilters">重置</ElButton>
    </form>
    <div class="table-heading"><h2>模板列表</h2><ElButton :icon="Refresh" :loading="loading || statsLoading" @click="reloadAll">刷新</ElButton></div>
    <div v-if="loadError || statsError" class="load-error" role="alert">{{ loadError || statsError }}</div>
    <div class="table-card">
      <div v-loading="loading" class="template-table-scroll" :aria-busy="loading" tabindex="0" aria-label="采购合同模板表格">
        <table class="template-table">
          <colgroup><col v-for="(width, index) in ['17.39%', '10.87%', '15.22%', '9.78%', '10.87%', '9.78%', '17.39%', '144px']" :key="index" :style="{ width }" /></colgroup>
          <thead><tr><th v-for="label in ['模板名称', '适用类别', '当前版本', '状态', '版本记录', '修改人', '更新时间', '操作']" :key="label" scope="col">{{ label }}</th></tr></thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id" class="template-row">
              <td :title="row.template_name || '—'"><strong>{{ row.template_name || '—' }}</strong></td><td :title="categoryLabel(row)">{{ categoryLabel(row) }}</td><td :title="row.current_version?.version_name || '未命名版本'">{{ row.current_version?.version_name || '未命名版本' }}</td>
              <td class="status-cell"><span class="status-badge" :class="{ inactive: row.status !== 'ACTIVE' }">{{ row.status_display || (row.status === 'ACTIVE' ? '启用' : '停用') }}</span></td>
              <td>{{ row.versions?.length ?? 0 }} 个</td><td>{{ row.updated_by_name || '—' }}</td><td>{{ formatDateTime(row.updated_at) }}</td>
              <td class="action-cell"><div><ElButton link :disabled="createVisible || historyVisible" @click="openHistory(row)">版本记录</ElButton><ElButton v-if="canEdit" link :disabled="createVisible || historyVisible" @click="openEdit(row)">编辑模板</ElButton></div></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="8" class="table-empty">{{ loadError ? '记录加载失败，请刷新重试' : loading ? '正在加载采购模板…' : '暂无符合条件的采购模板' }}</td></tr>
          </tbody>
        </table>
      </div>
      <footer class="table-footer"><span>共 {{ displayedTotal }} 套模板</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" :disabled="loading" layout="sizes, prev, pager, next" @current-change="load" @size-change="search" /></footer>
    </div>
    <div class="template-note"><ElIcon :size="24"><InfoFilled /></ElIcon><span>保存当前模板不增加版本号；保存新版本会新增版本。已生成采购表保留原模板内容。</span></div>

    <PurchaseContractTemplateHistoryDrawer v-if="canManage" v-model:visible="historyVisible" :template-id="historyTemplate?.id || ''" />

    <PurchaseContractTemplateCreateDrawer v-if="canManage" v-model:visible="createVisible" :template-id="editingId" @created="reloadAll" />

    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
$font-body: 'Noto Sans SC Variable', token.$crm-font-body;
$font-display: 'Noto Serif SC Variable', token.$crm-font-display;
.template-page { box-sizing: border-box; min-width: 0; min-height: 0; height: calc(100dvh - 92px); display: flex; flex-direction: column; overflow: hidden; color: token.$crm-text-primary; background: token.$crm-color-page; font: 14px/20px $font-body; --el-color-primary: #{token.$crm-primary}; --el-border-color: #{token.$crm-border-default}; --el-fill-color-blank: #{token.$crm-color-surface}; --el-text-color-regular: #{token.$crm-text-primary}; --el-text-color-placeholder: #{token.$crm-text-muted}; }
.template-page h1,.template-page h2 { margin: 0; }
.template-page > :is(.page-heading, .summary-strip, .filters-row, .table-heading, .table-card, .template-note, .load-error) { min-width: 0; }

.page-heading { flex: 0 0 46px; display: flex; align-items: center; gap: 24px; }
.page-heading h1 { font: 700 34px/44px $font-display; letter-spacing: -1px; }
.total-count { color: token.$crm-text-secondary; white-space: nowrap; } .heading-space { flex: 1; }
.template-page :deep(.el-button) { margin: 0; height: 32px; border-radius: 5px; font: 500 13px $font-body; }
.page-heading .el-button { height: 32px; } .back-button { width: 90px; } .create-button { width: 140px; }
.summary-strip { flex: 0 0 46px; margin-top: 4px; display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); border-radius: 5px; background: token.$crm-color-subtle; }
.summary-item { display: flex; gap: 8px; align-items: center; justify-content: center; position: relative; color: token.$crm-text-secondary; font-size: 13px; }
.summary-item + .summary-item::before { position: absolute; left: 0; top: 9px; width: 1px; height: 28px; background: token.$crm-border-default; content: ''; }
.summary-item strong { color: token.$crm-primary; font-size: 12px; font-weight: 500; } .summary-item .neutral { color: token.$crm-text-primary; }
.filters-row { flex: 0 0 32px; margin-top: 17px; display: grid; grid-template-columns: minmax(260px, 1fr) 160px 76px 76px; gap: 14px; height: 32px; }
.filters-row > * { min-width: 0; width: 100%; } .filters-row .el-button { height: 32px; }
.filters-row :deep(.el-input__wrapper),.filters-row :deep(.el-select__wrapper) { min-height: 32px; box-sizing: border-box; border-radius: 5px; padding: 0 12px; box-shadow: 0 0 0 1px token.$crm-border-default inset; font-size: 13px; }
.filters-row :deep(.el-input__wrapper.is-focus),.filters-row :deep(.el-select__wrapper.is-focused) { box-shadow: 0 0 0 1px token.$crm-focus inset; }
.filters-row :deep(.el-input__inner) { height: 30px; font-family: inherit; } .filters-row :deep(.el-input__prefix-inner) { margin-right: 8px; font-size: 16px; }
.table-heading { flex: 0 0 32px; display: flex; align-items: center; justify-content: space-between; margin-top: 10px; }
.table-heading h2 { color: token.$crm-text-secondary; font-size: 14px; font-weight: 400; line-height: 20px; } .table-heading .el-button { width: 96px; height: 32px; }
.load-error { margin: 0 0 8px; color: token.$crm-danger; }
.table-card { flex: 1; min-height: 0; display: flex; flex-direction: column; margin-top: 14px; background: token.$crm-color-surface; border: 1px solid token.$crm-border-default; border-radius: 5px; overflow: hidden; }
.template-table-scroll { flex: 1; min-height: 0; overflow: auto; }
.template-table { width: 100%; table-layout: fixed; border-collapse: separate; border-spacing: 0; }
.template-table th,.template-table td { box-sizing: border-box; padding: 0 16px; overflow: hidden; border-right: 1px solid token.$crm-border-subtle; text-align: left; text-overflow: ellipsis; white-space: nowrap; }
.template-table th { height: 44px; position: sticky; top: 0; z-index: 1; color: token.$crm-text-secondary; background: token.$crm-color-subtle; font-size: 11px; font-weight: 500; line-height: 16px; }
.template-row td { height: 40px; border-bottom: 1px solid token.$crm-border-subtle; color: token.$crm-text-regular; font-size: 12px; line-height: 18px; }
.template-table th:last-child,.template-table td:last-child { border-right: 0; }
.template-row strong { color: token.$crm-text-primary; font-size: 13px; font-weight: 600; } .template-row:hover { background: token.$crm-color-row-hover; }
.template-row .status-cell,.template-row .action-cell { padding: 0 5px; overflow: visible; text-align: center; text-overflow: clip; }
.status-badge { box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; min-width: 56px; height: 24px; padding: 0 8px; border-radius: 999px; color: token.$crm-text-inverse; background: token.$crm-success; font-size: 12px; font-weight: 500; line-height: 18px; }
.status-badge.inactive { background: var(--haiqu-warm-primitive-neutral-stone, #87867f); }
.action-cell > div { display: flex; align-items: center; justify-content: center; gap: 12px; white-space: nowrap; } .action-cell .el-button { color: token.$crm-primary; } .action-cell .el-button.is-disabled { color: token.$crm-text-disabled; }
.table-footer { flex: 0 0 48px; height: 48px; box-sizing: border-box; display: flex; align-items: center; justify-content: space-between; padding: 0 16px; border-top: 1px solid token.$crm-border-default; color: token.$crm-text-secondary; font-size: 13px; }
.table-footer :deep(.el-pagination) { gap: 10px; --el-pagination-button-bg-color: #{token.$crm-color-surface}; --el-pagination-button-disabled-bg-color: #{token.$crm-color-surface}; --el-pagination-button-height: 32px; --el-pagination-button-width: 38px; font-weight: 400; }
.table-footer :deep(.el-pager li),.table-footer :deep(.btn-prev),.table-footer :deep(.btn-next) { margin-left: 0; border: 1px solid token.$crm-border-default; border-radius: 5px; }
.table-footer :deep(.el-pager li.is-active) { color: token.$crm-primary; border-color: token.$crm-primary; background: token.$crm-color-surface; }
.table-footer :deep(.el-select) { width: 136px; } .table-footer :deep(.el-select__wrapper) { min-height: 32px; font-size: 13px; }
.table-empty { height: 384px; text-align: center !important; color: token.$crm-text-muted; }
.template-note { flex: 0 0 40px; min-height: 40px; margin-top: 10px; padding: 0 16px; display: flex; gap: 10px; align-items: center; border-radius: 5px; background: token.$crm-color-subtle; color: token.$crm-text-secondary; font-size: 12px; }
.template-note .el-icon { flex-shrink: 0; color: var(--haiqu-warm-primitive-neutral-stone, #87867f); }
.permission-state { text-align: center; padding: 100px 0; } .permission-state h1 { font: 700 32px/44px $font-display; } .permission-state p { margin: 20px 0; }
</style>
