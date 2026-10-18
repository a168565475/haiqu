<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { updateComplaintProgress, uploadComplaintImage } from '@/api/complaints'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { Complaint, ComplaintOptions, ComplaintProgressInput, ComplaintStatus } from '@/types/complaint'
import { complaintDate, complaintRequestMessage, validateComplaintImages } from '@/utils/complaintFeedback'

const props = defineProps<{
  modelValue: boolean
  complaint: Complaint | null
  etag: string | null
  options: ComplaintOptions | null
  canClose: boolean
  initialTarget?: ComplaintStatus | null
}>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; updated: [complaint: Complaint, etag: string | null] }>()
const submitting = ref(false)
const retrying = ref(false)
const files = ref<File[]>([])
const failedFiles = ref<File[]>([])
const savedProgressId = ref<string | null>(null)
const savedComplaint = ref<Complaint | null>(null)
const errorMessage = ref('')
const form = reactive<ComplaintProgressInput>({ to_status: 'ACCEPTED', progress_note: '', root_cause: '', responsibility: '', solution: '', customer_feedback: '' })
const nextStatus = computed<ComplaintStatus>(() => {
  const map: Partial<Record<ComplaintStatus, ComplaintStatus>> = {
    ACCEPTED: 'RESPONSIBILITY_CONFIRMATION', RESPONSIBILITY_CONFIRMATION: 'SOLUTION_PLANNING',
    SOLUTION_PLANNING: 'CUSTOMER_CONFIRMATION', CUSTOMER_CONFIRMATION: 'CLOSED',
  }
  return map[props.complaint?.status || 'ACCEPTED'] || (props.complaint?.status as ComplaintStatus) || 'ACCEPTED'
})
const allowedStatuses = computed(() => new Set<ComplaintStatus>([
  props.complaint?.status || 'ACCEPTED', nextStatus.value, 'CANCELLED',
]))

watch(() => props.modelValue, visible => {
  if (!visible || !props.complaint) return
  Object.assign(form, {
    to_status: props.initialTarget || nextStatus.value,
    progress_note: '', root_cause: props.complaint.root_cause, responsibility: props.complaint.responsibility,
    solution: props.complaint.solution, customer_feedback: props.complaint.customer_feedback,
  })
  files.value = []
  failedFiles.value = []
  savedProgressId.value = null
  savedComplaint.value = null
  errorMessage.value = ''
})

function selectImages(event: Event) {
  const input = event.target as HTMLInputElement
  const selected = Array.from(input.files || [])
  const validation = validateComplaintImages(selected)
  if (validation) {
    ElMessage.warning(validation)
    input.value = ''
    return
  }
  files.value = selected
  failedFiles.value = []
}

async function uploadFiles(targets: File[]) {
  if (!props.complaint) return targets
  const failures: File[] = []
  for (const file of targets) {
    try { await uploadComplaintImage(props.complaint.id, file, savedProgressId.value) }
    catch { failures.push(file) }
  }
  return failures
}

async function submit() {
  if (submitting.value || savedComplaint.value) return
  if (!form.progress_note.trim()) return ElMessage.warning('请填写本次进展。')
  if (form.to_status === 'CLOSED' && !props.canClose) return ElMessage.warning('当前账号没有关闭客诉的权限。')
  if (!allowedStatuses.value.has(form.to_status)) return ElMessage.warning('客诉状态只能保持当前阶段、推进到下一阶段或取消。')
  if (!props.complaint || !props.etag) return ElMessage.warning('缺少记录版本，请刷新详情。')
  submitting.value = true
  errorMessage.value = ''
  try {
    const result = await updateComplaintProgress(props.complaint.id, { ...form, progress_note: form.progress_note.trim() }, props.etag)
    savedProgressId.value = result.progressId
    savedComplaint.value = result.data
    emit('updated', result.data, result.etag)
    failedFiles.value = await uploadFiles(files.value)
    if (failedFiles.value.length) {
      ElMessage.warning(`进展已保存，${failedFiles.value.length} 张图片上传失败，可立即重试。`)
    } else {
      ElMessage.success('客诉进展已更新。')
      emit('update:modelValue', false)
    }
  } catch (error) { errorMessage.value = complaintRequestMessage(error) }
  finally { submitting.value = false }
}

async function retryFailedImages() {
  if (!savedComplaint.value || !failedFiles.value.length || retrying.value) return
  retrying.value = true
  failedFiles.value = await uploadFiles(failedFiles.value)
  retrying.value = false
  if (failedFiles.value.length) return ElMessage.error(`仍有 ${failedFiles.value.length} 张图片上传失败，请检查网络后重试。`)
  ElMessage.success('失败图片已全部补传。')
  emit('update:modelValue', false)
}

function close() { if (!submitting.value && !retrying.value) emit('update:modelValue', false) }
</script>

