<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  decideCustomerDuplicateCandidate,
  dismissCustomerDuplicateCase,
  fetchCustomer,
  fetchCustomerDuplicateCase,
  fetchCustomerDuplicateCases,
  mergeCustomers,
  previewCustomerMerge,
} from '@/api/customers'
import type {
  CustomerDetail,
  CustomerDuplicateCase,
  CustomerMergePreview,
} from '@/types/customer'

const loading = ref(false)
const actionLoading = ref(false)
const cases = ref<CustomerDuplicateCase[]>([])
const selectedCase = ref<CustomerDuplicateCase | null>(null)
const selectedCaseEtag = ref('')
const candidateDetails = ref<Record<string, CustomerDetail>>({})
const survivorId = ref('')
const search = ref('')
const statusFilter = ref('')
const mergeReason = ref('人工复核确认重复客户')
const preview = ref<CustomerMergePreview | null>(null)
const errorText = ref('')

const filteredCases = computed(() => cases.value.filter((item) => {
  if (statusFilter.value && item.status !== statusFilter.value) return false
  if (!search.value.trim()) return true
  const keyword = search.value.trim().toLowerCase()
  return item.candidates.some((candidate) =>
    `${candidate.customer.account_code} ${candidate.customer.account_name}`.toLowerCase().includes(keyword),
  )
}))
const openCount = computed(() => cases.value.filter((item) => ['OPEN', 'REVIEWING'].includes(item.status)).length)
const highRiskCount = computed(() => cases.value.filter((item) =>
  item.candidates.some((candidate) => Number(candidate.confidence_score) >= 0.9),
).length)
const selectedCandidates = computed(() => selectedCase.value?.candidates || [])
const sourceIds = computed(() => selectedCandidates.value.map((item) => item.customer.id).filter((id) => id !== survivorId.value))

function errorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务。'
  const body = error.response.data as { error?: { message?: string } }
  if (error.response.status === 403) return '当前账号没有重复客户治理权限。'
  if (error.response.status === 412) return '案例已被其他人处理，请刷新后重试。'
  return body.error?.message || '请求失败，请检查案例状态。'
}

function score(candidate: CustomerDuplicateCase['candidates'][number]): number {
  return Math.round(Number(candidate.confidence_score) * 100)
}

function fieldValue(customerId: string, field: keyof CustomerDetail): string {
  const value = candidateDetails.value[customerId]?.[field]
  if (Array.isArray(value)) return value.length ? `${value.length} 项` : '—'
  if (value && typeof value === 'object') {
    return 'display_name' in value ? String(value.display_name) : '已记录'
  }
  return String(value || '—')
}

async function loadCases() {
  loading.value = true
  errorText.value = ''
  try {
    const result = await fetchCustomerDuplicateCases()
    cases.value = result.data
    loading.value = false
    if (selectedCase.value) {
      const latest = cases.value.find((item) => item.id === selectedCase.value?.id)
      if (latest) await selectCase(latest)
      else clearSelection()
    } else if (cases.value[0]) {
      await selectCase(cases.value[0])
    }
  } catch (error) {
    errorText.value = errorMessage(error)
  } finally {
    loading.value = false
  }
}

function clearSelection() {
  selectedCase.value = null
  selectedCaseEtag.value = ''
  survivorId.value = ''
  candidateDetails.value = {}
  preview.value = null
}

async function selectCase(item: CustomerDuplicateCase) {
  actionLoading.value = true
  preview.value = null
  try {
    const versioned = await fetchCustomerDuplicateCase(item.id)
    selectedCase.value = versioned.data
    selectedCaseEtag.value = versioned.etag || ''
    survivorId.value = versioned.data.candidates[0]?.customer.id || ''
    const detailEntries = await Promise.all(versioned.data.candidates.map(async (candidate) => {
      const detail = await fetchCustomer(candidate.customer.id)
      return [candidate.customer.id, detail.data] as const
    }))
    candidateDetails.value = Object.fromEntries(detailEntries)
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    actionLoading.value = false
  }
}

function mergePayload() {
  return {
    survivor_customer_id: survivorId.value,
    source_customer_ids: sourceIds.value,
    reason: mergeReason.value.trim(),
    field_decisions: {},
  }
}

async function runPreview() {
  if (loading.value || actionLoading.value) return
  if (!selectedCase.value || !survivorId.value || !sourceIds.value.length || mergeReason.value.trim().length < 2) {
    ElMessage.warning('请选择主客户并填写合并原因。')
    return
  }
  actionLoading.value = true
  try {
    for (const candidate of selectedCandidates.value.filter((item) => item.customer.id !== survivorId.value)) {
      await decideCustomerDuplicateCandidate(candidate.id, 'DUPLICATE', candidate.etag)
    }
    const survivor = selectedCandidates.value.find((item) => item.customer.id === survivorId.value)
    if (survivor) await decideCustomerDuplicateCandidate(survivor.id, 'SURVIVOR', survivor.etag)
    const refreshed = await fetchCustomerDuplicateCase(selectedCase.value.id)
    selectedCase.value = refreshed.data
    selectedCaseEtag.value = refreshed.etag || ''
    preview.value = await previewCustomerMerge(selectedCase.value.id, mergePayload())
    ElMessage.success('影响预览已由后端实时计算。')
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    actionLoading.value = false
  }
}

