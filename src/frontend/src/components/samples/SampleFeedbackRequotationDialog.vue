<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, reactive, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'

import {
  createSampleFeedbackRequotation,
  fetchSampleFeedbackRequotationOptions,
} from '@/api/samples'
import type { SampleFeedback, SampleRequotationOption } from '@/types/sample'

const props = defineProps<{
  sampleId: string
  sampleNumber: string
  customerName: string
  sampleEtag: string
  feedback: SampleFeedback | null
  canCreateQuotation: boolean
}>()
const emit = defineEmits<{
  created: [quotationId: string, sampleEtag: string, versionId: string]
}>()
const visible = defineModel<boolean>({ required: true })
const loading = ref(false)
const submitting = ref(false)
const loadError = ref('')
let loadSequence = 0
const options = ref<SampleRequotationOption[]>([])
const form = reactive({ sourceVersionId: '', validUntil: '', notes: '' })

const selected = computed(() => options.value.find((item) => item.version_id === form.sourceVersionId) || null)
const blockedByQuotationPermission = computed(() => (
  selected.value?.target_mode === 'CREATE_QUOTATION' && !props.canCreateQuotation
))

function defaultValidUntil() {
  const date = new Date()
  date.setDate(date.getDate() + 30)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function errorText(error: unknown): string {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  if (!error.response) return '网络异常，请检查连接后重试。'
  const data = error.response.data as { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string }
  const fieldError = Object.values(data.error?.field_errors || {}).flat()[0]
  if (error.response.status === 403) return '当前账号缺少报价查看、版本创建或报价建档权限。'
  if (error.response.status === 412) return '样品数据已被其他人更新，请刷新后重试。'
  return fieldError || data.error?.message || data.detail || '创建再报价失败。'
}

async function loadOptions() {
  if (!props.feedback) return
  const sequence = ++loadSequence
  loading.value = true
  loadError.value = ''
  options.value = []
  form.sourceVersionId = ''
  form.validUntil = defaultValidUntil()
  form.notes = props.feedback.corrective_action_request || props.feedback.rejection_reason || ''
  try {
    const result = await fetchSampleFeedbackRequotationOptions(props.sampleId, props.feedback.id)
    if (sequence !== loadSequence || !visible.value) return
    options.value = result.data
    const recommended = result.data.find((item) => item.is_sample_source) || result.data[0]
    form.sourceVersionId = recommended?.version_id || ''
  } catch (error) {
    if (sequence === loadSequence && visible.value) loadError.value = errorText(error)
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

async function submit() {
  if (loading.value || submitting.value || loadError.value) return
  if (!props.sampleEtag) return ElMessage.warning('缺少数据版本，请刷新样品后重试。')
  if (!props.feedback || !form.sourceVersionId) return ElMessage.warning('请选择一份同客户历史报价版本。')
  if (!selected.value) return ElMessage.warning('复制来源已失效，请重新选择。')
  if (!form.validUntil) return ElMessage.warning('请选择报价有效期。')
  if (blockedByQuotationPermission.value) return ElMessage.warning('来源报价已终态，需要报价建档权限才能创建新报价。')
  submitting.value = true
  try {
    const result = await createSampleFeedbackRequotation(
      props.sampleId,
      props.feedback.id,
      {
        source_quotation_version_id: form.sourceVersionId,
        valid_until: form.validUntil,
        notes: form.notes.trim(),
      },
      props.sampleEtag,
    )
    visible.value = false
    ElMessage.success(result.data.replayed ? '已打开这条反馈生成的再报价。' : `已创建 ${result.data.quotation_number} V${result.data.version_number} 草稿。`)
    emit('created', result.data.quotation_id, result.etag, result.data.quotation_version_id)
  } catch (error) {
    ElMessage.error(errorText(error))
  } finally {
    submitting.value = false
  }
}

watch(visible, (value) => { if (value) void loadOptions(); else { loadSequence++; loading.value = false } }, { immediate: true })
</script>

<template>
  <ElDialog draggable align-center v-model="visible" class="sample-requotation-dialog" title="从样品反馈创建再报价" width="720px" :close-on-click-modal="false" :close-on-press-escape="!submitting" :show-close="!submitting" destroy-on-close>
    <div v-loading="loading" class="requote-dialog">
      <p class="requote-intro">反馈、复制来源与新报价版本均保留可追溯关系。</p>
      <section class="feedback-source">
        <div><span>来源样品</span><b>{{ sampleNumber }} · {{ customerName }}</b></div>
        <div><span>客户反馈</span><b>{{ feedback?.confirmation_result_display || '—' }}</b></div>
        <p>{{ feedback?.feedback_content || '暂无反馈内容' }}</p>
        <small v-if="feedback?.corrective_action_request">整改要求：{{ feedback.corrective_action_request }}</small>
      </section>

      <section class="history-section">
        <h3>选择同客户历史报价作为复制基准</h3>
        <div v-if="loadError" class="requote-error" role="alert">{{ loadError }}<ElButton :disabled="loading" @click="loadOptions">重新加载</ElButton></div>
        <ElRadioGroup v-else-if="options.length" v-model="form.sourceVersionId" :disabled="submitting" class="quote-options">
          <ElRadio v-for="item in options" :key="item.version_id" :value="item.version_id" border>
            <span class="option-main"><b>{{ item.quotation_number }} V{{ item.version_number }}</b><em v-if="item.is_sample_source">样品来源</em></span>
            <span>{{ item.subject }} · {{ item.currency_code }} · {{ item.version_status }}</span>
          </ElRadio>
        </ElRadioGroup>
        <ElEmpty v-else :image-size="44" description="该客户暂无可复制的历史报价版本" />
      </section>

      <ElForm label-position="top" class="requote-form" :disabled="submitting || loading">
        <div class="form-grid">
          <ElFormItem label="目标报价">
            <ElInput :model-value="selected?.target_label || '请先选择复制来源'" readonly />
          </ElFormItem>
          <ElFormItem label="报价有效期" required>
            <ElDatePicker v-model="form.validUntil" type="date" value-format="YYYY-MM-DD" :clearable="false" />
          </ElFormItem>
        </div>
        <details class="requote-notes"><summary>带入新报价的反馈说明</summary><ElInput v-model="form.notes" type="textarea" :rows="2" maxlength="2000" show-word-limit /></details>
      </ElForm>

      <ElAlert
        v-if="blockedByQuotationPermission"
        title="来源报价已终态；当前账号缺少报价建档权限，不能创建新的报价 V1。"
        type="warning"
        :closable="false"
        show-icon
      />
      <ElAlert
        v-else
        title="进行中的来源报价会生成下一个版本；已接受、失单或取消的报价不会被重开，而是新建报价 V1。历史报价永不覆盖。"
        type="info"
        :closable="false"
        show-icon
      />
    </div>
    <template #footer>
      <ElButton :disabled="submitting" @click="visible = false">取消</ElButton>
      <ElButton type="primary" :loading="submitting" :disabled="loading || submitting || Boolean(loadError) || !options.length || blockedByQuotationPermission" @click="submit">创建报价草稿</ElButton>
    </template>
  </ElDialog>
</template>

<style scoped lang="scss" src="./sampleFeedbackRequotation.scss"></style>
<style lang="scss">
@use '@/styles/crm/sample-dialog' as dialog;
.sample-requotation-dialog { @include dialog.dialog; }
.sample-requotation-dialog.el-dialog.is-draggable { margin: auto; }
</style>