<template>
  <AppWindowDialog class="complaint-operation-dialog complaint-progress-dialog" :model-value="modelValue" title="更新客诉进展" :width="1290" :height="792" destroy-on-close :close-on-click-modal="!submitting && !retrying" :close-on-press-escape="!submitting && !retrying" :show-close="!submitting && !retrying" @update:model-value="value => { if (!value) close() }">
    <div v-if="complaint" class="progress-body">
      <section class="context-column">
        <p class="code">{{ complaint.complaint_code }}</p><h3>{{ complaint.title }}</h3>
        <dl><div><dt>当前阶段</dt><dd>{{ complaint.status_label }}</dd></div><div><dt>负责人</dt><dd>{{ complaint.owner.display_name }}</dd></div><div><dt>客户</dt><dd>{{ complaint.customer.account_name }}</dd></div><div><dt>目标完成</dt><dd>{{ complaintDate(complaint.target_completion_at) }}</dd></div></dl>
        <article><strong>原始问题</strong><p>{{ complaint.issue_description }}</p></article>
        <article><strong>最近进展</strong><p>{{ complaint.progress_entries[0]?.progress_note || '暂无进展说明。' }}</p></article>
      </section>
      <section class="form-column">
        <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />
        <el-alert v-if="savedComplaint && failedFiles.length" :title="`进展已经保存，但有 ${failedFiles.length} 张图片上传失败；重试不会重复推进状态。`" type="warning" :closable="false" show-icon />
        <el-form label-position="top" :disabled="submitting || retrying || !!savedComplaint">
          <div class="two-columns"><el-form-item label="目标状态" required><el-select v-model="form.to_status"><el-option v-for="item in options?.statuses" :key="item.value" :label="item.label" :value="item.value" :disabled="!allowedStatuses.has(item.value) || (item.value === 'CLOSED' && !canClose)" /></el-select></el-form-item><el-form-item label="图片证据"><label class="compact-upload"><input type="file" multiple accept="image/jpeg,image/png,image/webp" @change="selectImages" /><span>选择图片（{{ files.length }}）</span></label></el-form-item></div>
          <el-form-item label="本次进展" required><el-input v-model="form.progress_note" type="textarea" :rows="4" maxlength="5000" show-word-limit /></el-form-item>
          <div class="two-columns"><el-form-item label="根本原因"><el-input v-model="form.root_cause" type="textarea" :rows="4" maxlength="5000" /></el-form-item><el-form-item label="责任归属"><el-input v-model="form.responsibility" type="textarea" :rows="4" maxlength="5000" /></el-form-item><el-form-item label="解决方案"><el-input v-model="form.solution" type="textarea" :rows="4" maxlength="5000" /></el-form-item><el-form-item label="客户反馈"><el-input v-model="form.customer_feedback" type="textarea" :rows="4" maxlength="5000" /></el-form-item></div>
          <div v-if="files.length" class="file-list"><span v-for="file in files" :key="`${file.name}-${file.size}`" :class="{ failed: failedFiles.includes(file) }">{{ file.name }}</span></div>
        </el-form>
      </section>
    </div>
    <template #footer><el-button :disabled="submitting || retrying" @click="close">{{ savedComplaint ? '稍后处理' : '取消' }}</el-button><el-button v-if="savedComplaint && failedFiles.length" type="primary" :loading="retrying" @click="retryFailedImages">重试失败图片</el-button><el-button v-else type="primary" :loading="submitting" :disabled="!!savedComplaint" @click="submit">保存进展</el-button></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
@use '@/styles/theme/detail' as detail;.progress-body { height: auto; display: grid; grid-template-columns: minmax(240px,.8fr) minmax(0,1.2fr); overflow: visible; margin: 0; background: transparent; gap: 14px; font-size: 13px; }.context-column, .form-column { overflow-y: visible; min-width: 0; }.context-column { @include detail.inset; padding: 16px; }.code { margin: 0; color: var(--erp-color-brand); font-size: 12px; font-weight: 700; letter-spacing: 1px; }.context-column h3 { margin: 7px 0 14px; font-size: 16px; line-height: 24px; font-family: var(--erp-font-body); }.context-column dl { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 0 0 14px; }.context-column dt { color: var(--erp-color-text-regular); font-size: 12px; }.context-column dd { margin: 5px 0 0; font-size: 13px; overflow-wrap: anywhere; }.context-column article { margin-top: 14px; padding: 14px; border: 1px solid var(--erp-color-border); background: var(--erp-color-subtle); border-radius: 8px; }.context-column article strong { font-size: 13px; }.context-column article p { margin: 7px 0 0; color: var(--erp-color-text-regular); font-size: 13px; line-height: 21px; }.form-column > :deep(.el-alert) { margin-bottom: 12px; }.two-columns { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 0 14px; }.form-column :deep(.el-select) { width: 100%; }.form-column :deep(.el-input__wrapper), .form-column :deep(.el-select__wrapper), .form-column :deep(.el-textarea__inner) { background: var(--erp-input-background); box-shadow: 0 0 0 1px var(--erp-color-border) inset; }.compact-upload { height: 42px; display: flex; align-items: center; padding: 0 14px; border: 1px dashed var(--erp-color-border); border-radius: 8px; color: var(--erp-color-brand); cursor: pointer; }.compact-upload input { display: none; }.file-list { display: flex; flex-wrap: wrap; gap: 6px; }.file-list span { padding: 5px 8px; border-radius: 3px; background: var(--erp-color-subtle); font-size: 12px; }.file-list span.failed { color: var(--erp-color-text-inverse); background: var(--erp-color-danger); }:global(.complaint-progress-dialog) { container-type:inline-size; }@container (max-width:740px) { .progress-body { grid-template-columns:minmax(0,1fr); } }@container (max-width:440px) { .two-columns { grid-template-columns:minmax(0,1fr); } }
</style>
