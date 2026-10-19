<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'

import { createTask, fetchTaskOptions } from '@/api/tasks'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { TaskDetail, TaskOptions, TaskScope } from '@/types/task'

const props = withDefaults(defineProps<{
  modelValue: boolean
  embedded?: boolean
  scope?: TaskScope
  options?: TaskOptions | null
  fixedCustomerId?: string
  fixedCustomerName?: string
  defaultAssigneeId?: string
  fixedInquiryId?: string
  fixedInquiryNumber?: string
}>(), {
  embedded: false,
  scope: 'ME',
  options: null,
  fixedCustomerId: '',
  fixedCustomerName: '',
  defaultAssigneeId: '',
  fixedInquiryId: '',
  fixedInquiryNumber: '',
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  created: [task: TaskDetail]
}>()

const submitting = ref(false)
const loadingOptions = ref(false)
const availableOptions = ref<TaskOptions | null>(props.options)
const form = reactive({
  title: '',
  description: '',
  assignee_employee_id: '',
  task_type: 'OTHER',
  priority: 'NORMAL',
  due_at: '',
})

function apiError(error: unknown): string {
  if (!(error instanceof AxiosError)) return '任务创建失败，请稍后重试。'
  if (!error.response) return '网络连接异常，请检查后端服务。'
  const body = error.response.data as { detail?: string; error?: { message?: string; field_errors?: Record<string, string[]> } }
  const fieldError = body.error?.field_errors ? Object.values(body.error.field_errors).flat()[0] : undefined
  if (error.response.status === 403) return '当前账号没有创建该客户任务的权限。'
  return fieldError || body.error?.message || body.detail || '任务创建失败，请检查填写内容。'
}

function resetForm() {
  Object.assign(form, {
    title: '',
    description: '',
    assignee_employee_id: props.defaultAssigneeId,
    task_type: 'OTHER',
    priority: 'NORMAL',
    due_at: '',
  })
}

async function ensureOptions() {
  if (props.options) {
    availableOptions.value = props.options
    return
  }
  loadingOptions.value = true
  try {
    availableOptions.value = await fetchTaskOptions(props.scope)
  } catch (error) {
    availableOptions.value = null
    ElMessage.error(apiError(error))
  } finally {
    loadingOptions.value = false
  }
}

function close() {
  if (submitting.value) return
  emit('update:modelValue', false)
}

async function submit() {
  if (submitting.value || loadingOptions.value || !availableOptions.value) return
  if (!form.title.trim()) return ElMessage.warning('请填写任务标题。')
  if (!form.assignee_employee_id) return ElMessage.warning('请选择负责人。')
  if (form.due_at && Number.isNaN(new Date(form.due_at).getTime())) return ElMessage.warning('截止时间格式无效。')
  submitting.value = true
  try {
    const task = await createTask({
      ...form,
      title: form.title.trim(),
      description: form.description.trim(),
      due_at: form.due_at ? new Date(form.due_at).toISOString() : null,
      ...(props.fixedInquiryId ? { source_type: 'INQUIRY', source_id: props.fixedInquiryId } : props.fixedCustomerId ? { source_type: 'CUSTOMER', source_id: props.fixedCustomerId } : {}),
    })
    ElMessage.success('任务已创建。')
    emit('created', task)
    emit('update:modelValue', false)
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    submitting.value = false
  }
}

watch(() => props.options, value => { if (value) availableOptions.value = value }, { immediate: true })
watch(() => props.modelValue, async value => {
  if (!value) return
  resetForm()
  await ensureOptions()
})
</script>

<template>
  <AppWindowDialog :model-value="modelValue" title="新建任务" :width="984" height="auto" :class="embedded ? 'task-create-dialog--embedded' : 'task-operation-dialog task-create-dialog'" destroy-on-close :close-on-click-modal="!submitting" :close-on-press-escape="!submitting" :show-close="!submitting" @update:model-value="value => { if (!value) close() }">
    <ElForm v-loading="loadingOptions" label-position="top" :disabled="submitting" class="create-layout" :class="{ 'create-layout--embedded': embedded }">
      <section class="edit-column">
        <h3>编辑任务</h3>
        <ElFormItem v-if="fixedInquiryId" label="关联询盘"><ElInput :model-value="fixedInquiryNumber || fixedInquiryId" disabled /></ElFormItem>
        <ElFormItem v-if="fixedCustomerId" label="关联客户"><ElInput :model-value="fixedCustomerName || fixedCustomerId" disabled /></ElFormItem>
        <ElFormItem label="任务标题" required><ElInput v-model="form.title" maxlength="250" /></ElFormItem>
        <ElFormItem label="说明"><ElInput v-model="form.description" type="textarea" :rows="7" maxlength="2000" show-word-limit /></ElFormItem>
      </section>
      <section class="schedule-column">
        <h3>安排任务</h3>
        <ElFormItem label="负责人" required><ElSelect v-model="form.assignee_employee_id" filterable><ElOption v-for="item in availableOptions?.assignees" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" /></ElSelect></ElFormItem>
        <ElFormItem label="任务类型"><ElSelect v-model="form.task_type"><ElOption v-for="item in availableOptions?.task_types" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></ElFormItem>
        <ElFormItem label="优先级"><ElSelect v-model="form.priority"><ElOption v-for="item in availableOptions?.priorities" :key="item.value" :label="item.label" :value="item.value" /></ElSelect></ElFormItem>
        <ElFormItem label="截止时间"><ElDatePicker v-model="form.due_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></ElFormItem>
      </section>
    </ElForm>
    <template #footer>
      <ElButton :class="{ 'erp-button-motion': embedded }" :disabled="submitting" @click="close">取消</ElButton>
      <ElButton :class="{ 'erp-button-motion': embedded }" type="primary" :loading="submitting" :disabled="loadingOptions || !availableOptions" @click="submit">创建任务</ElButton>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.create-layout:not(.create-layout--embedded){height:auto;display:grid;grid-template-columns:1.15fr .85fr}.create-layout:not(.create-layout--embedded)>section{box-sizing:border-box;padding:28px 34px}.create-layout:not(.create-layout--embedded) h3{margin:0 0 22px;color:var(--erp-color-text-primary);font-size:20px;line-height:30px}.create-layout:not(.create-layout--embedded) .edit-column{background:var(--erp-color-surface)}.create-layout:not(.create-layout--embedded) .schedule-column{border-left:1px solid var(--erp-color-border);background:var(--erp-color-subtle)}.create-layout:not(.create-layout--embedded) :deep(.el-select),.create-layout:not(.create-layout--embedded) :deep(.el-date-editor){width:100%}.create-layout:not(.create-layout--embedded) :deep(.el-form-item__label){color:var(--erp-color-text-primary);font-size:14px}.create-layout:not(.create-layout--embedded) :deep(.el-input__wrapper),.create-layout:not(.create-layout--embedded) :deep(.el-select__wrapper),.create-layout:not(.create-layout--embedded) :deep(.el-textarea__inner){background:var(--erp-input-background);box-shadow:0 0 0 1px var(--erp-color-border) inset}.create-layout:not(.create-layout--embedded) :deep(.el-form-item){margin-bottom:18px}.create-layout:not(.create-layout--embedded) :deep(.el-textarea__inner){min-height:220px!important}

.create-layout.create-layout--embedded {
  display: grid;
  grid-template-columns: 1.15fr .85fr;
  height: auto;
  gap: 14px;
  font-size: 13px;
  line-height: 20px;

  > section { min-width: 0; padding: 16px; border: 1px solid var(--erp-color-border); border-radius: 6px; background: var(--erp-color-surface); }
  h3 { margin: 0 0 14px; font-size: 16px; line-height: 24px; }
  :deep(.el-select), :deep(.el-date-editor) { width: 100%; }
  :deep(.el-form-item__label) { color: var(--erp-color-text-primary); font-size: 13px; }
  :deep(.el-form-item:last-child) { margin-bottom: 0; }
}
@container (max-width: 680px) { .create-layout.create-layout--embedded { grid-template-columns: 1fr; } }
</style>

<style lang="scss">
.task-create-dialog--embedded.app-window-dialog.el-dialog {
  container-type: inline-size;

  .app-window-dialog__body { padding: 16px; }
  .app-window-dialog__footer { padding: 12px 16px; background: transparent; }
  .app-window-dialog__footer .el-button { border-radius: var(--erp-radius-control); font-size: 13px; }
}
</style>
