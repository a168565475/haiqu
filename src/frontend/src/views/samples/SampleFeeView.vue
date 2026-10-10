<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'

import { createSampleFeeRecord, decideSampleFeeWaiver, fetchSample, fetchSampleOptions, uploadSampleFeeEvidence } from '@/api/samples'
import { fetchAllMasterDataRecords } from '@/api/referenceData'
import { useAuthStore } from '@/stores/auth'
import type { SampleDetail, SampleFeeApproval, SampleFeeRecord, SampleOptions } from '@/types/sample'
import type { Currency } from '@/types/referenceData'
import SampleSection from '@/components/samples/SampleSection.vue'
import CustomerActivityTag from '@/components/customers/CustomerActivityTag.vue'
import { useSampleUnsavedChanges } from '@/composables/useSampleUnsavedChanges'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const sampleId = computed(() => String(route.params.sampleId || ''))
const sample = ref<SampleDetail | null>(null)
const options = ref<SampleOptions | null>(null)
const currencies = ref<Currency[]>([])
const etag = ref('')
const loading = ref(true)
const submitting = ref(false)
const uploadingEvidence = ref(false)
const errorMessage = ref('')
const savedForm = ref('')

const emptyFeeForm = {
  fee_decision: 'PAID' as 'PAID' | 'FREE' | 'WAIVED',
  currency_code: '',
  sample_fee_amount: '',
  shipping_fee_amount: '',
  discount_amount: '',
  payment_terms: '',
  freight_bearer: '',
  payment_due_at: '',
  verification_status: 'PENDING',
  decision_reason: '',
  free_confirmed_by_employee_id: '',
  approver_employee_id: '',
}
const feeForm = reactive({ ...emptyFeeForm })

const currentFee = computed<SampleFeeRecord | null>(() =>
  sample.value?.fee_records.find((item) => !item.superseded_at) || null,
)
const latestApproval = computed<SampleFeeApproval | null>(() =>
  currentFee.value?.requested_decision === 'WAIVED'
    ? sample.value?.fee_approvals.slice().sort((a, b) => b.created_at.localeCompare(a.created_at))[0] || null
    : null,
)
const canDecideFee = computed(() => authStore.moduleCan('samples.decide_sample_fee', undefined, sample.value))
const canApproveFee = computed(() => authStore.moduleCan('access_control.approve_samplefee', 'samples.change_samplefeerecord', sample.value)
  && currentFee.value?.approval_status === 'PENDING'
  && latestApproval.value?.status === 'PENDING'
  && Boolean(authStore.user?.employee?.id)
  && latestApproval.value?.approver?.id === authStore.user?.employee?.id)
const pageEditable = computed(() => ['PENDING', 'PREPARING'].includes(sample.value?.status || ''))
const canUploadEvidence = computed(() => authStore.moduleCan('samples.add_samplefilelink', undefined, sample.value) && Boolean(sample.value)
  && !['CONFIRMED', 'COMPLETED', 'FINISHED', 'REJECTED', 'CANCELLED'].includes(sample.value?.status || ''))
