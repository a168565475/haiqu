<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
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
  <section class="template-page erp-glass-list" data-testid="template-management-page">
    <div v-if="!canManage" class="permission-state"><h1>无权查看采购合同模板</h1><p>请联系管理员开通采购查看权限后重试。</p><ElButton @click="back">返回</ElButton></div>
    <template v-else>
    <section v-glass-spotlight class="erp-list-filter">
    <header class="page-heading erp-list-heading">
      <h1>采购合同模板</h1><span class="total-count">共 {{ displayedTotal }} 套</span>

    </header>
    <div class="summary-strip erp-list-summary" aria-label="模板统计" :aria-busy="statsLoading"><div v-for="(label, index) in ['模板总数', '已启用', '已停用']" :key="label" class="summary-item erp-list-summary-item"><span>{{ label }}</span><strong :class="{ neutral: index === 1 }">{{ stats[index] ?? '—' }}</strong></div></div>
    <form class="filters-row erp-list-filters" aria-label="模板查询" @submit.prevent="search">
      <ElInput v-model="keyword" clearable :prefix-icon="Search" aria-label="搜索模板名称" placeholder="搜索模板名称" />
      <ElSelect v-model="statusFilter" clearable aria-label="模板状态" placeholder="状态：全部"><ElOption label="启用" value="ACTIVE" /><ElOption label="停用" value="INACTIVE" /></ElSelect>
      <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="resetFilters">重置</ElButton><ElButton class="erp-button-motion" type="primary" native-type="submit">应用筛选</ElButton></div>
    </form>
    </section>

    <div v-if="loadError || statsError" class="load-error" role="alert">{{ loadError || statsError }}</div>
    <div class="table-card erp-list-data">
      <div class="table-heading erp-list-toolbar"><ElButton class="back-button erp-button-motion" :icon="ArrowLeft" @click="back">返回</ElButton><ElButton v-if="canCreate" class="create-button erp-button-motion" type="primary" :icon="Plus" :disabled="createVisible || historyVisible" @click="openCreate">新建模板</ElButton><h2>模板列表</h2><ElButton class="erp-button-motion" :icon="Refresh" :loading="loading || statsLoading" @click="reloadAll">刷新</ElButton></div>
      <div class="erp-list-table-frame">
      <div v-loading="loading" class="template-table-scroll erp-list-table-scroll" :aria-busy="loading" tabindex="0" aria-label="采购合同模板表格">
        <table class="template-table erp-list-native-table">
          <colgroup><col v-for="(width, index) in ['17.39%', '10.87%', '15.22%', '9.78%', '10.87%', '9.78%', '17.39%', '144px']" :key="index" :style="{ width }" /></colgroup>
          <thead><tr><th v-for="(label, index) in ['模板名称', '适用类别', '当前版本', '状态', '版本记录', '修改人', '更新时间', '操作']" :key="label" :class="{ 'erp-list-sticky-action': index === 7 }" scope="col">{{ label }}</th></tr></thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id" class="template-row">
              <td :title="row.template_name || '—'"><strong>{{ row.template_name || '—' }}</strong></td><td :title="categoryLabel(row)">{{ categoryLabel(row) }}</td><td :title="row.current_version?.version_name || '未命名版本'">{{ row.current_version?.version_name || '未命名版本' }}</td>
              <td class="status-cell"><span class="status-badge erp-list-tag" :class="row.status === 'ACTIVE' ? 'erp-list-tag--success' : 'inactive erp-list-tag--neutral'">{{ row.status_display || (row.status === 'ACTIVE' ? '启用' : '停用') }}</span></td>
              <td>{{ row.versions?.length ?? 0 }} 个</td><td>{{ row.updated_by_name || '—' }}</td><td>{{ formatDateTime(row.updated_at) }}</td>
              <td class="action-cell erp-list-sticky-action"><div><ElButton link :disabled="createVisible || historyVisible" @click="openHistory(row)">版本记录</ElButton><ElButton v-if="canEdit" link :disabled="createVisible || historyVisible" @click="openEdit(row)">编辑模板</ElButton></div></td>
            </tr>
            <tr v-if="!rows.length"><td colspan="8" class="table-empty">{{ loadError ? '记录加载失败，请刷新重试' : loading ? '正在加载采购模板…' : '暂无符合条件的采购模板' }}</td></tr>
          </tbody>
        </table>
      </div>
      </div>
      <footer class="table-footer erp-list-footer"><span>共 {{ displayedTotal }} 套模板</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" :disabled="loading" layout="sizes, prev, pager, next" @current-change="load" @size-change="search" /></footer>
    </div>
    <div class="template-note"><ElIcon :size="24"><InfoFilled /></ElIcon><span>保存当前模板不增加版本号；保存新版本会新增版本。已生成采购表保留原模板内容。</span></div>

    <PurchaseContractTemplateHistoryDrawer v-if="canManage" v-model:visible="historyVisible" :template-id="historyTemplate?.id || ''" />

    <PurchaseContractTemplateCreateDrawer v-if="canManage" v-model:visible="createVisible" :template-id="editingId" @created="reloadAll" />

    </template>
  </section>
</template>

<style scoped lang="scss">
.page-heading { flex-wrap: wrap; }
.total-count { color: var(--erp-color-text-secondary); white-space: nowrap; font-size: 12px; }
.back-button { width: 90px; }
.create-button { width: 140px; }
.filters-row > .el-input { width: min(300px, 100%); flex: 1 1 250px; }
.filters-row > .el-select { width: 160px; flex: 1 1 120px; }
.table-heading h2 { margin: 0 auto 0 8px; color: var(--erp-color-text-secondary); font-size: 13px; font-weight: 400; }
.load-error { color: var(--erp-color-danger); }
.template-table th, .template-table td { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.template-row strong { font-size: 13px; font-weight: 600; }
.template-table .status-cell, .template-table .action-cell { padding: 0 5px; overflow: visible; text-align: center; text-overflow: clip; }
.action-cell > div { display: flex; align-items: center; justify-content: center; gap: 12px; white-space: nowrap; }
.action-cell .el-button { font-size: 12px; }
.table-empty { height: 300px; text-align: center; color: var(--erp-color-text-secondary); }
.template-note { display: flex; flex: none; align-items: center; gap: 10px; padding: 8px 16px; color: var(--erp-color-text-secondary); font-size: 12px; }
.template-note .el-icon { flex: none; }
.state-page, .permission-state { padding: 100px 0; text-align: center; }
.state-page p, .permission-state p { margin: 20px 0; }
</style>
