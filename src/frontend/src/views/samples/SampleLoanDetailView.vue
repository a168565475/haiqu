<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { Refresh } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchSampleLoanDetail } from '@/api/samples'
import { useAuthStore } from '@/stores/auth'
import CustomerActivityTag from '@/components/customers/CustomerActivityTag.vue'
import type { SampleLoanDetail } from '@/types/sample'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const loading = ref(true)
const detail = ref<SampleLoanDetail | null>(null)
const errorMessage = ref('')
const loanId = computed(() => String(route.params.loanId || ''))

function getErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '借出单详情加载失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务后重试。'
  const data = error.response.data as { error?: { message?: string }; detail?: string }
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有查看借出单详情的权限。'
  if (error.response.status === 404) return '未找到该借出单，可能已被删除或编号无效。'
  if (error.response.status >= 500) return '样品借出服务暂时异常，请稍后重试。'
  return data?.error?.message || data?.detail || '借出单详情加载失败，请稍后重试。'
}

const canViewLoan = computed(() => authStore.hasPermission('samples.view_sampleinventoryloanline'))
const canViewReceipt = computed(() => authStore.hasPermission('samples.view_sampleinventoryline'))
const canViewSample = computed(() => authStore.hasPermission('samples.view_samplerequest'))
let detailRequest = 0

async function loadDetail() {
  const request = ++detailRequest
  detail.value = null
  if (!canViewLoan.value) {
    errorMessage.value = '当前账号没有查看借出单详情的权限。'
    loading.value = false
    return
  }
  if (!loanId.value) {
    detail.value = null
    errorMessage.value = '借出单标识不能为空。'
    loading.value = false
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchSampleLoanDetail(loanId.value)
    if (request === detailRequest) detail.value = result
  } catch (error) {
    if (request !== detailRequest) return
    detail.value = null
    errorMessage.value = getErrorMessage(error)
  } finally {
    if (request === detailRequest) loading.value = false
  }
}

function backToLoans() {
  void router.push({ name: 'sample-loans' })
}

function openReceiptDetail(receiptId: string) {
  if (!canViewReceipt.value || !receiptId) return
  void router.push({ name: 'sample-inventory-receipt-detail', params: { receiptId } })
}