const busy = computed(() => loading.value || submitting.value || uploadingEvidence.value)
const formDisabled = computed(() => !canDecideFee.value || !pageEditable.value || busy.value || Boolean(errorMessage.value))
const dirty = computed(() => Boolean(savedForm.value) && JSON.stringify(feeForm) !== savedForm.value)
useSampleUnsavedChanges(() => dirty.value, '离开样品费用页')
const feeStatus = computed(() => currentFee.value?.verification_status_display || '尚未登记费用')
function statusTone(status?: string): 'success' | 'warning' | 'danger' | 'neutral' {
  if (['CONFIRMED', 'MANUALLY_CONFIRMED', 'APPROVED', 'CLEAN', 'NOT_REQUIRED'].includes(status || '')) return 'success'
  if (['REJECTED', 'INFECTED', 'FAILED'].includes(status || '')) return 'danger'
  return status ? 'warning' : 'neutral'
}
const payableAmount = computed(() => {
  const parse = (value: string) => Number.parseFloat(value || '0') || 0
  return Math.max(0, parse(feeForm.sample_fee_amount) + parse(feeForm.shipping_fee_amount) - parse(feeForm.discount_amount))
})
const evidenceFiles = computed(() => sample.value?.files.filter((item) => item.file_role === 'FEE_EVIDENCE') || [])
const paymentCurrencyLabel = computed(() => feeForm.currency_code.trim().toUpperCase() || '—')
const currencyChoices = computed(() => {
  const active = currencies.value.map((item) => ({
    code: item.code,
    label: `${item.code} · ${item.chinese_name || item.english_name}`,
    disabled: false,
  }))
  const current = feeForm.currency_code.trim().toUpperCase()
  if (current && !active.some((item) => item.code === current)) {
    active.push({ code: current, label: `${current}（历史停用值，请改选）`, disabled: true })
  }
  return active
})

function getErrorMessage(error: unknown): string {
  if (!(error instanceof AxiosError)) return '请求失败，请稍后重试。'
  if (!error.response) return '网络异常，已保留当前输入内容，请检查连接后重试。'
  const data = error.response.data as { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string }
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有执行该操作的权限。'
  if (error.response.status === 409) return data.error?.message || '当前业务状态不允许执行该操作。'
  if (error.response.status === 412) return '数据已被其他人更新，请重新加载后再提交。'
  if (error.response.status === 428) return '缺少数据版本，请重新加载后重试。'
  if (error.response.status >= 500) return '后端服务暂时异常，请稍后重试。'
  const fieldErrors = data.error?.field_errors
  if (fieldErrors) return Object.values(fieldErrors).flat().join('；')
  return data.error?.message || data.detail || '提交失败，请检查输入。'
}

