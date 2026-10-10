<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  deleteSampleLoan,
  fetchSampleLoanOptions,
  fetchSampleLoans,
  fetchSampleLoanSummary,
} from '@/api/samples'
import SampleLoanCreateDialog from '@/components/samples/SampleLoanCreateDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  SampleLoanOptions,
  SampleLoanQuery,
  SampleLoanRow,
  SampleLoanSummary,
} from '@/types/sample'

type OperatedPeriod = NonNullable<SampleLoanQuery['operated_period']>

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const summaryLoading = ref(false)
const optionsLoading = ref(false)
const loanDialogVisible = ref(false)
const dialogMounted = ref(false)
watch(loanDialogVisible, visible => { if (visible) dialogMounted.value = true })
const deletingLoanIds = ref<Set<string>>(new Set())
const errorMessage = ref('')
const summaryError = ref('')
const optionsError = ref('')
let listRequest = 0
let summaryRequest = 0
let optionsRequest = 0
const rows = ref<SampleLoanRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const summary = ref<SampleLoanSummary | null>(null)
const options = ref<SampleLoanOptions>({ borrower_names: [], product_categories: [] })
const filters = reactive<{
  keyword: string
  borrowerName: string
  categoryName: string
  operatedPeriod: OperatedPeriod | ''
}>({ keyword: '', borrowerName: '', categoryName: '', operatedPeriod: '' })

const timeOptions: Array<{ value: OperatedPeriod; label: string }> = [
  { value: 'TODAY', label: '今日' },
  { value: 'THIS_MONTH', label: '本月' },
  { value: 'LAST_30_DAYS', label: '近30天' },
]

const statCards = computed(() => [
  { key: 'active', label: '借出中', value: summary.value?.active_documents, icon: '↗', tone: 'orange' },
  { key: 'cumulative', label: '累计借出', value: summary.value?.cumulative_borrowed, icon: '→', tone: 'blue' },
  { key: 'customer', label: '客户现场确认', value: summary.value?.customer_confirmation, icon: '✓', tone: 'green' },
  { key: 'showroom', label: '展厅 / 拍摄', value: summary.value?.showroom_or_photo, icon: '◎', tone: 'purple' },
])
const canDeleteLoan = computed(() => (
  authStore.hasPermission('samples.delete_sampleinventoryloan')
))
const canCreateLoan = computed(() => authStore.hasPermission('samples.add_sampleinventoryloan'))
const canViewInventory = computed(() => authStore.hasPermission('samples.view_sampleinventoryline'))
const canViewOutbound = computed(() => authStore.hasPermission('samples.view_sampleinventoryoutboundline'))

function getErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务后重试。'
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有查看样品借出记录的权限。'
  if (error.response.status >= 500) return '样品借出服务暂时异常，请稍后重试。'
  return data?.error?.message || data?.detail || '请求失败，请检查筛选条件。'
}

function getDeleteErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '删除失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务后重试。'
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  if (error.response.status === 403) return '当前账号没有删除样品借出单的权限。'
  if (error.response.status >= 500) return '删除服务暂时异常，请稍后重试。'
  return data?.error?.message || data?.detail || '删除失败，请刷新列表后重试。'
}

function buildQuery(): SampleLoanQuery {
  const query: SampleLoanQuery = {
    page: page.value,
    page_size: pageSize.value,
    ordering: '-loan__operated_at',
  }
  if (filters.keyword.trim()) query.q = filters.keyword.trim()
  if (filters.borrowerName) query.borrower_name = filters.borrowerName
  if (filters.categoryName) query.category_name = filters.categoryName
  if (filters.operatedPeriod) query.operated_period = filters.operatedPeriod
  return query
}

async function loadRows() {
  const request = ++listRequest
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchSampleLoans(buildQuery())
    if (request !== listRequest) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (error) {
    if (request !== listRequest) return
    rows.value = []
    total.value = 0
    errorMessage.value = getErrorMessage(error)
  } finally {
    if (request === listRequest) loading.value = false
  }
}

async function loadSummary() {
  const request = ++summaryRequest
  summaryError.value = ''
  summaryLoading.value = true
  try {
    const result = await fetchSampleLoanSummary()
    if (request !== summaryRequest) return
    summary.value = result
  } catch (error) {
    if (request !== summaryRequest) return
    summary.value = null
    summaryError.value = `借出统计加载失败：${getErrorMessage(error)}`
  } finally {
    if (request === summaryRequest) summaryLoading.value = false
  }
}

