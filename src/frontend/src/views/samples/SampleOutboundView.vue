<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'

import {
  deleteSampleOutbound,
  fetchSampleOutbound,
  fetchSampleOutboundOptions,
  fetchSampleOutboundSummary,
} from '@/api/samples'
import SampleOutboundCreateDialog from '@/components/samples/SampleOutboundCreateDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  SampleOutboundMethod,
  SampleOutboundOptions,
  SampleOutboundQuery,
  SampleOutboundRow,
  SampleOutboundSummary,
} from '@/types/sample'

type OperatedPeriod = NonNullable<SampleOutboundQuery['operated_period']>

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const summaryLoading = ref(false)
const optionsLoading = ref(false)
const errorMessage = ref('')
const summaryError = ref('')
const optionsError = ref('')
let listRequest = 0
let summaryRequest = 0
let optionsRequest = 0
const rows = ref<SampleOutboundRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const summary = ref<SampleOutboundSummary | null>(null)
const options = ref<SampleOutboundOptions>({ outbound_methods: [], product_categories: [] })
const outboundDialogVisible = ref(false)
const dialogMounted = ref(false)
watch(outboundDialogVisible, visible => { if (visible) dialogMounted.value = true })
const deletingOutboundIds = ref<Set<string>>(new Set())
const filters = reactive<{
  keyword: string
  outboundMethod: SampleOutboundMethod | ''
  categoryName: string
  operatedPeriod: OperatedPeriod | ''
}>({ keyword: '', outboundMethod: '', categoryName: '', operatedPeriod: '' })

const timeOptions: Array<{ value: OperatedPeriod; label: string }> = [
  { value: 'TODAY', label: '今日' },
  { value: 'THIS_MONTH', label: '本月' },
  { value: 'LAST_30_DAYS', label: '近30天' },
]

const statCards = computed(() => [
  { key: 'today', label: '今日出库', value: summary.value?.outbound_today, icon: '→', tone: 'blue' },
  { key: 'month', label: '本月出库', value: summary.value?.outbound_this_month, icon: '✓', tone: 'green' },
  { key: 'mail', label: '跟单员邮寄', value: summary.value?.mailed, icon: '↗', tone: 'orange' },
  { key: 'carry', label: '业务员带走', value: summary.value?.salesperson_carried, icon: '人', tone: 'purple' },
])
const canDeleteOutbound = computed(() => (
  authStore.hasPermission('samples.delete_sampleinventoryoutbound')
))
const canCreateOutbound = computed(() => authStore.hasPermission('samples.add_sampleinventoryoutbound'))
const canViewInventory = computed(() => authStore.hasPermission('samples.view_sampleinventoryline'))
const canViewLoans = computed(() => authStore.hasPermission('samples.view_sampleinventoryloanline'))

function getErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务后重试。'
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有查看样品出库记录的权限。'
  if (error.response.status >= 500) return '样品出库服务暂时异常，请稍后重试。'
  return data?.error?.message || data?.detail || '请求失败，请检查筛选条件。'
}

function getDeleteErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '删除失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务后重试。'
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  if (error.response.status === 403) return '当前账号没有删除样品出库单的权限。'
  if (error.response.status >= 500) return '删除服务暂时异常，请稍后重试。'
  return data?.error?.message || data?.detail || '删除失败，请刷新列表后重试。'
}

function buildQuery(): SampleOutboundQuery {
  const query: SampleOutboundQuery = {
    page: page.value,
    page_size: pageSize.value,
    ordering: '-outbound__operated_at',
  }
  if (filters.keyword.trim()) query.q = filters.keyword.trim()
  if (filters.outboundMethod) query.outbound_method = filters.outboundMethod
  if (filters.categoryName) query.category_name = filters.categoryName
  if (filters.operatedPeriod) query.operated_period = filters.operatedPeriod
  return query
}

async function loadRows() {
  const request = ++listRequest
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchSampleOutbound(buildQuery())
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
    const result = await fetchSampleOutboundSummary()
    if (request !== summaryRequest) return
    summary.value = result
  } catch (error) {
    if (request !== summaryRequest) return
    summary.value = null
    summaryError.value = `出库统计加载失败：${getErrorMessage(error)}`
  } finally {
    if (request === summaryRequest) summaryLoading.value = false
  }
}