function formatDateTime(value?: string | null) {
  if (!value) return '未维护'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '未维护' : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

function formatMoney(value: string | number) {
  return Number(value || 0).toFixed(2)
}

function applySample(value: SampleDetail, version: string, preserveForm = false) {
  sample.value = value
  etag.value = version || value.etag
  if (preserveForm) return
  const record = value.fee_records.find((item) => !item.superseded_at)
  if (!record) { Object.assign(feeForm, emptyFeeForm); savedForm.value = JSON.stringify(feeForm); return }
  feeForm.fee_decision = (record.requested_decision === 'WAIVED' ? 'WAIVED' : record.fee_decision === 'FREE' ? 'FREE' : 'PAID')
  feeForm.currency_code = record.currency_code || ''
  feeForm.sample_fee_amount = record.sample_fee_amount || ''
  feeForm.shipping_fee_amount = record.shipping_fee_amount || ''
  feeForm.discount_amount = record.discount_amount || ''
  feeForm.payment_terms = record.payment_terms || ''
  feeForm.freight_bearer = record.freight_bearer || ''
  feeForm.payment_due_at = record.payment_due_at || ''
  feeForm.verification_status = record.verification_status || 'PENDING'
  feeForm.decision_reason = record.decision_reason || ''
  feeForm.free_confirmed_by_employee_id = record.free_confirmed_by?.id || ''
  feeForm.approver_employee_id = latestApproval.value?.approver?.id || ''
  savedForm.value = JSON.stringify(feeForm)
}

async function loadPage(preserveForm = false) {
  if (!sampleId.value) return
  loading.value = true
  errorMessage.value = ''
  try {
    const [detail, optionData, currencyRows] = await Promise.all([
      fetchSample(sampleId.value),
      fetchSampleOptions(),
      fetchAllMasterDataRecords<Currency>('currencies', { status: 'ACTIVE' }),
    ])
    options.value = optionData
    currencies.value = currencyRows
    applySample(detail.data, detail.etag, preserveForm)
  } catch (error) {
    errorMessage.value = getErrorMessage(error)
  } finally {
    loading.value = false
  }
}

function requireDecisionFields(): boolean {
  if (!etag.value) { ElMessage.warning('缺少数据版本，请重新加载后重试。'); return false }
  if (!feeForm.currency_code.trim()) {
    ElMessage.warning('请选择币种。')
    return false
  }
  if (feeForm.fee_decision === 'PAID' && payableAmount.value <= 0) {
    ElMessage.warning('收费样的应付合计必须大于 0。')
    return false
  }
  if (feeForm.fee_decision === 'PAID') {
    if ([feeForm.sample_fee_amount, feeForm.shipping_fee_amount, feeForm.discount_amount].some(value => value.trim() && !/^\d+(\.\d{1,4})?$/.test(value.trim()))) {
      ElMessage.warning('费用请输入非负金额，最多保留四位小数。'); return false
    }
    if (!feeForm.freight_bearer) { ElMessage.warning('请选择运费承担方。'); return false }
  }
  if (feeForm.fee_decision === 'FREE' && (!feeForm.decision_reason.trim() || !feeForm.freight_bearer || !feeForm.free_confirmed_by_employee_id)) {
    ElMessage.warning('免费样必须填写商业理由、运费承担方并选择确认人。')
    return false
  }
  if (feeForm.fee_decision === 'WAIVED' && (!feeForm.decision_reason.trim() || !feeForm.approver_employee_id)) {
    ElMessage.warning('费用豁免必须填写申请原因并选择审批人。')
    return false
  }
  return true
}

async function uploadEvidence(uploadFile: { raw?: File }) {
  const file = uploadFile.raw
  if (!sample.value || !file || !canUploadEvidence.value || busy.value || errorMessage.value) return
  if (!etag.value) { ElMessage.warning('缺少数据版本，请重新加载后重试。'); return }
  const suffix = file.name.split('.').pop()?.toLowerCase()
  if (!suffix || !['pdf', 'jpg', 'jpeg', 'png'].includes(suffix)) {
    ElMessage.warning('付款凭证仅支持 PDF、JPG 或 PNG 格式。')
    return
  }
  if (file.size <= 0 || file.size > 10 * 1024 * 1024) {
    ElMessage.warning('付款凭证必须大于 0 字节且不超过 10MB。')
    return
  }
  uploadingEvidence.value = true
  try {
    const result = await uploadSampleFeeEvidence(sample.value.id, file, etag.value)
    etag.value = result.etag
    ElMessage.success('付款凭证已上传并关联到当前样品。')
    await loadPage(true)
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    uploadingEvidence.value = false
  }
}

async function submitFee() {
  if (!sample.value || formDisabled.value || !requireDecisionFields()) return
  submitting.value = true
  try {
    const result = await createSampleFeeRecord(sample.value.id, {
      fee_decision: feeForm.fee_decision,
      currency_code: feeForm.currency_code.trim().toUpperCase(),
      sample_fee_amount: feeForm.sample_fee_amount || '0',
      shipping_fee_amount: feeForm.shipping_fee_amount || '0',
      discount_amount: feeForm.discount_amount || '0',
      payment_terms: feeForm.payment_terms.trim(),
      freight_bearer: feeForm.freight_bearer || undefined,
      payment_due_at: feeForm.payment_due_at || null,
      verification_status: feeForm.fee_decision === 'PAID' ? (evidenceFiles.value.length ? 'EVIDENCE_UPLOADED' : 'PENDING') : 'NOT_REQUIRED',
      decision_reason: feeForm.decision_reason.trim(),
      free_confirmed_by_employee_id: feeForm.free_confirmed_by_employee_id || null,
      approver_employee_id: feeForm.approver_employee_id || null,
    }, etag.value)
    etag.value = result.etag
    ElMessage.success(feeForm.fee_decision === 'WAIVED' ? '费用豁免已提交审批。' : '费用决定已保存，并已写入审计记录。')
    await loadPage()
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    submitting.value = false
  }
}

async function decideWaiver(approved: boolean) {
  if (!sample.value || !latestApproval.value || !canApproveFee.value || busy.value || errorMessage.value) return
  if (!etag.value) { ElMessage.warning('缺少数据版本，请重新加载后重试。'); return }
  submitting.value = true
  try {
    const result = await decideSampleFeeWaiver(sample.value.id, latestApproval.value.approval_id, approved, etag.value)
    etag.value = result.etag
    ElMessage.success(approved ? '费用豁免已审批通过。' : '费用豁免已拒绝。')
    await loadPage(dirty.value)
  } catch (error) {
    ElMessage.error(getErrorMessage(error))
  } finally {
    submitting.value = false
  }
}

// TODO: 接入独立费用草稿、发票生成与受控账户快照接口后开放相应入口。

onMounted(() => { void loadPage() })
</script>

<template>
  <section v-loading="loading" class="sample-fee-page" aria-label="样品费用处理" data-visual-reference="258:5218">
    <template v-if="sample">
      <header class="fee-page-header">
        <div class="title-line"><h1>样品费用处理</h1><span>{{ sample.request_number }} · {{ sample.customer_name }} · {{ sample.sample_type_display }}</span><CustomerActivityTag :label="feeStatus" :tone="statusTone(currentFee?.verification_status)" /></div>
        <div class="top-actions">
          <ElButton @click="router.push(`/samples/${sample.id}`)">返回详情</ElButton>
          <ElButton disabled title="暂未开放费用草稿保存">保存草稿</ElButton>
          <ElButton type="primary" :loading="submitting" :disabled="formDisabled" @click="submitFee">提交确认</ElButton>
        </div>
      </header>
      <div v-if="errorMessage" class="fee-error" role="alert"><span>{{ errorMessage }}</span><ElButton :disabled="busy" @click="loadPage(true)">重新加载</ElButton></div>
      <section class="sample-context-card" aria-label="样品费用摘要">
        <div><strong>样品明细：{{ sample.item_summary.text || '未维护' }}</strong><span>样品费 {{ currentFee?.currency_code || '—' }} {{ formatMoney(currentFee?.sample_fee_amount || 0) }} · 运费 {{ formatMoney(currentFee?.shipping_fee_amount || 0) }} · 合计 {{ formatMoney(currentFee?.payable_amount || 0) }}</span></div>
        <p>费用决定由本页登记；到账状态由财务确认</p>
      </section>
      <div class="decision-heading"><b>费用处理方式</b><span>三种方式互斥，切换后按对应规则提交</span></div>
      <div class="fee-layout">
        <main class="fee-main">
          <div class="decision-list">
            <button v-for="option in options?.fee_decisions" :key="option.value" type="button" class="decision-choice" :class="{ selected: feeForm.fee_decision === option.value }" :aria-pressed="feeForm.fee_decision === option.value" :disabled="formDisabled" @click="feeForm.fee_decision = option.value as 'PAID' | 'FREE' | 'WAIVED'">
              <span class="decision-icon" aria-hidden="true">{{ option.value === 'PAID' ? '¥' : option.value === 'FREE' ? '✓' : '◇' }}</span><span class="decision-copy"><b>{{ option.label }}</b><small>{{ option.value === 'PAID' ? '客户承担样品费与运费' : option.value === 'FREE' ? '样品费免收，可保留运费约定' : '按审批范围豁免费用' }}</small></span>
              <span class="decision-hint">{{ feeForm.fee_decision === option.value ? '当前选择' : option.value === 'FREE' ? '需填写商业理由' : option.value === 'WAIVED' ? '需主管确认' : '记录费用与付款约定' }}</span>
            </button>
          </div>
          <SampleSection title="费用计算与付款约定" class="fee-calculation">
            <ElForm label-position="top" :disabled="formDisabled" class="fee-form-grid">
              <ElFormItem label="样品费"><ElInput v-model="feeForm.sample_fee_amount" aria-label="样品费" :disabled="formDisabled || feeForm.fee_decision !== 'PAID'" placeholder="0.00"><template #prefix>{{ paymentCurrencyLabel }}</template></ElInput></ElFormItem>
              <ElFormItem label="运费"><ElInput v-model="feeForm.shipping_fee_amount" aria-label="运费" :disabled="formDisabled || feeForm.fee_decision !== 'PAID'" placeholder="0.00"><template #prefix>{{ paymentCurrencyLabel }}</template></ElInput></ElFormItem>
              <ElFormItem label="折扣"><ElInput v-model="feeForm.discount_amount" aria-label="折扣" :disabled="formDisabled || feeForm.fee_decision !== 'PAID'" placeholder="0.00"><template #prefix>{{ paymentCurrencyLabel }}</template></ElInput></ElFormItem>
              <ElFormItem label="应付合计"><ElInput :model-value="`${paymentCurrencyLabel} ${feeForm.fee_decision === 'PAID' ? formatMoney(payableAmount) : '0.00'}`" readonly aria-label="应付合计" /></ElFormItem>
              <ElFormItem label="付款条款"><ElInput v-model="feeForm.payment_terms" aria-label="付款条款" placeholder="例如：发货前付款" /></ElFormItem>
              <ElFormItem label="账户渠道"><ElInput :model-value="currentFee?.account_reference || '暂未提供收款账户'" readonly aria-label="账户渠道" /></ElFormItem>
              <ElFormItem label="费用负责人"><ElInput :model-value="currentFee?.decided_by?.display_name || sample.owner?.display_name || '未维护'" readonly aria-label="费用负责人" /></ElFormItem>
              <ElFormItem label="截止时间"><ElDatePicker v-model="feeForm.payment_due_at" aria-label="截止时间" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" placeholder="请选择" /></ElFormItem>
              <ElFormItem label="币种" required><ElSelect v-model="feeForm.currency_code" aria-label="币种" filterable placeholder="请选择币种"><ElOption v-for="item in currencyChoices" :key="item.code" :label="item.label" :value="item.code" :disabled="item.disabled" /></ElSelect></ElFormItem>
              <ElFormItem label="运费承担方" :required="feeForm.fee_decision !== 'WAIVED'"><ElSelect v-model="feeForm.freight_bearer" aria-label="运费承担方" placeholder="请选择"><ElOption v-for="item in options?.freight_bearers" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></ElFormItem>
              <ElFormItem v-if="feeForm.fee_decision === 'FREE'" label="免费确认人" required><ElSelect v-model="feeForm.free_confirmed_by_employee_id" filterable placeholder="请选择在职员工"><ElOption v-for="item in options?.fee_approvers" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem>
              <ElFormItem v-if="feeForm.fee_decision === 'WAIVED'" label="豁免审批人" required><ElSelect v-model="feeForm.approver_employee_id" filterable placeholder="请选择在职员工"><ElOption v-for="item in options?.fee_approvers" :key="item.id" :label="item.display_name" :value="item.id" /></ElSelect></ElFormItem>
            </ElForm>
            <div class="formula-bar">应付合计 = 样品费 + 运费 − 折扣；金额保留 2 位小数显示</div>
          </SampleSection>
          <SampleSection title="样品发票与附件" class="fee-documents">
            <template #actions><ElButton disabled title="暂未开放样品发票生成">生成样品发票</ElButton></template>
            <div class="document-row"><div><strong>样品发票：暂未生成</strong><small>样品发票服务暂未开放</small></div><div class="document-actions"><ElButton disabled>预览</ElButton><ElButton disabled>下载</ElButton></div></div>
            <div class="document-row evidence-row"><div class="evidence-list"><strong v-if="!evidenceFiles.length">付款凭证：尚未上传</strong><div v-for="file in evidenceFiles" :key="file.id" class="evidence-file"><span :title="file.original_name">{{ file.original_name }}</span><CustomerActivityTag :label="file.scan_status === 'CLEAN' ? '扫描通过' : file.scan_status === 'PENDING' ? '待扫描' : file.scan_status" :tone="statusTone(file.scan_status)" /></div><small>上传仅作为付款证据，不能直接标记到账</small></div><ElUpload accept=".pdf,.jpg,.jpeg,.png" :auto-upload="false" :show-file-list="false" :disabled="!canUploadEvidence || busy || Boolean(errorMessage)" @change="uploadEvidence"><ElButton :loading="uploadingEvidence" :disabled="!canUploadEvidence || busy || Boolean(errorMessage)">上传付款凭证</ElButton></ElUpload></div>
            <p class="upload-tip">支持 PDF、JPG、PNG，单个文件不超过 10MB。</p>
          </SampleSection>
          <SampleSection title="业务理由与备注" class="fee-notes"><ElInput v-model="feeForm.decision_reason" aria-label="业务理由与备注" :disabled="formDisabled" type="textarea" :rows="5" maxlength="1000" show-word-limit :placeholder="feeForm.fee_decision === 'PAID' ? '客户处于重点开发阶段、样品用途等说明（选填）' : '请填写商业理由或豁免申请原因（必填）'" /></SampleSection>
        </main>
        <aside class="fee-side">
          <SampleSection title="确认与审批" class="fee-approval">
            <div class="approval-step"><span>1</span><div><b>业务选择</b><small>{{ currentFee?.decided_by?.display_name || '尚未提交费用决定' }}</small></div><CustomerActivityTag :label="currentFee ? currentFee.fee_decision_display : '待选择'" :tone="currentFee ? 'success' : 'neutral'" /></div>
            <div class="approval-step"><span>2</span><div><b>主管确认</b><small>{{ latestApproval?.approver?.display_name || currentFee?.free_confirmed_by?.display_name || '—' }}</small></div><CustomerActivityTag :label="latestApproval?.status_display || (currentFee ? '无需审批' : '待提交')" :tone="statusTone(latestApproval?.status || (currentFee ? 'NOT_REQUIRED' : ''))" /></div>
            <div class="approval-step"><span>3</span><div><b>财务核验</b><small>{{ currentFee ? formatDateTime(currentFee.decided_at || currentFee.created_at) : '—' }}</small></div><CustomerActivityTag :label="feeStatus" :tone="statusTone(currentFee?.verification_status)" /></div>
            <template v-if="latestApproval"><p class="approval-reason">{{ latestApproval.request_reason }}</p><p v-if="latestApproval.decision_note" class="approval-reason">审批说明：{{ latestApproval.decision_note }}</p><div v-if="canApproveFee" class="approval-actions"><ElButton :disabled="busy || Boolean(errorMessage)" @click="decideWaiver(false)">拒绝</ElButton><ElButton type="primary" :disabled="busy || Boolean(errorMessage)" :loading="submitting" @click="decideWaiver(true)">审批通过</ElButton></div></template>
          </SampleSection>
          <SampleSection title="收款账户快照" class="fee-account"><template #actions><CustomerActivityTag :label="currentFee?.account_reference ? '已记录' : '暂未提供'" tone="neutral" /></template><p v-if="currentFee?.account_reference">{{ currentFee.account_reference }}</p><p v-else>受控收款账户暂未提供，请联系财务确认。</p><span>收款账户由财务维护，业务员不可自由输入。</span></SampleSection>
          <SampleSection title="控制规则" class="fee-rules"><ol><li>账户来自财务维护的收款账户，业务员不可自由输入。</li><li>付款凭证仅作为附件，到账由财务核验确认。</li><li>免费样需填写商业理由、运费承担方及确认人；费用豁免须经审批后生效。</li><li>样品费用不在本页进行核销。</li></ol></SampleSection>
        </aside>
      </div>
    </template>
    <ElResult v-else-if="errorMessage" icon="error" title="样品费用加载失败" :sub-title="errorMessage"><template #extra><ElButton type="primary" @click="loadPage()">重新加载</ElButton><ElButton @click="router.push('/samples')">返回样品列表</ElButton></template></ElResult>
  </section>
</template>

<style scoped lang="scss" src="./sampleFee.scss"></style>

