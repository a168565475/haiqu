<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createQuotationFromInquiry, fetchInquiryQuotationContext } from '@/api/quotations'
import type { InquiryQuotationContext } from '@/types/quotation'
import InquiryActionDialog from '@/components/inquiries/InquiryActionDialog.vue'
import InquiryNotice from '@/components/inquiries/InquiryNotice.vue'
import { newInquiryKey } from '@/views/inquiries/inquiryEditorState'
import { fetchAllMasterDataRecords } from '@/api/referenceData'
import type { Currency } from '@/types/referenceData'

const props = defineProps<{ modelValue: boolean; inquiryId: string; inquiryEtag: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; created: [quotationId: string, versionId: string] }>()
const router = useRouter()
const loading = ref(false)
const currencies = ref<Currency[]>([])
let generation = 0
let requestKey = ''
let requestSignature = ''
const uncertain = ref(false)
const submitting = ref(false)
const error = ref('')
const context = ref<InquiryQuotationContext | null>(null)
const form = reactive({ entityId: '', legalName: '', country: '', subject: '', currency: 'USD', dueAt: '', createAnother: false })
const visible = computed({ get: () => props.modelValue, set: (value) => { if (!submitting.value) emit('update:modelValue', value) } })
const needsEntity = computed(() => Boolean(context.value?.requires_entity && !form.entityId))
const hasExisting = computed(() => Boolean(context.value?.existing_quotations.length))
const preflightPassed = computed(() => Boolean(context.value?.preflight.length && context.value.preflight.every(item => item.passed)))

