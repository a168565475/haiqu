<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Plus } from '@element-plus/icons-vue'

import { archiveBom, fetchBomForEdit, fetchBomFilterOptions, fetchBoms } from '@/api/boms'
import searchIcon from '@/assets/crm-v2/search.svg'
import { useAuthStore } from '@/stores/auth'
import type { Bom, BomFilterOptions, BomQuery, BomStatus } from '@/types/bom'

const router = useRouter()
const authStore = useAuthStore()
const rows = ref<Bom[]>([])
const options = ref<BomFilterOptions | null>(null)
const loading = ref(false)
let latestRowsRequest = 0
let latestOptionsRequest = 0
const optionsError = ref('')
const optionsLoading = ref(false)
const errorMessage = ref('')
const page = ref(1)
const pageSize = ref(50)
const total = ref(0)
const deletingId = ref('')
const updatedRange = ref<[string, string] | null>(null)

const filters = reactive<{ q: string; status: BomStatus | ''; product_category_id: string }>({
  q: '',
  status: '',
  product_category_id: '',
})

const canCreate = computed(() => (
  authStore.hasPermission('boms.add_bom')
  && authStore.hasPermission('production_tasks.view_productiontask')
))
const canEdit = computed(() => authStore.hasPermission('boms.change_bom'))
const canDelete = computed(() => authStore.hasPermission('boms.delete_bom'))

function apiError(error: unknown) {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务。'
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  if (error.response.status === 403) return '当前账号没有查看 BOM 的权限。'
  return data.error?.message || data.detail || 'BOM 数据加载失败。'
}

function buildQuery(): BomQuery {
  return {
    page: page.value,
    page_size: pageSize.value,
    q: filters.q.trim() || undefined,
    status: filters.status || undefined,
    product_category_id: filters.product_category_id || undefined,
    updated_after: updatedRange.value?.[0] || undefined,
    updated_before: updatedRange.value?.[1] || undefined,
  }
}

async function loadRows(): Promise<boolean> {
  const requestId = ++latestRowsRequest
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchBoms(buildQuery())
    if (requestId !== latestRowsRequest) return true
    rows.value = result.data
    total.value = result.meta.total
    if (page.value > result.meta.total_pages && result.meta.total_pages > 0) {
      page.value = result.meta.total_pages
      return loadRows()
    }
    return true
  } catch (error) {
    if (requestId !== latestRowsRequest) return true
    rows.value = []
    total.value = 0
    errorMessage.value = apiError(error)
    return false
  } finally {
    if (requestId === latestRowsRequest) loading.value = false
  }
}

