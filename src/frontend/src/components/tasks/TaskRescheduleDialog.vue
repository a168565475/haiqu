<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { postTaskAction, previewTaskReschedule } from '@/api/tasks'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { TaskDetail } from '@/types/task'
import { formatTaskDate, taskRequestMessage } from '@/utils/taskFeedback'

const props = defineProps<{ modelValue: boolean; task: TaskDetail | null; etag: string | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; updated: [task: TaskDetail, etag: string | null] }>()
const submitting = ref(false)
const previewing = ref(false)
const preview = ref<{ warning: boolean; conflict_count: number } | null>(null)
const form = reactive({ new_due_at: '', reason: '', sync_reminders: true })

watch(() => props.modelValue, (visible) => {
  if (!visible) return
  Object.assign(form, { new_due_at: '', reason: '', sync_reminders: true })
  preview.value = null
})

function close() { if (!submitting.value) emit('update:modelValue', false) }
function isoDate() {
  const date = new Date(form.new_due_at)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}
async function loadPreview() {
  const date = isoDate()
  if (!props.task || !date || !form.reason.trim()) { preview.value = null; return }
  previewing.value = true
  try { preview.value = await previewTaskReschedule(props.task.id, { new_due_at: date, reason: form.reason.trim(), sync_reminders: form.sync_reminders }) }
  catch (error) { preview.value = null; ElMessage.error(taskRequestMessage(error)) }
  finally { previewing.value = false }
}
async function submit() {
  if (submitting.value) return
  const date = isoDate()
  if (!date) return ElMessage.warning('请选择有效的新截止时间。')
  if (!form.reason.trim()) return ElMessage.warning('请填写改期原因。')
  if (!props.task || !props.etag) return ElMessage.warning('缺少任务版本信息，请刷新页面。')
  submitting.value = true
  try {
    const result = await postTaskAction(props.task.id, 'reschedule', { new_due_at: date, reason: form.reason.trim(), sync_reminders: form.sync_reminders }, props.etag)
    emit('updated', result.data, result.etag)
    emit('update:modelValue', false)
    ElMessage.success('任务截止时间已更新。')
  } catch (error) { ElMessage.error(taskRequestMessage(error)) }
  finally { submitting.value = false }
}
</script>

<template>
  <AppWindowDialog class="task-operation-dialog task-reschedule-dialog" :model-value="modelValue" title="改期任务" :width="820" :height="698" destroy-on-close :close-on-click-modal="!submitting" :close-on-press-escape="!submitting" :show-close="!submitting" @update:model-value="value => { if (!value) close() }">
    <div v-if="task" class="reschedule-body">
      <h3>{{ task.title }}</h3><p>{{ task.task_number }}　·　负责人：{{ task.assignee.display_name }}　·　{{ task.task_type_display }}</p>
      <el-form label-position="top" :disabled="submitting">
        <div class="date-compare"><el-form-item label="原截止时间（只读）"><el-input :model-value="formatTaskDate(task.due_at)" disabled /></el-form-item><b>→</b><el-form-item label="新的截止时间" required><el-date-picker v-model="form.new_due_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" @change="loadPreview" /></el-form-item></div>
        <el-form-item label="改期原因" required><el-input v-model="form.reason" type="textarea" :rows="4" maxlength="500" show-word-limit @blur="loadPreview" /></el-form-item>
        <el-checkbox v-model="form.sync_reminders" @change="loadPreview">同步平移待执行提醒</el-checkbox>
        <p class="help">改期后，相关待执行提醒将按相同时间间隔同步调整。</p>
        <el-alert v-if="preview?.warning" type="warning" :closable="false" :title="`同一负责人在该小时内有 ${preview.conflict_count} 条高/紧急任务到期，仅作提醒，不阻止改期。`" />
        <p v-else-if="previewing" class="help">正在检查时间冲突…</p>
      </el-form>
    </div>
    <template #footer><el-button :disabled="submitting" @click="close">取消</el-button><el-button type="primary" :loading="submitting" @click="submit">确认改期</el-button></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.reschedule-body{min-height:546px;margin:-30px;padding:30px 34px;background:#faf9f5}.reschedule-body h3{margin:0 0 4px;font-size:20px}.reschedule-body>p{margin:0 0 28px;color:#6f6f6f;font-size:13px}.date-compare{display:grid;grid-template-columns:1fr 32px 1fr;gap:16px;align-items:center}.date-compare b{text-align:center;font-size:24px;font-weight:400}.reschedule-body :deep(.el-date-editor){width:100%}.reschedule-body :deep(.el-input__wrapper),.reschedule-body :deep(.el-textarea__inner){background:#fdfbf9;box-shadow:0 0 0 1px #e6e2dd inset}.date-compare :deep(.is-disabled .el-input__wrapper){background:#f5f4f0}.reschedule-body :deep(.el-form-item__label){color:#000;font-size:14px}.help{margin:8px 0 16px!important;color:#858585!important;font-size:13px!important}
</style>