function errorText(errorValue: any) {
  const status = errorValue?.response?.status
  const detail = errorValue?.response?.data?.detail || errorValue?.response?.data?.error?.message
  if (status === 401) return '登录状态已失效，请重新登录。'
  if (status === 403) return '当前账号没有创建报价权限。'
  if (status === 409) return detail || '当前询盘已有进行中的报价，请明确选择。'
  if (status === 412 || status === 428) return '询盘已被更新，请关闭窗口后刷新页面再试。'
  if (!errorValue?.response) return '网络异常，已保留输入内容，请检查网络后重试。'
  return detail || '创建报价失败，请稍后重试。'
}
async function loadContext() {
  const version = ++generation
  context.value = null; loading.value = true; error.value = ''; uncertain.value = false
  requestKey = ''; requestSignature = ''
  Object.assign(form, { entityId: '', legalName: '', country: '', subject: '', currency: '', dueAt: '', createAnother: false })
  try {
    if (!props.inquiryId) throw new Error('缺少询盘编号')
    const [result, currencyRows] = await Promise.all([fetchInquiryQuotationContext(props.inquiryId), fetchAllMasterDataRecords<Currency>('currencies', { status: 'ACTIVE' })])
    if (version !== generation) return
    context.value = result.data
    currencies.value = currencyRows
    form.entityId = result.data.entities[0]?.id || ''
    form.subject = result.data.default_subject
    form.currency = result.data.default_currency_code
  } catch (errorValue) { if (version === generation) error.value = errorText(errorValue) }
  finally { if (version === generation) loading.value = false }
}
function openExisting(id: string) { visible.value = false; void router.push({ name: 'quotation-edit', params: { quotationId: id } }) }
async function submit() {
  if (submitting.value || loading.value || uncertain.value || !context.value?.allowed.create_quote || !preflightPassed.value || !props.inquiryEtag) return
  if (!form.subject.trim()) { error.value = '请填写报价主题。'; return }
  if (!Number.isFinite(Date.parse(form.dueAt)) || Date.parse(form.dueAt) <= Date.now()) { error.value = '报价草稿截止时间必须晚于当前时间。'; return }
  if (!currencies.value.some(item => item.code === form.currency && item.status === 'ACTIVE')) { error.value = '请选择有效币种。'; return }
  if (needsEntity.value && !context.value.can_create_entity) { error.value = '当前账号无权补录交易主体，请先完善客户资料。'; return }
  if (needsEntity.value && (!form.legalName.trim() || !form.country.trim())) return ElMessage.warning('请填写法定主体名称和注册国家。')
  if (hasExisting.value && !form.createAnother) return ElMessage.warning('请打开已有报价，或明确勾选“新建另一份报价”。')
  submitting.value = true; error.value = ''
  try {
    const payload = {
      inquiry_id: props.inquiryId, transaction_entity_id: form.entityId || null,
      transaction_entity: needsEntity.value ? { legal_name: form.legalName.trim(), registration_country_code: form.country.trim().toUpperCase() } : undefined,
      subject: form.subject.trim(), currency_code: form.currency, due_at: form.dueAt,
      idempotency_key: '', create_another: form.createAnother,
    }
    const signature = JSON.stringify(payload)
    if (signature !== requestSignature) { requestKey = newInquiryKey(); requestSignature = signature }
    payload.idempotency_key = requestKey
    const result = await createQuotationFromInquiry(payload, props.inquiryEtag)
    ElMessage.success(result.data.replayed ? '已返回此前创建的报价草稿。' : '报价草稿已创建，询盘已进入“报价中”。')
    emit('update:modelValue', false)
    emit('created', result.data.quotation.id, result.data.version_id)
  } catch (errorValue) {
    error.value = errorText(errorValue)
    const response = (errorValue as { response?: { status?: number } })?.response
    if (!response || (response.status || 0) >= 500) { uncertain.value = true; error.value = '创建结果尚未确认，请关闭窗口并刷新列表核对已有报价，避免重复创建。' }
  } finally { submitting.value = false }
}
watch([() => props.modelValue, () => props.inquiryId], ([opened]) => { if (opened) void loadContext(); else generation++ }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>

<template>
  <InquiryActionDialog v-model="visible" title="创建报价" subtitle="需求确认 → 报价中" :width="640" :height="720"
    confirm-label="确认并创建报价" :confirm-width="141" :busy="submitting" :loading="loading" :error="error"
    :disabled="!context?.allowed.create_quote || !preflightPassed || !inquiryEtag || uncertain" @confirm="submit">
    <template v-if="context">
      <InquiryNotice :tone="preflightPassed ? 'success' : 'warning'" :title="preflightPassed ? '报价前置检查已通过' : '报价前置检查未通过'">已检查客户关联、产品需求和询盘负责人。</InquiryNotice>
      <section class="inquiry-quote-checks"><span v-for="item in context.preflight" :key="item.code" :class="{ fail: !item.passed }">{{ item.passed ? '✓' : '!' }} {{ item.label }}</span></section>
      <InquiryNotice v-if="hasExisting" tone="warning" title="该询盘已有进行中的报价"><div v-for="quote in context.existing_quotations" :key="quote.id" class="inquiry-existing-quote"><span>{{ quote.quotation_number }} · {{ quote.subject }}</span><el-button link :disabled="submitting" @click="openExisting(quote.id)">打开报价</el-button></div><el-checkbox v-model="form.createAnother" :disabled="submitting">我确认新建另一份报价</el-checkbox></InquiryNotice>
      <el-form label-position="top" :disabled="submitting || uncertain" class="inquiry-quote-form">
        <el-form-item label="报价主题" required><el-input v-model="form.subject" maxlength="250"/></el-form-item>
        <div class="inquiry-form-grid inquiry-quote-grid"><el-form-item label="币种" required><el-select popper-class="inquiry-v4-select" v-model="form.currency"><el-option v-for="item in currencies" :key="item.code" :label="item.code" :value="item.code" :disabled="item.status !== 'ACTIVE'"/></el-select></el-form-item><el-form-item label="报价草稿截止时间" required><el-date-picker popper-class="inquiry-v4-select" v-model="form.dueAt" type="datetime" format="YYYY-MM-DD HH:mm" value-format="YYYY-MM-DDTHH:mm:ssZ"/></el-form-item></div>
        <el-form-item label="客户交易主体"><el-select popper-class="inquiry-v4-select" v-model="form.entityId" clearable placeholder="请选择交易主体"><el-option v-for="entity in context.entities" :key="entity.id" :label="`${entity.legal_name}（${entity.entity_code}）`" :value="entity.id"/></el-select></el-form-item>
        <section v-if="needsEntity && context.can_create_entity"><p class="inquiry-dialog-hint">补录客户交易主体；编号由系统生成。</p><div class="inquiry-form-grid"><el-form-item label="法定主体名称" required><el-input v-model="form.legalName"/></el-form-item><el-form-item label="注册国家" required><el-input v-model="form.country" maxlength="3"/></el-form-item></div></section>
      </el-form>
      <InquiryNotice title="来源产品明细">将复制产品、规格、数量和单位；目标价仅保留为需求快照，报价单价仍待录入。</InquiryNotice>
      <p class="inquiry-dialog-hint inquiry-quote-hint">若已有进行中的报价，系统会提示打开原报价或明确新建另一份。</p>
    </template>
    <el-button v-else-if="!loading" @click="loadContext">重新加载</el-button>
  </InquiryActionDialog>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.inquiry-quote-checks { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 12px 24px; margin: 14px 0 20px; color: token.$crm-success; font-size: 12px; line-height: 20px; .fail { color: token.$crm-danger; } }
.inquiry-quote-form { margin-top: 0; }
.inquiry-form-grid.inquiry-quote-grid { grid-template-columns: 180px minmax(0,1fr); }
.inquiry-quote-hint { margin-top: 12px; }
.inquiry-existing-quote { display: flex; justify-content: space-between; gap: 12px; align-items: center; }
</style>
