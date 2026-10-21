<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

import { fetchSample } from '@/api/samples'
import {
  confirmSampleMaterialIssue,
  fetchSampleMaterialIssue,
  initiateSampleMaterialIssue,
} from '@/api/sampleMaterialIssue'
import SampleSection from '@/components/samples/SampleSection.vue'
import SampleStatusTag from '@/components/samples/SampleStatusTag.vue'
import type { SampleDetail } from '@/types/sample'
import type { SampleMaterialIssueLine, SampleMaterialIssueResult } from '@/types/sampleMaterialIssue'
import { sampleMaterialCategories, type SampleMaterialCategory } from '@/types/sampleMaterial'
import { sampleProductFieldLabel, sampleProductsLabel, sampleQuantityLabel } from '@/utils/samplePresentation'
import { createClientUuid } from '@/utils/clientUuid'

const route = useRoute()
const router = useRouter()
const sample = ref<SampleDetail | null>(null)
const result = ref<SampleMaterialIssueResult | null>(null)
const etag = ref('')
const loading = ref(true)
const saving = ref(false)
const errorMessage = ref('')
const actionError = ref('')
const note = ref('')
const confirmationRequestId = createClientUuid()
const categoryFilter = ref<'all' | SampleMaterialCategory>('all')

const confirmMode = computed(() => route.name === 'sample-material-issue-confirm')
const lines = computed(() => result.value?.lines || [])
const categoryTabs = computed(() => {
  const counts = new Map<string, number>()
  lines.value.forEach((line) => counts.set(line.category, (counts.get(line.category) || 0) + 1))
  return [
    { key: 'all' as const, label: '全部材料', count: lines.value.length },
    ...sampleMaterialCategories
      .filter((category) => counts.has(category.key))
      .map((category) => ({ key: category.key, label: category.label, count: counts.get(category.key) || 0 })),
  ]
})
const visibleLines = computed(() => categoryFilter.value === 'all' ? lines.value : lines.value.filter((line) => line.category === categoryFilter.value))
const title = computed(() => confirmMode.value ? '仓库确认样品领料' : '发起样品领料')
const issueTagStatus = computed(() => result.value?.status === 'ISSUED' ? 'MATERIALS_READY' : result.value?.status === 'PENDING_CONFIRMATION' ? 'MATERIAL_ISSUE_REVIEW' : 'MATERIAL_ISSUE_PENDING')
const colorLabel = computed(() => {
  const colors = (sample.value?.products || []).flatMap((product) => product.details || [])
    .map((detail) => [detail.color_name, detail.color_card, detail.color_code].filter(Boolean).join(' / '))
    .filter(Boolean)
  return colors.join('；') || '—'
})
const applicationFields = computed(() => [
  { label: '客户', value: sample.value?.customer_name || '—' },
  { label: '产品名称', value: sample.value ? sampleProductsLabel(sample.value) : '—' },
  { label: '规格', value: sample.value ? sampleProductFieldLabel(sample.value, 'specification') : '—' },
  { label: '颜色', value: colorLabel.value },
  { label: '打样数量', value: sample.value ? sampleQuantityLabel(sample.value) : '—' },
  { label: '申请日期', value: sample.value?.requested_at?.slice(0, 10) || '—' },
])
const canSubmit = computed(() => Boolean(result.value?.available && etag.value && !loading.value
  && (confirmMode.value ? result.value.canConfirm && !result.value.blockers?.length : result.value.canInitiate) && !saving.value))

function messageFromError(error: unknown) {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (error.response?.status === 412) return '数据已被其他人更新，请刷新后重试。'
  if (error.response?.status === 403) return '当前账号没有执行该操作的权限。'
  const data = error.response?.data as { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } | undefined
  const fields = data?.error?.field_errors
  return fields ? Object.values(fields).flat().join('；') : data?.error?.message || data?.detail || '提交失败，请检查后重试。'
}

function applyIssue(value: SampleMaterialIssueResult, version: string) {
  result.value = value
  if (categoryFilter.value !== 'all' && !value.lines?.some((line) => line.category === categoryFilter.value)) categoryFilter.value = 'all'
  etag.value = version || value.etag || ''
}

async function loadPage() {
  const sampleId = String(route.params.sampleId || '')
  if (!sampleId) { errorMessage.value = '缺少样品编号，请从样品列表进入。'; loading.value = false; return }
  loading.value = true; errorMessage.value = ''; actionError.value = ''
  try {
    const [sampleResponse, issueResponse] = await Promise.all([fetchSample(sampleId), fetchSampleMaterialIssue(sampleId)])
    sample.value = sampleResponse.data
    applyIssue(issueResponse.data, issueResponse.etag)
  } catch (error) { errorMessage.value = messageFromError(error) }
  finally { loading.value = false }
}

async function initiate() {
  if (!sample.value || !canSubmit.value) return
  try { await ElMessageBox.confirm('确认发起整张样品领料？仓库将全部领走本次核库可供和采购已到货的材料。', '发起样品领料', { confirmButtonText: '确认发起', cancelButtonText: '返回' }) }
  catch { return }
  saving.value = true; actionError.value = ''
  try {
    const response = await initiateSampleMaterialIssue(sample.value.id, etag.value, note.value.trim())
    applyIssue(response.data, response.etag)
    ElMessage.success('样品领料已发起，等待仓库确认。')
  } catch (error) { actionError.value = messageFromError(error) }
  finally { saving.value = false }
}