async function executeMerge() {
  if (loading.value || actionLoading.value) return
  if (!selectedCase.value || !selectedCaseEtag.value || !preview.value) {
    ElMessage.warning('请先完成合并影响预览。')
    return
  }
  await ElMessageBox.confirm(
    '来源客户将被归档，关联联系人、沟通和业务对象将由后端事务迁移。该操作不能自动撤销，是否继续？',
    '确认合并客户',
    { type: 'warning', confirmButtonText: '确认合并' },
  )
  actionLoading.value = true
  try {
    await mergeCustomers(selectedCase.value.id, mergePayload(), selectedCaseEtag.value)
    ElMessage.success('客户已合并，历史负责人、授权、审计和合并证据均已保留。')
    clearSelection()
    await loadCases()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    actionLoading.value = false
  }
}

async function dismissCase() {
  if (loading.value || actionLoading.value) return
  if (!selectedCase.value || !selectedCaseEtag.value) return
  const note = await ElMessageBox.prompt('请输入忽略原因', '确认不是重复客户', {
    inputValidator: (value) => value.trim().length >= 2 || '至少输入 2 个字',
  })
  actionLoading.value = true
  try {
    await dismissCustomerDuplicateCase(selectedCase.value.id, note.value.trim(), selectedCaseEtag.value)
    ElMessage.success('案例已忽略，并保留处理记录。')
    clearSelection()
    await loadCases()
  } catch (error) {
    ElMessage.error(errorMessage(error))
  } finally {
    actionLoading.value = false
  }
}

onMounted(loadCases)
</script>

<template>
  <div class="duplicate-center" data-duplicate-center>
    <header class="page-heading"><div><h1>重复客户中心</h1><p>识别、对比并合并重复客户，完整保留业务历史。</p></div><ElButton :loading="loading" :disabled="actionLoading" @click="loadCases">刷新检测结果</ElButton></header>
    <section class="stats"><article><span>疑似重复</span><strong>{{ openCount }}</strong><ElTag type="warning">待处理</ElTag></article><article><span>高风险组</span><strong>{{ highRiskCount }}</strong><ElTag type="danger">优先</ElTag></article><article><span>案例总数</span><strong>{{ cases.length }}</strong><ElTag>真实数据</ElTag></article><article><span>已处理</span><strong>{{ cases.filter((item) => !['OPEN', 'REVIEWING'].includes(item.status)).length }}</strong><ElTag type="success">已完成</ElTag></article></section>
    <section class="filters"><ElInput v-model="search" placeholder="搜索客户名称或编号" clearable /><ElSelect v-model="statusFilter" clearable placeholder="状态：全部"><ElOption label="待处理" value="OPEN" /><ElOption label="复核中" value="REVIEWING" /><ElOption label="已忽略" value="DISMISSED" /><ElOption label="已合并" value="MERGED" /></ElSelect><ElButton type="primary" :disabled="loading || actionLoading" @click="loadCases">查询</ElButton></section>
    <ElAlert v-if="errorText" type="error" :title="errorText" :closable="false" show-icon><ElButton size="small" @click="loadCases">重试</ElButton></ElAlert>
    <section class="workspace">
      <ElCard v-loading="loading" shadow="never" class="case-list"><template #header><strong>疑似重复组</strong><span>{{ filteredCases.length }} 组</span></template><button v-for="item in filteredCases" :key="item.id" :class="{ selected: selectedCase?.id === item.id }" :disabled="loading || actionLoading" @click="selectCase(item)"><strong>{{ item.candidates.map((candidate) => candidate.customer.account_name).join(' / ') }}</strong><span>{{ item.candidates.length }} 条客户记录 · {{ item.status }}</span><ElTag :type="Math.max(...item.candidates.map(score)) >= 90 ? 'danger' : 'warning'">{{ Math.max(...item.candidates.map(score)) }}%</ElTag></button><ElEmpty v-if="!filteredCases.length" description="暂无重复案例；检测由后端治理服务产生" :image-size="80" /></ElCard>
      <ElCard v-loading="loading || actionLoading" shadow="never" class="compare"><template #header><div><strong>字段对比与主客户选择</strong><p>系统保留业务历史最完整的客户；人工确认最终主客户。</p></div><ElTag v-if="selectedCase">{{ selectedCase.candidates.length }} 个候选</ElTag></template>
        <template v-if="selectedCase">
          <ElRadioGroup v-model="survivorId" class="candidate-tabs" @change="preview = null"><ElRadio v-for="candidate in selectedCandidates" :key="candidate.id" :value="candidate.customer.id" border><strong>{{ candidate.customer.account_name }}</strong><small>{{ candidate.customer.account_code }} · {{ score(candidate) }}% 匹配</small></ElRadio></ElRadioGroup>
          <ElTable :data="[
            { label: '公司名称', field: 'account_name' }, { label: '国家/地区', field: 'primary_country_code' },
            { label: '网站域名', field: 'primary_website_url' }, { label: '客户阶段', field: 'lifecycle_stage_display' },
            { label: '负责人', field: 'primary_owner' }, { label: '创建时间', field: 'created_at' },
          ]" border>
            <ElTableColumn prop="label" label="字段" width="130" />
            <ElTableColumn v-for="candidate in selectedCandidates" :key="candidate.id" :label="candidate.customer.account_code" min-width="190"><template #default="{ row }"><span :class="{ survivor: candidate.customer.id === survivorId }">{{ fieldValue(candidate.customer.id, row.field) }}</span></template></ElTableColumn>
          </ElTable>
          <ElForm label-position="top" class="merge-form"><ElFormItem label="合并原因" required><ElInput v-model="mergeReason" maxlength="2000" /></ElFormItem></ElForm>
          <ElDescriptions v-if="preview" border :column="3" class="preview"><ElDescriptionsItem v-for="(count, key) in preview.move_counts" :key="key" :label="String(key)">{{ count }}</ElDescriptionsItem></ElDescriptions><ElAlert v-if="preview" type="warning" :title="preview.warnings.join('；')" :closable="false" show-icon />
          <footer><div><ElButton @click="dismissCase">不是重复</ElButton></div><div><ElButton @click="runPreview">预览影响</ElButton><ElButton type="primary" :disabled="!preview" @click="executeMerge">合并客户</ElButton></div></footer>
        </template>
        <ElEmpty v-else description="请选择一个重复案例开始复核" />
      </ElCard>
    </section>
  </div>