async function loadOptions() {
  const request = ++optionsRequest
  optionsError.value = ''
  optionsLoading.value = true
  try {
    const result = await fetchSampleOutboundOptions()
    if (request !== optionsRequest) return
    options.value = result
  } catch (error) {
    if (request !== optionsRequest) return
    optionsError.value = `筛选选项加载失败：${getErrorMessage(error)}`
  } finally {
    if (request === optionsRequest) optionsLoading.value = false
  }
}

function searchOutbound() {
  page.value = 1
  void loadRows()
}

function resetFilters() {
  Object.assign(filters, { keyword: '', outboundMethod: '', categoryName: '', operatedPeriod: '' })
  page.value = 1
  void loadRows()
}

function refreshPage() {
  void Promise.all([loadRows(), loadSummary(), loadOptions()])
}

function handleOutboundCreated() {
  refreshPage()
}

function openInventoryList() {
  if (!canViewInventory.value) return
  void router.push({ name: 'sample-inventory' })
}

function openLoanList() {
  if (!canViewLoans.value) return
  void router.push({ name: 'sample-loans' })
}

function openOutboundDetail(outboundId: string) {
  void router.push({ name: 'sample-outbound-detail', params: { outboundId } })
}

async function deleteOutbound(row: SampleOutboundRow) {
  if (!canDeleteOutbound.value || loading.value || deletingOutboundIds.value.has(row.outbound_id)) return
  deletingOutboundIds.value = new Set([...deletingOutboundIds.value, row.outbound_id])
  try {
    try { await ElMessageBox.confirm(
      `确认删除出库单 ${row.outbound_number} 及其全部明细吗？删除后对应数量将恢复到剩余库存。`,
      '删除样品出库单',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
      },
    ) } catch { return }
    if (!canDeleteOutbound.value) return
    await deleteSampleOutbound(row.outbound_id)
    const removedCurrentPage = rows.value.every((item) => item.outbound_id === row.outbound_id)
    if (removedCurrentPage && page.value > 1) page.value -= 1
    ElMessage.success('样品出库单已删除，库存数量已恢复。')
    refreshPage()
  } catch (error) {
    ElMessage.error(getDeleteErrorMessage(error))
  } finally {
    const nextIds = new Set(deletingOutboundIds.value)
    nextIds.delete(row.outbound_id)
    deletingOutboundIds.value = nextIds
  }
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function deliveryDetail(row: SampleOutboundRow): string {
  if (row.outbound_method === 'MERCHANDISER_MAIL') return row.tracking_number || '—'
  if (row.outbound_method === 'OTHER') return row.remark || '—'
  return '—'
}

onMounted(() => {
  refreshPage()
})
</script>