function issueQuantity(line: SampleMaterialIssueLine) {
  const quantity = line.issuedQuantity ?? line.availableQuantity
  if (line.category !== 'tube') return quantity
  const bars = line.barCount != null && (line.pipeBatches?.length || Number(quantity) === 0) ? line.barCount : '—'
  const meters = quantity.replace(/(\.\d*?[1-9])0+$|\.0+$/, '$1')
  return `${bars} 根 / ${meters} 米`
}

function pipeBatchDescription(line: SampleMaterialIssueLine) {
  return line.pipeBatches?.map(batch => `${batch.warehouseName} / ${batch.zoneName}：${batch.barCount} 根 × ${batch.rawBarLengthM} 米 = ${batch.meterQuantity} 米`).join('；') || ''
}

async function confirmIssue() {
  if (!sample.value || !canSubmit.value) return
  saving.value = true; actionError.value = ''
  try { await ElMessageBox.confirm('确认已全部领走本次核库可供和采购已到货的材料？提交后按页面数量扣减库存。', '全部领料', { confirmButtonText: '确认全部领料', cancelButtonText: '返回' }) }
  catch { saving.value = false; return }
  try {
    const response = await confirmSampleMaterialIssue(sample.value.id, etag.value, confirmationRequestId)
    applyIssue(response.data, response.etag)
    ElMessage.success('本次可供材料已全部领走，样品可以进入参数和生产阶段。')
  } catch (error) { actionError.value = messageFromError(error) }
  finally { saving.value = false }
}

onMounted(loadPage)
</script>

<template>
  <section class="sample-material-issue-page" aria-label="样品领料">
      <main v-loading="loading" class="sample-material-issue-content">
        <header class="issue-heading">
          <div><h1>{{ title }}</h1><SampleStatusTag v-if="sample" :status="sample.status" :label="sample.status_display" /></div>
          <p>申请编号 {{ sample?.request_number || '—' }}</p>
        </header>
        <div v-if="errorMessage" role="alert" class="issue-error"><span>{{ errorMessage }}</span><ElButton @click="loadPage">重新加载</ElButton></div>
        <template v-else-if="sample && result?.available">
          <section class="issue-context" aria-label="申请与样品信息">
            <div v-for="field in applicationFields" :key="field.label" class="issue-context-field">
              <label>{{ field.label }}</label><strong :title="field.value">{{ field.value }}</strong>
            </div>
          </section>
          <SampleSection title="材料领料明细" class="issue-card">
            <template #actions><SampleStatusTag :status="issueTagStatus" :label="result.statusLabel || '待发起领料'" /></template>
            <p class="issue-intro">本次核库可供和采购已到货的材料全部领走，无需填写数量；未领缺口见明细。</p>
            <div v-if="result.blockers?.length" role="alert" class="issue-error">{{ result.blockers.join('；') }}</div>
            <nav v-if="categoryTabs.length > 1" class="issue-tabs" aria-label="材料分类">
              <button v-for="tab in categoryTabs" :key="tab.key" type="button" :class="{ active: categoryFilter === tab.key }" @click="categoryFilter = tab.key">{{ tab.label }} {{ tab.count }}</button>
            </nav>
            <div class="issue-table-wrap">
              <table class="erp-table-editor issue-table">
                <thead><tr><th>材料分类</th><th>材料名称</th><th>规格</th><th>材质</th><th>颜色 / 色卡 / 色号</th><th>需求数量</th><th>仓库可供</th><th>需采购</th><th>已到货</th><th>实际领料</th><th>未领缺口</th><th>单位</th><th>状态</th></tr></thead>
                <tbody>
                  <tr v-for="line in visibleLines" :key="line.id || line.lineKey">
                    <td>{{ sampleMaterialCategories.find((category) => category.key === line.category)?.label || line.category || '—' }}</td><td class="primary-text">{{ line.name || '—' }}</td><td class="specification">{{ line.specification || '—' }}</td><td>{{ line.material || '—' }}</td><td>{{ line.color || '—' }}</td>
                    <td>{{ line.requestedQuantity }}</td><td>{{ line.warehouseQuantity }}</td><td>{{ line.procurementQuantity ?? '—' }}</td><td>{{ line.arrivedQuantity }}</td>
                    <td :title="pipeBatchDescription(line)"><span data-testid="readonly-issued-quantity">{{ issueQuantity(line) }}</span></td><td>{{ line.shortageQuantity || '0' }}</td><td>{{ line.unitLabel || '—' }}</td><td><SampleStatusTag :status="issueTagStatus" :label="result.statusLabel || '待发起领料'" /></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </SampleSection>
          <div v-if="!confirmMode && result.status === 'NOT_STARTED'" class="issue-note"><label for="issue-note">领料备注（选填）</label><ElInput id="issue-note" v-model="note" type="textarea" :rows="2" maxlength="2000" placeholder="补充仓库领料安排" /></div>
        </template>
        <ElEmpty v-else-if="!loading" description="当前没有可操作的样品领料内容" />
      </main>
      <footer class="issue-actions"><ElButton @click="router.push({ name: 'sample-detail', params: { sampleId: sample?.id } })">返回详情</ElButton><span v-if="actionError" role="alert" class="action-error">{{ actionError }}</span><ElButton v-if="!confirmMode && result?.status === 'NOT_STARTED'" type="primary" :loading="saving" :disabled="!canSubmit" @click="initiate">发起领料</ElButton><ElButton v-if="confirmMode && result?.status === 'PENDING_CONFIRMATION'" type="primary" :loading="saving" :disabled="!canSubmit" @click="confirmIssue">全部领料</ElButton></footer>
  </section>
</template>

<style scoped lang="scss" src="./sampleMaterialIssue.scss"></style>