</template>

<style lang="scss" scoped>
.duplicate-center { color: var(--erp-color-text-primary); }.page-heading,.stats,.filters,.workspace,.candidate-tabs,footer { display:flex; }.page-heading { align-items:center;justify-content:space-between;margin-bottom:18px }.page-heading h1{margin:0;font-size:28px}.page-heading p,.compare p{margin:5px 0 0;color:var(--erp-color-text-regular);font-size:13px}.stats{gap:12px;margin-bottom:18px}.stats article{position:relative;display:flex;min-height:92px;flex:1;flex-direction:column;gap:8px;padding:16px;border:1px solid var(--erp-color-border);border-radius:10px;background:var(--erp-color-surface)}.stats strong{font-size:24px}.stats .el-tag{position:absolute;top:14px;right:14px}.filters{gap:10px;margin-bottom:12px;padding:12px;border:1px solid var(--erp-color-border);border-radius:10px;background:var(--erp-color-surface)}.filters .el-input{max-width:420px}.workspace{align-items:flex-start;gap:12px;margin-top:12px}.case-list{width:32%;min-width:300px}.case-list :deep(.el-card__header),.compare :deep(.el-card__header){display:flex;justify-content:space-between}.case-list button{position:relative;display:flex;width:100%;min-height:88px;flex-direction:column;gap:7px;margin-bottom:8px;padding:14px;border:1px solid var(--erp-color-border);border-radius:9px;background:var(--erp-color-surface);text-align:left;cursor:pointer}.case-list button.selected{border-color:var(--erp-color-border-strong);background:var(--erp-color-selected)}.case-list button span{color:var(--erp-color-text-regular);font-size:12px}.case-list button .el-tag{position:absolute;top:12px;right:12px}.compare{flex:1;min-width:0}.candidate-tabs{gap:8px;width:100%;margin-bottom:14px}.candidate-tabs :deep(.el-radio){height:auto;min-height:64px;flex:1;margin:0}.candidate-tabs :deep(.el-radio__label){display:flex;flex-direction:column;gap:5px;white-space:normal}.candidate-tabs small{color:var(--erp-color-text-regular)}.survivor{color:var(--erp-color-info);font-weight:700}.merge-form{margin-top:14px}.preview{margin-bottom:12px}footer{justify-content:space-between;margin-top:14px}footer>div{display:flex;gap:8px}@media(max-width:900px){.stats{display:grid;grid-template-columns:repeat(2,1fr)}.workspace{flex-direction:column}.case-list{width:100%}.filters{flex-wrap:wrap}.candidate-tabs{flex-direction:column}}
</style>