async function loadOptions() {
  const request = ++optionsRequest
  optionsError.value = ''
  optionsLoading.value = true
  try {
    const result = await fetchSampleLoanOptions()
    if (request !== optionsRequest) return
    options.value = result
  } catch (error) {
    if (request !== optionsRequest) return
    optionsError.value = `筛选选项加载失败：${getErrorMessage(error)}`
  } finally {
    if (request === optionsRequest) optionsLoading.value = false
  }
}

function searchLoans() {
  page.value = 1
  void loadRows()
}

function resetFilters() {
  Object.assign(filters, { keyword: '', borrowerName: '', categoryName: '', operatedPeriod: '' })
  page.value = 1
  void loadRows()
}

function refreshPage() {
  void Promise.all([loadRows(), loadSummary(), loadOptions()])
}

function openInventoryList() {
  if (!canViewInventory.value) return
  void router.push({ name: 'sample-inventory' })
}

function openOutboundList() {
  if (!canViewOutbound.value) return
  void router.push({ name: 'sample-outbound' })
}

function openLoanDetail(loanId: string) {
  void router.push({ name: 'sample-loan-detail', params: { loanId } })
}

async function deleteLoan(row: SampleLoanRow) {
  if (!canDeleteLoan.value || loading.value || deletingLoanIds.value.has(row.loan_id)) return
  deletingLoanIds.value = new Set([...deletingLoanIds.value, row.loan_id])
  try {
    try { await ElMessageBox.confirm(
      `确认删除借出单 ${row.loan_number} 及其全部明细吗？删除后对应数量将恢复到剩余库存。`,
      '删除样品借出单',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
      },
    ) } catch { return }
    if (!canDeleteLoan.value) return
    await deleteSampleLoan(row.loan_id)
    const removedCurrentPage = rows.value.every((item) => item.loan_id === row.loan_id)
    if (removedCurrentPage && page.value > 1) page.value -= 1
    ElMessage.success('样品借出单已删除，库存数量已恢复。')
    refreshPage()
  } catch (error) {
    ElMessage.error(getDeleteErrorMessage(error))
  } finally {
    const nextIds = new Set(deletingLoanIds.value)
    nextIds.delete(row.loan_id)
    deletingLoanIds.value = nextIds
  }
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

onMounted(() => {
  refreshPage()
})
</script>