async function loadFilterOptions(): Promise<boolean> {
  const requestId = ++latestOptionsRequest
  optionsLoading.value = true
  optionsError.value = ''
  try {
    const result = await fetchBomFilterOptions()
    if (requestId === latestOptionsRequest) options.value = result
    return true
  } catch (error) {
    if (requestId !== latestOptionsRequest) return true
    optionsError.value = apiError(error)
    return false
  } finally {
    if (requestId === latestOptionsRequest) optionsLoading.value = false
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

function resetFilters() {
  filters.q = ''
  filters.status = ''
  filters.product_category_id = ''
  updatedRange.value = null
  search()
}

function openCreate() {
  if (!canCreate.value) return
  void router.push({ name: 'bom-create' })
}

function openProductInformation() {
  void router.push({ name: 'products' })
}

function number(value: string | number | null) {
  if (value === null || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(parsed) : String(value)
}

function dateTime(value: string) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value || '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(parsed)
}

function statusType(row: Bom) {
  return row.quantity_requires_confirmation ? 'warning' : row.status === 'VERIFIED' ? 'success' : 'warning'
}

function sectionText(row: Bom) {
  return row.section_summary.length
    ? row.section_summary.map((item) => `${({ PROFILE: '型材', ACCESSORY: '配件', FABRIC: '面辅料' } as Record<string, string>)[item.type] || item.label} ${item.count}`).join(' · ')
    : '尚未添加用料明细'
}

function statusText(row: Bom) {
  return row.is_order_product_outdated
    ? '订单产品已变更'
    : row.is_order_quantity_outdated
      ? '订单数量已变更'
      : row.quantity_requires_confirmation ? '数量待确认' : row.status_display
}

function openPreview(row: Bom) {
  void router.push({ name: 'bom-preview', params: { bomId: row.id } })
}

function openEdit(row: Bom) {
  if (!canEdit.value) return
  void router.push({ name: 'bom-edit', params: { bomId: row.id } })
}

async function deleteRow(row: Bom) {
  if (!canDelete.value || deletingId.value) return
  try {
    await ElMessageBox.confirm(
      `删除后“${row.bom_number}”将从 BOM 列表移除，历史审计记录仍会保留。`,
      '确认删除 BOM',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  deletingId.value = row.id
  try {
    const current = await fetchBomForEdit(row.id)
    await archiveBom(row.id, current.etag)
    ElMessage.success('BOM 已删除。')
    if (rows.value.length === 1 && page.value > 1) page.value -= 1
    await loadRows()
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    deletingId.value = ''
  }
}

function handleRowCommand(command: string, row: Bom) {
  if (command === 'preview') openPreview(row)
  if (command === 'edit') openEdit(row)
  if (command === 'delete') void deleteRow(row)
}

onMounted(() => { void loadRows(); void loadFilterOptions() })
onBeforeUnmount(() => { ++latestRowsRequest; ++latestOptionsRequest })
</script>

<template>
  <section class="bom-list-page" aria-label="BOM 列表">
    <header class="bom-page-heading">
      <div class="bom-page-heading__title"><h1>BOM 管理</h1><span>{{ total }} 个 BOM</span></div>
    </header>

    <ElAlert v-if="optionsError" type="warning" :title="`筛选选项加载失败：${optionsError}`" :closable="false"><ElButton size="small" @click="loadFilterOptions">重试选项</ElButton></ElAlert>

    <section class="filter-row" aria-label="BOM 快速筛选">
        <ElInput v-model="filters.q" class="search-filter" clearable placeholder="搜索 BOM / 任务 / 订单 / 产品" @keydown.enter="handleSearchEnter" @clear="search">
          <template #suffix><button type="button" class="bom-search-button" aria-label="搜索 BOM" @click="search"><img :src="searchIcon" alt="" aria-hidden="true" /></button></template>
        </ElInput>
        <ElSelect v-model="filters.status" placeholder="确认状态：全部" clearable @change="search">
          <ElOption label="待确认" value="PENDING_CONFIRMATION" />
          <ElOption label="已确认" value="VERIFIED" />
        </ElSelect>
        <ElSelect v-model="filters.product_category_id" :loading="optionsLoading" placeholder="产品类别：全部" clearable @change="search">
          <ElOption v-for="item in options?.product_categories || []" :key="item.id" :label="item.category_name" :value="item.id" />
        </ElSelect>
        <ElDatePicker
          v-model="updatedRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          aria-label="更新日期范围"
          clearable
          @change="search"
        />
        <ElPopover placement="bottom-end" :width="260" trigger="click">
          <template #reference><ElButton :icon="ArrowDown">更多筛选</ElButton></template>
          <div class="more-filter-panel"><span>当前页已展示全部可用筛选项。</span><ElButton text type="primary" @click="openProductInformation">产品信息</ElButton><ElButton text type="primary" @click="resetFilters">重置全部筛选</ElButton></div>
        </ElPopover>
      <div v-if="canCreate" class="bom-filter-actions">
        <ElButton type="primary" :icon="Plus" @click="openCreate()">新建 BOM</ElButton>
      </div>
    </section>

    <section class="list-card" aria-label="BOM 清单">
      <ElAlert v-if="errorMessage" type="error" :closable="false" show-icon>{{ errorMessage }}</ElAlert>
      <ElTable v-else v-loading="loading" :data="rows" border row-key="id" empty-text="暂无 BOM，可从生产任务单新建">
        <ElTableColumn prop="bom_number" label="BOM 编号" width="150" />
        <ElTableColumn label="生产任务单" width="120"><template #default="scope"><span class="cell-single">{{ scope.row.production_task_number || '—' }}</span></template></ElTableColumn>
        <ElTableColumn label="产品编码" width="160"><template #default="scope"><span class="cell-single">{{ scope.row.product_code_snapshot || scope.row.product_number_snapshot || '—' }}</span></template></ElTableColumn>
        <ElTableColumn label="产品名称" width="220"><template #default="scope"><span class="cell-single">{{ scope.row.product_name_snapshot || '—' }}</span></template></ElTableColumn>
        <ElTableColumn label="规格" width="180" show-overflow-tooltip><template #default="scope"><span class="cell-single">{{ scope.row.specification_snapshot || '—' }}</span></template></ElTableColumn>
        <ElTableColumn label="颜色" width="140"><template #default="scope"><span class="cell-single">{{ scope.row.product_color_snapshot || '—' }}</span></template></ElTableColumn>
        <ElTableColumn label="订单数量" width="120" align="right"><template #default="scope"><span class="quantity-cell"><strong>{{ number(scope.row.current_order_quantity) }}</strong><span v-if="scope.row.product_unit_name">{{ scope.row.product_unit_name }}</span></span></template></ElTableColumn>
        <ElTableColumn label="用料分区" min-width="250" show-overflow-tooltip><template #default="scope">{{ sectionText(scope.row) }}</template></ElTableColumn>
        <ElTableColumn label="确认状态" width="140" align="center"><template #default="scope"><ElTag :type="statusType(scope.row)" effect="light">{{ statusText(scope.row) }}</ElTag></template></ElTableColumn>
        <ElTableColumn label="更新人" width="120"><template #default="scope"><span class="cell-single">{{ scope.row.updated_by_name || '—' }}</span></template></ElTableColumn>
        <ElTableColumn label="更新时间" width="170"><template #default="scope"><span class="cell-single">{{ dateTime(scope.row.updated_at) }}</span></template></ElTableColumn>
        <ElTableColumn label="操作" width="72" align="center" fixed="right" class-name="operation-column">
          <template #default="scope">
            <ElDropdown :persistent="false" trigger="click" @command="(command: string) => handleRowCommand(command, scope.row)">
              <ElButton link :loading="deletingId === scope.row.id" :aria-label="`${scope.row.bom_number} 更多操作`">更多</ElButton>
              <template #dropdown>
                <ElDropdownMenu>
                  <ElDropdownItem command="preview">预览</ElDropdownItem>
                  <ElDropdownItem command="edit" :disabled="!canEdit">编辑</ElDropdownItem>
                  <ElDropdownItem command="delete" :disabled="!canDelete" divided>删除</ElDropdownItem>
                </ElDropdownMenu>
              </template>
            </ElDropdown>
          </template>
        </ElTableColumn>
      </ElTable>
      <footer class="list-card__footer"><span>共 {{ total }} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :pager-count="5" layout="sizes, prev, pager, next" :total="total" @current-change="loadRows" @size-change="search" /></footer>
    </section>

  </section>
</template>

<style scoped lang="scss">
.bom-list-page { box-sizing: border-box; min-width: 0; height: 100%; min-height: 0; display: flex; flex-direction: column; padding: 26px 28px 18px; color: #1f1d18; background: var(--erp-page-background); }
.bom-page-heading, .bom-page-heading__title, .bom-filter-actions, .filter-row, .list-card__footer { display: flex; align-items: center; }
.bom-page-heading { height: 46px; flex: none; justify-content: space-between; }
.bom-page-heading__title { gap: 14px; }
.bom-page-heading h1 { margin: 0; font-family: 'Noto Serif SC', serif; font-size: 34px; line-height: 46px; }
.bom-page-heading__title > span { color: #6f6a61; font-size: 13px; }
.bom-filter-actions { flex: none; margin-left: auto; }
.bom-filter-actions :deep(.el-button) { width: 140px; height: 38px; margin: 0; border-radius: 5px; border-color: #c84e28; background: #c84e28; }
.filter-row { min-height: 38px; flex: none; flex-wrap: wrap; gap: 10px 14px; margin-top: 17px; }
.filter-row .search-filter { width: 250px; min-width: 250px; flex: none; }
.filter-row > :deep(.el-select) { width: 196px; flex: none; }
.filter-row > :deep(.el-date-editor) { width: 258px; flex: none; }
.filter-row :deep(.el-input__wrapper), .filter-row :deep(.el-select__wrapper), .filter-row :deep(.el-button) { min-height: 38px; border-radius: 5px; }
.bom-search-button { display: inline-flex; width: 20px; height: 24px; align-items: center; justify-content: center; margin: 0; padding: 0; border: 0; color: inherit; background: transparent; cursor: pointer; }
.bom-search-button img { width: 16px; height: 16px; }
.bom-search-button:focus-visible { outline: 2px solid #3898ec; outline-offset: 2px; }
.list-card { min-height: 0; flex: 1; display: flex; flex-direction: column; margin-top: 22px; overflow: hidden; border: 1px solid #e3dfd7; border-radius: 5px; background: #fdfcf9; }
.list-card :deep(.el-table) { min-height: 0; flex: 1; color: #1f1d18; }
.list-card :deep(.el-table th.el-table__cell) { height: 44px; padding: 0; color: #6f6a61; background: #efebe3; font-size: 11px; font-weight: 500; }
.list-card :deep(.el-table .el-table__cell) { padding: 0; }
.list-card :deep(.el-table .cell) { padding: 0 16px; }
.list-card :deep(.operation-column .cell) { padding: 0 8px; }
.list-card :deep(.el-table .el-table__row) { height: 40px; font-size: 12px; }
.list-card :deep(.el-table .el-table__row > td.el-table__cell) { height: 40px; }
.list-card :deep(.el-table__row:hover > td) { background: #fff6ea; }
.cell-single { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.quantity-cell { display: inline-flex; align-items: baseline; justify-content: flex-end; gap: 4px; white-space: nowrap; }
.quantity-cell > span { color: #6f6a61; font-size: 11px; }
.list-card :deep(.el-tag) { min-width: 76px; height: 24px; justify-content: center; border: 0; border-radius: 999px; }
.bom-list-page .list-card__footer { height: auto !important; min-height: 48px; flex: none; flex-wrap: wrap; justify-content: space-between; gap: 8px; padding: 8px 16px !important; border-top: 1px solid #e3dfd7; color: #6f6a61; font-size: 12px; }
.list-card__footer :deep(.el-pagination) { min-width: 0; max-width: 100%; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-left: auto; --el-pagination-button-bg-color: #fdfcf9; }
.list-card__footer :deep(.is-active) { color: #c84e28; background: #fdfcf9; border: 1px solid #c84e28; }
.more-filter-panel { display: flex; flex-direction: column; gap: 8px; color: #6f6a61; font-size: 12px; }
</style>
