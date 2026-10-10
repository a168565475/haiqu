<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { bulkReassign, previewBulkReassign } from '@/api/tasks'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { TaskBatchPreview, TaskOptions, TaskSummary } from '@/types/task'
import { createClientUuid } from '@/utils/clientUuid'
import { taskRequestMessage } from '@/utils/taskFeedback'

const props = defineProps<{ modelValue: boolean; tasks: TaskSummary[]; options: TaskOptions | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; completed: [count: number] }>()
const assigneeId = ref('')
const reason = ref('')
const preview = ref<TaskBatchPreview | null>(null)
const previewing = ref(false)
const submitting = ref(false)
const eventId = ref('')
const items = computed(() => props.tasks.map(task => ({ id: task.id, version: task.business_version })))

watch(() => props.modelValue, (visible) => {
  if (!visible) return
  assigneeId.value = ''
  reason.value = ''
  preview.value = null
  eventId.value = createClientUuid()
})
async function updatePreview() {
  if (!assigneeId.value) { preview.value = null; return }
  eventId.value = createClientUuid()
  previewing.value = true
  try { preview.value = await previewBulkReassign(items.value, assigneeId.value, eventId.value) }
  catch (error) { preview.value = null; ElMessage.error(taskRequestMessage(error)) }
  finally { previewing.value = false }
}
function close() { if (!submitting.value) emit('update:modelValue', false) }
async function submit() {
  if (submitting.value) return
  if (!assigneeId.value) return ElMessage.warning('请选择新负责人。')
  if (!preview.value) return ElMessage.warning('请等待影响预览完成。')
  submitting.value = true
  try {
    const result = await bulkReassign(items.value, assigneeId.value, reason.value.trim(), eventId.value)
    emit('completed', result.count)
    emit('update:modelValue', false)
    ElMessage.success(`已转交 ${result.count} 条任务。`)
  } catch (error) { ElMessage.error(taskRequestMessage(error)) }
  finally { submitting.value = false }
}
</script>

<template>
  <AppWindowDialog class="task-operation-dialog task-bulk-reassign-dialog" :model-value="modelValue" title="批量转交任务" :width="984" :height="604" destroy-on-close :close-on-click-modal="!submitting" :close-on-press-escape="!submitting" :show-close="!submitting" @update:model-value="value => { if (!value) close() }">
    <div class="bulk-reassign-body">
      <p class="selected-count">已选择 {{ tasks.length }} 条任务</p>
      <div class="bulk-reassign-grid">
        <div class="selected-table"><div class="selected-head"><span>任务标题</span><span>客户</span><span>原负责人</span></div><div v-for="task in tasks" :key="task.id" class="selected-row"><span><strong>{{ task.title }}</strong><small>{{ task.task_number }}</small></span><span>{{ task.customer?.name || '—' }}</span><span>{{ task.assignee.display_name }}</span></div></div>
        <el-form label-position="top" :disabled="submitting"><el-form-item label="新负责人" required><el-select v-model="assigneeId" filterable placeholder="请选择新负责人" @change="updatePreview"><el-option v-for="item in options?.assignees" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" /></el-select></el-form-item><el-form-item label="说明（选填）"><el-input v-model="reason" type="textarea" :rows="6" maxlength="500" show-word-limit /></el-form-item><p v-if="previewing">正在核对所选任务…</p></el-form>
      </div>
      <p class="summary">将 {{ preview?.task_count ?? tasks.length }} 条任务转交给 <strong>{{ options?.assignees.find(item => item.id === assigneeId)?.name || '待选择负责人' }}</strong></p>
    </div>
    <template #footer><el-button :disabled="submitting" @click="close">取消</el-button><el-button type="primary" :loading="submitting" :disabled="previewing || !preview" @click="submit">确认转交 {{ preview?.task_count ?? tasks.length }} 条</el-button></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.bulk-reassign-body{min-height:452px;margin:-30px;padding:24px 28px;background:#fbfaf6}.selected-count{height:38px;display:flex;align-items:center;margin:0 0 14px;padding:0 14px;background:#f3f0e9;font-size:15px}.bulk-reassign-grid{display:grid;grid-template-columns:1.2fr .8fr;gap:24px}.selected-table{overflow:hidden;border:1px solid #e7e2dc;border-radius:5px}.selected-head,.selected-row{display:grid;grid-template-columns:1.5fr 1fr 92px;align-items:center;padding:0 14px}.selected-head{height:44px;background:#eee9e0;color:#555;font-size:13px}.selected-row{min-height:68px;border-top:1px solid #e7e2dc;font-size:13px}.selected-row strong,.selected-row small{display:block}.selected-row small{color:#858585}.bulk-reassign-grid :deep(.el-select){width:100%}.bulk-reassign-grid :deep(.el-input__wrapper),.bulk-reassign-grid :deep(.el-textarea__inner){background:#fefefd;box-shadow:0 0 0 1px #e7e2dc inset}.summary{margin:28px 0 0;color:#3a373b;font-size:15px}.summary strong{color:#c7441d}
</style>