<template>
  <section class="sample-loan-page" data-figma-node="812:9236" aria-labelledby="sample-loan-title">
    <header class="page-heading">
      <div class="title-line">
        <h1 id="sample-loan-title">样品库</h1>
        <span>查看样品借出单及库存占用明细</span>
      </div>
      <div class="heading-actions">
        <ElButton :disabled="!canViewInventory" @click="openInventoryList">样品入库</ElButton>
        <ElButton :disabled="!canViewOutbound" @click="openOutboundList">样品出库</ElButton>
        <ElButton type="primary" :disabled="!canCreateLoan" @click="canCreateLoan && (loanDialogVisible = true)">样品借出</ElButton>
      </div>
    </header>

    <nav class="inventory-tabs" aria-label="样品库分类">
      <button type="button" class="inventory-tab" :disabled="!canViewInventory" @click="openInventoryList">样品库存</button>
      <button type="button" class="inventory-tab" :disabled="!canViewOutbound" @click="openOutboundList">样品出库</button>
      <button type="button" class="inventory-tab is-active" aria-current="page">样品借出</button>
    </nav>

    <div v-loading="summaryLoading" class="stats-grid">
      <article v-for="card in statCards" :key="card.key" class="stat-card">
        <div class="stat-copy">
          <span>{{ card.label }}</span>
          <strong>{{ card.value ?? '—' }}</strong>
        </div>
        <span class="stat-icon" :class="`is-${card.tone}`" aria-hidden="true">
          {{ card.icon }}
        </span>
      </article>
    </div>

    <div v-if="summaryError" class="load-error" role="alert">{{ summaryError }} <ElButton link @click="loadSummary">重试统计</ElButton></div>
    <div v-if="optionsError" class="load-error" role="alert">{{ optionsError }} <ElButton link @click="loadOptions">重试选项</ElButton></div>

    <ElCard class="filter-card" shadow="never">
      <ElForm class="filter-grid" label-position="top" @submit.prevent="searchLoans">
        <ElFormItem label="关键词">
          <ElInput
            v-model="filters.keyword"
            clearable
            placeholder="输入借出编号、跟进单号或产品名称"
            aria-label="借出关键词"
            maxlength="100"
          />
        </ElFormItem>
        <ElFormItem label="借用人">
          <ElSelect v-model="filters.borrowerName" aria-label="借用人" clearable placeholder="全部" :loading="optionsLoading">
            <ElOption v-for="item in options.borrower_names" :key="item" :label="item" :value="item" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="产品类别">
          <ElSelect v-model="filters.categoryName" aria-label="产品类别" clearable placeholder="全部" :loading="optionsLoading">
            <ElOption v-for="item in options.product_categories" :key="item" :label="item" :value="item" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="操作时间">
          <ElSelect v-model="filters.operatedPeriod" aria-label="操作时间" clearable placeholder="全部时间">
            <ElOption v-for="item in timeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </ElSelect>
        </ElFormItem>
        <div class="filter-actions">
          <ElButton type="primary" native-type="submit">查询</ElButton>
          <ElButton @click="resetFilters">重置</ElButton>
        </div>
      </ElForm>
    </ElCard>

    <div class="table-toolbar">
      <span>按明细行展示，单据编号可重复</span>
      <div class="toolbar-actions">
        <!-- TODO：接入有权限控制的完整借出导出接口后启用。 -->
        <span title="借出记录导出接口尚未开放"><ElButton disabled>导出</ElButton></span>
        <ElButton :loading="loading" @click="refreshPage">刷新</ElButton>
      </div>
    </div>

    <ElAlert
      v-if="errorMessage"
      class="list-error"
      type="error"
      :title="errorMessage"
      show-icon
      :closable="false"
    >
      <template #default><ElButton link type="primary" @click="refreshPage">重新加载</ElButton></template>
    </ElAlert>

    <ElCard class="table-card" shadow="never">
      <ElTable
        v-loading="loading"
        :data="rows"
        height="100%"
        row-key="id"
        :empty-text="errorMessage ? '列表加载失败' : '暂无样品借出记录。完成借出后将在这里显示。'"
      >
        <ElTableColumn prop="loan_number" label="借出编号" width="160" fixed="left" show-overflow-tooltip>
          <template #default="{ row }">
            <button class="document-link" type="button" @click="openLoanDetail(row.loan_id)">
              {{ row.loan_number }}
            </button>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="operator_name" label="操作人" width="80" show-overflow-tooltip />
        <ElTableColumn prop="operated_at" label="操作时间" width="140">
          <template #default="{ row }">{{ formatDateTime(row.operated_at) }}</template>
        </ElTableColumn>
        <ElTableColumn prop="sample_request_number" label="样品跟进单号" width="160" show-overflow-tooltip />
        <ElTableColumn prop="product_category" label="产品类别" width="100" show-overflow-tooltip />
        <ElTableColumn prop="product_name" label="产品名称" width="150" show-overflow-tooltip />
        <ElTableColumn label="规格 / 颜色" width="190" show-overflow-tooltip>
          <template #default="{ row }">{{ row.specification || '—' }} / {{ row.color || '—' }}</template>
        </ElTableColumn>
        <ElTableColumn prop="loan_quantity" label="借出数" width="80" align="center" />
        <ElTableColumn prop="borrower_name" label="借用人" width="110" show-overflow-tooltip />
        <ElTableColumn prop="purpose_note" label="用途 / 备注" min-width="330" show-overflow-tooltip>
          <template #default="{ row }">{{ row.purpose_note || '—' }}</template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="110" align="center" fixed="right">
          <template #default="{ row }">
            <ElButton link type="primary" @click="openLoanDetail(row.loan_id)">查看</ElButton>
            <ElButton
              v-if="canDeleteLoan"
              link
              type="danger"
              :loading="deletingLoanIds.has(row.loan_id)"
              :disabled="loading || deletingLoanIds.has(row.loan_id)"
              @click="deleteLoan(row)"
            >删除</ElButton>
          </template>
        </ElTableColumn>
      </ElTable>
      <footer class="table-footer">
        <span>共 {{ total }} 条</span>
        <ElPagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          background
          layout="sizes, prev, pager, next"
          :page-sizes="[20, 50, 100]"
          :total="total"
          @current-change="loadRows"
          @size-change="() => { page = 1; void loadRows() }"
        />
      </footer>
    </ElCard>

    <SampleLoanCreateDialog
      v-if="canCreateLoan && dialogMounted"
      v-model="loanDialogVisible"
      @created="refreshPage"
    />
  </section>
</template>

<style scoped lang="scss" src="./sampleLoan.scss"></style>
