<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { postTaskAction } from '@/api/tasks'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { TaskDetail, TaskOptions } from '@/types/task'
import { taskRequestMessage } from '@/utils/taskFeedback'

const props = defineProps<{ modelValue: boolean; task: TaskDetail | null; etag: string | null; options: TaskOptions | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; updated: [task: TaskDetail, etag: string | null] }>()
const submitting = ref(false)
const form = reactive({ assignee_employee_id: '', reason: '' })

watch(() => props.modelValue, (visible) => {
  if (!visible || !props.task) return
  form.assignee_employee_id = ''
  form.reason = ''
})

function close() {
  if (!submitting.value) emit('update:modelValue', false)
}

async function submit() {
  if (submitting.value) return
  if (!form.assignee_employee_id) return ElMessage.warning('请选择新负责人。')
  if (!form.reason.trim()) return ElMessage.warning('请填写转交说明。')
  if (!props.task || !props.etag) return ElMessage.warning('缺少任务版本信息，请刷新页面。')
  submitting.value = true
  try {
    const result = await postTaskAction(props.task.id, 'reassign', {
      assignee_employee_id: form.assignee_employee_id,
      reason: form.reason.trim(),
    }, props.etag)
    emit('updated', result.data, result.etag)
    emit('update:modelValue', false)
    ElMessage.success('任务已转交。')
  } catch (error) {
    ElMessage.error(taskRequestMessage(error))
  } finally { submitting.value = false }
}
</script>

<template>
  <AppWindowDialog class="task-operation-dialog task-reassign-dialog" :model-value="modelValue" title="转交任务" :width="930" :height="646" destroy-on-close :close-on-click-modal="!submitting" :close-on-press-escape="!submitting" :show-close="!submitting" @update:model-value="value => { if (!value) close() }">
    <div v-if="task" class="reassign-layout">
      <section class="task-summary">
        <dl>
          <div><dt>任务标题</dt><dd>{{ task.title }}</dd></div>
          <div><dt>任务编号</dt><dd>{{ task.task_number }}</dd></div>
          <div><dt>关联客户</dt><dd>{{ task.customer?.name || '—' }}</dd></div>
          <div><dt>当前负责人</dt><dd>{{ task.assignee.display_name }}</dd></div>
        </dl>
      </section>
      <el-form label-position="top" class="operation-form" :disabled="submitting">
        <h3>负责人交接</h3>
        <div class="people-flow"><span><i>{{ task.assignee.display_name.slice(0, 1) }}</i>{{ task.assignee.display_name }}<small>当前负责人</small></span><b>→</b><span><i class="next">{{ options?.assignees.find(item => item.id === form.assignee_employee_id)?.name.slice(0, 1) || '新' }}</i>{{ options?.assignees.find(item => item.id === form.assignee_employee_id)?.name || '待选择' }}<small>新负责人</small></span></div>
        <el-form-item label="新负责人" required><el-select v-model="form.assignee_employee_id" filterable placeholder="请选择新负责人"><el-option v-for="item in options?.assignees" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="转交说明" required><el-input v-model="form.reason" type="textarea" :rows="4" maxlength="500" show-word-limit /></el-form-item>
      </el-form>
    </div>
    <template #footer><el-button :disabled="submitting" @click="close">取消</el-button><el-button type="primary" :loading="submitting" @click="submit">确认转交</el-button></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.reassign-layout{height:494px;display:grid;grid-template-columns:350px 1fr;margin:-30px}.task-summary{padding:36px 34px;background:#f6f4ef}.task-summary dl{margin:0}.task-summary div{margin-bottom:24px}.task-summary dt{color:#595551;font-size:14px}.task-summary dd{margin:7px 0 0;color:#090a0b;font-size:15px;line-height:24px}.operation-form{padding:30px 34px}.operation-form h3{margin:0 0 24px;font-size:20px}.people-flow{height:92px;display:flex;align-items:center;justify-content:center;gap:38px;margin-bottom:22px}.people-flow span{min-width:100px;display:flex;align-items:center;flex-direction:column;color:#242424;font-size:14px}.people-flow i{width:38px;height:38px;display:grid;place-items:center;margin-bottom:6px;border-radius:50%;color:#fff;background:#d5ad8d;font-style:normal}.people-flow i.next{background:#c7441d}.people-flow small{color:#858585}.people-flow b{font-size:24px;font-weight:400}.operation-form :deep(.el-select){width:100%}.operation-form :deep(.el-input__wrapper),.operation-form :deep(.el-textarea__inner){background:#fefefe;box-shadow:0 0 0 1px #e2ddd7 inset}.operation-form :deep(.el-form-item__label){color:#090a0b;font-size:14px}
</style>