function openSampleRequest(sampleRequestId: string) {
  if (!canViewSample.value || !sampleRequestId) return
  void router.push({ name: 'sample-detail', params: { sampleId: sampleRequestId } })
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function specificationAndColor(specification: string, color: string): string {
  return [specification, color].filter(Boolean).join(' / ') || '—'
}

function displayValue(value: string): string {
  return value.trim() || '—'
}

watch(loanId, () => { void loadDetail() }, { immediate: true })
onBeforeUnmount(() => { detailRequest++ })
</script>

<template>
  <section v-loading="loading" class="loan-detail-page" data-figma-node="816:9535" aria-labelledby="loan-detail-title">
    <div class="breadcrumb">样品管理 / 样品库 / 借出单详情</div>

    <header class="detail-heading">
      <div class="heading-title">
        <h1 id="loan-detail-title">借出单详情</h1>
        <CustomerActivityTag class="read-only-tag" tone="neutral" label="只读" />
      </div>
      <ElButton class="back-button" @click="backToLoans">返回列表</ElButton>
    </header>

    <template v-if="detail">
      <section class="detail-card overview-card" aria-labelledby="loan-overview-title">
        <h2 id="loan-overview-title" class="card-title">单据概要</h2>
        <div class="overview-grid">
          <div class="info-field"><span>借出编号</span><strong>{{ detail.loan_number }}</strong></div>
          <div class="info-field"><span>单据类型</span><strong>{{ detail.document_type }}</strong></div>
          <div class="info-field"><span>提交人</span><strong>{{ detail.submitted_by }}</strong></div>
          <div class="info-field"><span>提交时间</span><strong>{{ formatDateTime(detail.submitted_at) }}</strong></div>
          <div class="info-field"><span>操作来源</span><strong>{{ detail.operation_source }}</strong></div>
          <div class="info-field status-field"><span>状态</span><strong>{{ detail.status_display }}</strong></div>
        </div>
        <CustomerActivityTag class="completed-tag occupancy-tag" tone="warning" :label="detail.inventory_status_display" />
      </section>

      <section class="detail-card operation-card" aria-labelledby="loan-operation-title">
        <h2 id="loan-operation-title" class="card-title">操作信息</h2>
        <div class="operation-grid">
          <div class="info-field">
            <span>操作说明</span>
            <strong>借用人和用途按明细保存；当前版本不提供归还入口。</strong>
          </div>
          <div class="info-field">
            <span>数量规则</span>
            <strong>操作数量不得超过提交时可用库存</strong>
          </div>
        </div>
      </section>

      <section class="detail-card lines-card" aria-labelledby="loan-lines-title">
        <div class="card-title title-with-count">
          <h2 id="loan-lines-title">借出明细</h2>
          <span>{{ detail.line_count }} 条明细</span>
        </div>
        <div class="lines-table" role="table" aria-label="借出明细">
          <div class="lines-table-head" role="row">
            <span>来源入库批次</span>
            <span>样品跟进单号</span>
            <span>产品名称</span>
            <span>规格 / 颜色</span>
            <span>借出数量</span>
            <span>借用人</span>
            <span>用途 / 备注</span>
            <span>库存影响</span>
            <span aria-hidden="true"></span>
          </div>
          <div class="lines-table-body">
            <div v-if="!detail.lines.length" class="detail-empty">暂无借出明细</div>
            <div v-for="line in detail.lines" :key="line.id" class="lines-table-row" role="row">
              <button type="button" class="source-link" :disabled="!canViewReceipt || !line.receipt_id" @click="openReceiptDetail(line.receipt_id)">
                {{ line.receipt_number }}
              </button>
              <span>{{ line.sample_request_number }}</span>
              <span>{{ line.product_name || '—' }}</span>
              <span>{{ specificationAndColor(line.specification, line.color) }}</span>
              <span>{{ line.loan_quantity }}</span>
              <span>{{ displayValue(line.borrower_name) }}</span>
              <span>{{ displayValue(line.purpose_note) }}</span>
              <span class="inventory-impact">{{ line.inventory_impact }}</span>
              <span aria-hidden="true"></span>
            </div>
          </div>
        </div>
      </section>

      <section class="detail-card source-card" aria-labelledby="loan-source-title">
        <h2 id="loan-source-title" class="card-title">来源样品跟进单</h2>
        <div class="source-list">
          <div v-if="!detail.lines.length" class="detail-empty">暂无来源样品</div>
          <div v-for="line in detail.lines" :key="`source-${line.id}`" class="source-row">
            <button type="button" class="source-link" :disabled="!canViewSample || !line.sample_request_id" @click="openSampleRequest(line.sample_request_id)">
              {{ line.sample_request_number }}
            </button>
            <span>{{ line.product_name || '—' }}</span>
            <CustomerActivityTag class="source-status" tone="success" label="查看来源" />
            <span class="source-flow">按编号进入样品跟进详情查看完整来源流程</span>
          </div>
        </div>
      </section>

      <section class="prototype-note" aria-label="借出规则说明">
        <span>按来源入库批次查看入库记录，按来源样品编号查看打样申请。</span>
        <strong>借出数量持续占用可用库存</strong>
      </section>
    </template>

    <ElResult
      v-else-if="!loading"
      class="detail-error"
      icon="error"
      title="无法显示借出单详情"
      :sub-title="errorMessage"
    >
      <template #extra>
        <ElButton :icon="Refresh" type="primary" :disabled="!canViewLoan || !loanId" @click="loadDetail">重新加载</ElButton>
        <ElButton @click="backToLoans">返回列表</ElButton>
      </template>
    </ElResult>
  </section>
</template>

<style scoped lang="scss" src="./sampleLoanDetail.scss"></style>