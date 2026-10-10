<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { bulkComplete, previewBulkComplete } from '@/api/tasks'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { TaskBatchPreview, TaskSummary } from '@/types/task'
import { createClientUuid } from '@/utils/clientUuid'
import { taskRequestMessage } from '@/utils/taskFeedback'

const props = defineProps<{ modelValue: boolean; tasks: TaskSummary[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; completed: [count: number] }>()
const loading = ref(false)
const submitting = ref(false)
const reason = ref('')
const preview = ref<TaskBatchPreview | null>(null)
const eventId = ref('')
const items = computed(() => props.tasks.map(task => ({ id: task.id, version: task.business_version })))

watch(() => props.modelValue, async (visible) => {
  if (!visible) return
  reason.value = ''
  preview.value = null
  eventId.value = createClientUuid()
  loading.value = true
  try { preview.value = await previewBulkComplete(items.value, eventId.value) }
  catch (error) { ElMessage.error(taskRequestMessage(error)) }
  finally { loading.value = false }
})

function close() { if (!submitting.value) emit('update:modelValue', false) }
async function submit() {
  if (submitting.value || !items.value.length || !eventId.value) return
  submitting.value = true
  try {
    const result = await bulkComplete(items.value, reason.value.trim(), eventId.value)
    emit('completed', result.count)
    emit('update:modelValue', false)
    ElMessage.success(`已完成 ${result.count} 条任务。`)
  } catch (error) { ElMessage.error(taskRequestMessage(error)) }
  finally { submitting.value = false }
}
</script>

<template>
  <AppWindowDialog class="task-operation-dialog task-bulk-complete-dialog" :model-value="modelValue" title="批量完成任务" :width="1044" :height="674" destroy-on-close :close-on-click-modal="!submitting" :close-on-press-escape="!submitting" :show-close="!submitting" @update:model-value="value => { if (!value) close() }">
    <div class="bulk-layout" v-loading="loading">
      <section><h3>已选择 {{ tasks.length }} 条任务</h3><div class="selected-table"><div class="selected-head"><span>任务标题</span><span>客户</span><span>当前状态</span><span>负责人</span></div><div v-for="task in tasks" :key="task.id" class="selected-row"><span><strong>{{ task.title }}</strong><small>{{ task.task_number }}</small></span><span>{{ task.customer?.name || '—' }}</span><span><i>{{ task.display_status }}</i></span><span>{{ task.assignee.display_name }}</span></div></div></section>
      <section class="impact"><h3>完成后将产生以下影响</h3><p>✓　将完成 <strong>{{ preview?.task_count ?? '—' }}</strong> 条任务</p><p>♙　涉及 <strong>{{ preview?.customer_count ?? '—' }}</strong> 个客户</p><p>!　其中 <strong>{{ preview?.overdue_count ?? '—' }}</strong> 条已逾期</p><p>◷　关闭 <strong>{{ preview?.scheduled_reminder_count ?? '—' }}</strong> 条待执行提醒</p><label>说明（选填）<el-input v-model="reason" type="textarea" :rows="4" maxlength="500" show-word-limit /></label></section>
    </div>
    <template #footer><el-button :disabled="submitting" @click="close">取消</el-button><el-button type="primary" :loading="submitting" :disabled="loading || !preview" @click="submit">确认完成 {{ preview?.task_count ?? tasks.length }} 条</el-button></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.bulk-layout{height:522px;display:grid;grid-template-columns:1.15fr .85fr;margin:-30px}.bulk-layout>section{padding:28px 32px}.bulk-layout>section+section{border-left:1px solid #e7e2dc;background:#f5f3ee}.bulk-layout h3{margin:0 0 18px;font-size:19px}.selected-table{overflow:hidden;border:1px solid #e7e2dc;border-radius:5px}.selected-head,.selected-row{display:grid;grid-template-columns:1.5fr 1fr 90px 90px;align-items:center}.selected-head{height:44px;padding:0 14px;background:#eee9e0;color:#555;font-size:13px}.selected-row{min-height:64px;padding:0 14px;border-top:1px solid #e7e2dc;font-size:13px}.selected-row strong,.selected-row small{display:block}.selected-row small{color:#858585}.selected-row i{padding:4px 10px;border-radius:999px;color:#fff;background:#b8781e;font-style:normal}.impact p{margin:18px 0;color:#272725;font-size:15px}.impact strong{color:#c7441d;font-size:20px}.impact label{display:flex;flex-direction:column;gap:8px;margin-top:24px;color:#272725;font-size:14px}.impact :deep(.el-textarea__inner){background:#fcfbf9;box-shadow:0 0 0 1px #e7e2dc inset}
</style>
