<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import axios from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { fetchFinanceSourceTasks, fetchFinanceStatements } from '@/api/financeStatements'
import type { FinanceSourceTask, FinanceStatement } from '@/types/financeStatements'

const props = defineProps<{ modelValue: boolean; mode: 'task' | 'statement'; taskId?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; task: [value: FinanceSourceTask]; statement: [value: FinanceStatement] }>()
const tasks = ref<FinanceSourceTask[]>([])
const statements = ref<FinanceStatement[]>([])
const q = ref(''); const page = ref(1); const total = ref(0); const loading = ref(false); const error = ref('')
let generation = 0
let controller: AbortController | undefined
async function load() {
  const request = ++generation; controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''
  try {
    if (props.mode === 'task') {
      const result = await fetchFinanceSourceTasks({ q: q.value, mode: 'receipt', page: page.value, page_size: 20 }, controller.signal)
      if (request !== generation) return
      tasks.value = result.data; total.value = result.meta.total
    } else {
      const result = await fetchFinanceStatements({ q: q.value, task_id: props.taskId, status: 'ACTIVE', page: page.value, page_size: 20 }, controller.signal)
      if (request !== generation) return
      statements.value = result.data; total.value = result.meta.total
    }
  } catch (err) { if (request === generation && !axios.isCancel(err)) {
    error.value = axios.isAxiosError(err) ? err.response?.data?.error?.message || '来源加载失败，请重试。' : '来源加载失败。'
    if (axios.isAxiosError(err) && err.response?.status === 403) { tasks.value = []; statements.value = []; total.value = 0 }
  } }
  finally { if (request === generation) loading.value = false }
}
watch(() => props.modelValue, value => { if (value) { tasks.value = []; statements.value = []; q.value = ''; page.value = 1; void load() } else { ++generation; controller?.abort() } })
onBeforeUnmount(() => { ++generation; controller?.abort() })
</script>

<template>
  <AppWindowDialog :model-value="modelValue" :title="mode === 'task' ? '选择生产任务' : '选择所属对账单'" :width="1080" :min-width="280" :minimizable="false" destroy-on-close modal-class="finance-receipt-overlay" @update:model-value="emit('update:modelValue', $event)">
    <div class="source-search"><el-input v-model="q" :placeholder="mode === 'task' ? '任务号、业务员' : '对账单号'" aria-label="搜索收款来源" @keyup.enter="page = 1; load()"/><el-button @click="page = 1; load()">查询</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <el-table v-if="mode === 'task'" v-loading="loading" :data="tasks" border><el-table-column prop="task_number" label="生产任务" min-width="150"/><el-table-column label="业务员" min-width="180"><template #default="{ row }">{{ row.salesperson.code }} / {{ row.salesperson.name }}</template></el-table-column><el-table-column prop="source_order_date" label="来源日期" min-width="120"/><el-table-column label="操作" width="80"><template #default="{ row }"><el-button link type="primary" :disabled="loading || !!error" @click="emit('task', row)">选择</el-button></template></el-table-column><template #empty>{{ error ? '任务加载失败' : '暂无包含有效对账单的任务，请先建立对账单' }}</template></el-table>
    <el-table v-else v-loading="loading" :data="statements" border><el-table-column prop="number" label="对账单号" min-width="180"/><el-table-column prop="task_number" label="生产任务" min-width="150"/><el-table-column prop="amount" label="对账金额" min-width="120" align="right"/><el-table-column prop="outstanding_amount" label="当前未付" min-width="120" align="right"/><el-table-column label="操作" width="80"><template #default="{ row }"><el-button link type="primary" :disabled="loading || !!error" @click="emit('statement', row)">选择</el-button></template></el-table-column><template #empty>{{ error ? '对账单加载失败' : '该任务暂无有效对账单' }}</template></el-table>
    <template #footer><el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load"/><el-button @click="emit('update:modelValue', false)">关闭</el-button></template>
  </AppWindowDialog>
</template>
<style scoped>.source-search{display:flex;gap:10px;margin-bottom:14px}.source-search .el-input{max-width:300px}</style>