<template>
  <section class="sample-outbound-page erp-glass-list" data-figma-node="812:8933" aria-labelledby="sample-outbound-title">
    <section v-glass-spotlight class="erp-list-filter">
    <header class="page-heading erp-list-heading">
      <div class="title-line">
        <h1 id="sample-outbound-title">样品库</h1>
        <span>查看仓库出库单及样品明细</span>
      </div>

    </header>

    <nav class="inventory-tabs erp-list-tabs" aria-label="样品库分类">
      <button type="button" class="inventory-tab" :disabled="!canViewInventory" @click="openInventoryList">样品库存</button>
      <button type="button" class="inventory-tab is-active" aria-current="page">样品出库</button>
      <button type="button" class="inventory-tab" :disabled="!canViewLoans" @click="openLoanList">样品借出</button>
    </nav>

    <div v-loading="summaryLoading" class="stats-grid erp-list-summary">
      <article v-for="card in statCards" :key="card.key" class="stat-card erp-list-summary-item">
        <div class="stat-copy">
          <span>{{ card.label }}</span>
          <strong>{{ card.value ?? '—' }}</strong>
        </div>
        <span class="stat-icon erp-list-tag" :class="`erp-list-tag--${({ green: 'success', orange: 'warning', blue: 'info', red: 'danger', purple: 'brand' } as Record<string, string>)[card.tone] || 'info'}`" aria-hidden="true">
          {{ card.icon }}
        </span>
      </article>
    </div>

    <div v-if="summaryError" class="load-error" role="alert">{{ summaryError }} <ElButton link @click="loadSummary">重试统计</ElButton></div>
    <div v-if="optionsError" class="load-error" role="alert">{{ optionsError }} <ElButton link @click="loadOptions">重试选项</ElButton></div>

    <div class="filter-card">
      <ElForm class="filter-grid erp-list-filters" label-position="top" @submit.prevent="searchOutbound">
        <ElFormItem label="关键词">
          <ElInput
            v-model="filters.keyword"
            clearable
            placeholder="输入出库编号、打样单号、产品名称或快递单号"
            aria-label="出库关键词"
            maxlength="100"
          />
        </ElFormItem>
        <ElFormItem label="出库方式">
          <ElSelect v-model="filters.outboundMethod" aria-label="出库方式" clearable placeholder="全部" :loading="optionsLoading">
            <ElOption
              v-for="item in options.outbound_methods"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
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
        <div class="filter-actions erp-list-filter-actions">
          <ElButton class="erp-button-motion" @click="resetFilters">重置</ElButton>
          <ElButton class="erp-button-motion" type="primary" native-type="submit">应用筛选</ElButton>
        </div>
      </ElForm>
    </div>
    </section>

    <section class="table-card erp-list-data">
    <div class="table-toolbar erp-list-toolbar">
      <div class="heading-actions">
        <ElButton class="erp-button-motion" :disabled="!canViewInventory" @click="openInventoryList">样品入库</ElButton>
        <ElButton class="erp-button-motion" type="primary" :disabled="!canCreateOutbound" @click="canCreateOutbound && (outboundDialogVisible = true)">样品出库</ElButton>
        <ElButton class="erp-button-motion" :disabled="!canViewLoans" @click="openLoanList">样品借出</ElButton>
      </div>
      <span>按明细行展示，单据编号可重复</span>
      <div class="toolbar-actions">
        <!-- TODO：接入有权限控制的完整出库导出接口后启用。 -->
        <span title="出库记录导出接口尚未开放"><ElButton class="erp-button-motion" disabled>导出</ElButton></span>
        <ElButton class="erp-button-motion" :loading="loading" @click="refreshPage">刷新</ElButton>
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

    <div class="erp-list-table-frame">
      <ElTable
        v-loading="loading"
        :data="rows"
        height="100%"
        row-key="id"
        :empty-text="errorMessage ? '列表加载失败' : '暂无样品出库记录。完成出库后将在这里显示。'"
      >
        <ElTableColumn prop="outbound_number" label="出库编号" width="160" fixed="left" show-overflow-tooltip>
          <template #default="{ row }">
            <button class="document-link" type="button" @click="openOutboundDetail(row.outbound_id)">
              {{ row.outbound_number }}
            </button>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="operator_name" label="操作人" width="80" show-overflow-tooltip />
        <ElTableColumn prop="operated_at" label="操作时间" width="140">
          <template #default="{ row }">{{ formatDateTime(row.operated_at) }}</template>
        </ElTableColumn>
        <ElTableColumn prop="sample_request_number" label="样品跟进单号" width="160" show-overflow-tooltip />
        <ElTableColumn prop="product_category" label="产品类别" width="100" show-overflow-tooltip />
        <ElTableColumn prop="product_name" label="产品名称" width="140" show-overflow-tooltip />
        <ElTableColumn label="规格 / 颜色" width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.specification || '—' }} / {{ row.color || '—' }}</template>
        </ElTableColumn>
        <ElTableColumn prop="outbound_quantity" label="出库数" width="80" align="center" />
        <ElTableColumn prop="outbound_method_display" label="出库方式" width="120" show-overflow-tooltip />
        <ElTableColumn prop="courier_company" label="快递公司" width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.courier_company || '—' }}</template>
        </ElTableColumn>
        <ElTableColumn label="快递单号 / 备注" min-width="230" show-overflow-tooltip>
          <template #default="{ row }">{{ deliveryDetail(row) }}</template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="110" align="center" fixed="right">
          <template #default="{ row }">
            <ElButton link type="primary" @click="openOutboundDetail(row.outbound_id)">查看</ElButton>
            <ElButton
              v-if="canDeleteOutbound"
              link
              type="danger"
              :loading="deletingOutboundIds.has(row.outbound_id)"
              :disabled="loading || deletingOutboundIds.has(row.outbound_id)"
              @click="deleteOutbound(row)"
            >删除</ElButton>
          </template>
        </ElTableColumn>
      </ElTable>
    </div>
      <footer class="table-footer erp-list-footer">
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
    </section>
  </section>

  <SampleOutboundCreateDialog
    v-if="canCreateOutbound && dialogMounted"
    v-model="outboundDialogVisible"
    @created="handleOutboundCreated"
  />
</template>

<style scoped lang="scss" src="./sampleOutbound.scss"></style>
