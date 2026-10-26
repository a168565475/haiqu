<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { isAxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import { createClientUuid } from '@/utils/clientUuid'
import { taskRequestMessage } from '@/utils/taskFeedback'
import { createProductionTaskExpense, fetchProductionTaskCostSummary, fetchProductionTaskExpenses, updateProductionTaskExpense, voidProductionTaskExpense } from '@/api/productionCosts'
import type { ProductionCostCategory, ProductionTaskCostSummary, ProductionTaskExpense, ProductionTaskExpenseInput } from '@/types/productionCost'

const props = defineProps<{ taskId: string }>()
const emit = defineEmits<{ 'busy-change': [busy: boolean] }>()
const authStore = useAuthStore()
const canView = computed(() => authStore.hasPermission('production_tasks.view_productiontaskcost'))
const canManage = computed(() => canView.value && authStore.hasPermission('production_tasks.manage_productiontaskexpense'))
const summary = ref<ProductionTaskCostSummary | null>(null)
const loading = ref(false)
const loadError = ref('')
const expanded = ref<string[]>([])
const expenses = ref<ProductionTaskExpense[]>([])
const expensesLoading = ref(false)
const expensesError = ref('')
const expensesLoaded = ref(false)
const dialogVisible = ref(false)
const editing = ref<ProductionTaskExpense | null>(null)
const saving = ref(false)
const voiding = ref('')
const formError = ref('')
const expenseTypes = { LOADING: '装卸费', TRANSPORT: '运输费', OTHER: '其他费用' }
function localToday() {
  const date = new Date()
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
const form = reactive<ProductionTaskExpenseInput>({ expense_type: 'TRANSPORT', description: '', amount: '', occurred_on: localToday(), remark: '' })
let generation = 0
let summaryRequest = 0
let expensesRequest = 0
let submittedBody = ''
let requestId = ''

function errorText(error: unknown, fallback: string) {
  if (isAxiosError(error)) {
    if (error.response?.status === 412) return '费用已被其他人修改，请关闭窗口并刷新费用后重试。'
    return taskRequestMessage(error)
  }
  return error instanceof Error ? error.message : fallback
}
function money(value: string | null) {
  if (value === null) return '—'
  const [whole = '0', fraction = '00'] = value.split('.')
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${fraction.padEnd(2, '0')}`
}
function share(category: ProductionCostCategory) {
  if (!summary.value?.complete || !summary.value.order_amount || Number(summary.value.order_amount) <= 0) return null
  return Number(category.amount) / Number(summary.value.order_amount) * 100
}
const hasRecords = computed(() => summary.value?.categories.some(category => category.count > 0 || category.missing_count > 0))
async function loadSummary() {
  if (!canView.value || !props.taskId) return
  const currentGeneration = generation
  const request = ++summaryRequest
  const taskId = props.taskId
  loading.value = true
  loadError.value = ''
  try {
    const data = await fetchProductionTaskCostSummary(taskId)
    if (currentGeneration === generation && request === summaryRequest) summary.value = data
  } catch (error) {
    if (currentGeneration === generation && request === summaryRequest) { summary.value = null; loadError.value = errorText(error, '成本加载失败，请重试。') }
  } finally {
    if (currentGeneration === generation && request === summaryRequest) loading.value = false
  }
}
async function loadExpenses() {
  if (!canView.value || !props.taskId) return
  const currentGeneration = generation
  const request = ++expensesRequest
  expensesLoading.value = true
  expensesError.value = ''
  try {
    const data = await fetchProductionTaskExpenses(props.taskId)
    if (currentGeneration === generation && request === expensesRequest) { expenses.value = data; expensesLoaded.value = true }
  } catch (error) {
    if (currentGeneration === generation && request === expensesRequest) { expensesLoaded.value = false; expenses.value = []; expensesError.value = errorText(error, '费用加载失败，请重试。') }
  } finally {
    if (currentGeneration === generation && request === expensesRequest) expensesLoading.value = false
  }
}
function toggleCategory(category: ProductionCostCategory) {
  if (expanded.value.includes(category.key)) expanded.value = expanded.value.filter(key => key !== category.key)
  else {
    expanded.value.push(category.key)
    if (category.key === 'other' && !expensesLoaded.value && !expensesLoading.value) void loadExpenses()
  }
}
async function openExpense(expense: ProductionTaskExpense | null = null) {
  if (!canManage.value || saving.value) return
  editing.value = expense
  Object.assign(form, expense ? { expense_type: expense.expense_type, description: expense.description, amount: expense.amount, occurred_on: expense.occurred_on, remark: expense.remark } : { expense_type: 'TRANSPORT', description: '', amount: '', occurred_on: localToday(), remark: '' })
  submittedBody = ''
  requestId = ''
  formError.value = ''
  dialogVisible.value = true
}
function validateForm() {
  if (!Object.hasOwn(expenseTypes, form.expense_type)) return '请选择费用类型。'
  if (!form.description.trim() || form.description.trim().length > 100) return '请填写 1 至 100 字的费用说明。'
  if (!/^\d{1,16}(\.\d{1,2})?$/.test(form.amount) || !/[1-9]/.test(form.amount)) return '金额须大于 0，最多 16 位整数和 2 位小数。'
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.occurred_on)) return '请选择发生日期。'
  const date = new Date(`${form.occurred_on}T00:00:00Z`)
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== form.occurred_on) return '请选择有效的发生日期。'
  if (form.remark.length > 500) return '备注最多 500 字。'
  return ''
}
async function saveExpense() {
  if (!canManage.value || saving.value) return
  formError.value = validateForm()
  if (formError.value) return
  const currentGeneration = generation
  const taskId = props.taskId
  const payload: ProductionTaskExpenseInput = { ...form, description: form.description.trim(), remark: form.remark.trim() }
  const currentEditing = editing.value
  saving.value = true
  try {
    if (currentEditing) await updateProductionTaskExpense(taskId, currentEditing.id, payload, currentEditing.etag)
    else {
      // 相同内容重试沿用 UUID；修改内容后使用新的请求标识。
      const body = JSON.stringify(payload)
      if (submittedBody !== body) { requestId = createClientUuid(); submittedBody = body }
      await createProductionTaskExpense(taskId, { ...payload, client_request_id: requestId })
    }
    if (currentGeneration !== generation) return
    dialogVisible.value = false
    ElMessage.success(currentEditing ? '费用已修改' : '费用已登记')
    await Promise.all([loadSummary(), loadExpenses()])
  } catch (error) {
    if (currentGeneration === generation) formError.value = errorText(error, '保存失败，请重试。')
  } finally {
    if (currentGeneration === generation) saving.value = false
  }
}
async function voidExpense(expense: ProductionTaskExpense) {
  if (!canManage.value || voiding.value) return
  const currentGeneration = generation
  const taskId = props.taskId
  try { await ElMessageBox.confirm(`作废“${expense.description}”后，将不再计入当前成本。`, '作废费用', { type: 'warning', confirmButtonText: '确认作废', cancelButtonText: '取消' }) }
  catch (error) {
    if (error !== 'cancel' && error !== 'close' && currentGeneration === generation) expensesError.value = errorText(error, '无法确认作废，请重试。')
    return
  }
  if (currentGeneration !== generation || !canManage.value) return
  voiding.value = expense.id
  try {
    await voidProductionTaskExpense(taskId, expense.id, expense.etag)
    if (currentGeneration !== generation) return
    ElMessage.success('费用已作废')
    await Promise.all([loadSummary(), loadExpenses()])
  } catch (error) {
    if (currentGeneration === generation) expensesError.value = errorText(error, '作废失败，请刷新后重试。')
  } finally {
    if (currentGeneration === generation) voiding.value = ''
  }
}
watch([() => props.taskId, canView], () => {
  generation += 1
  summary.value = null
  expenses.value = []
  expensesLoaded.value = false
  expanded.value = []
  loadError.value = ''
  expensesError.value = ''
  dialogVisible.value = false
  loading.value = false
  expensesLoading.value = false
  saving.value = false
  voiding.value = ''
  void loadSummary()
}, { immediate: true })
watch(canManage, allowed => { if (!allowed) dialogVisible.value = false })
watch(() => saving.value || !!voiding.value, busy => emit('busy-change', busy), { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { generation += 1 })
</script>

<template>
  <section v-if="canView" class="cost-panel" aria-labelledby="order-cost-heading">
    <header class="cost-heading">
      <div><h2 id="order-cost-heading">当前成本总览</h2><p>汇总当前已保存金额 · 人民币（元）</p></div>
      <el-button v-if="canManage" data-test="add-expense" type="primary" :disabled="loading || saving" @click="openExpense()">登记费用</el-button>
    </header>
    <p v-if="loading" role="status" class="cost-state">正在加载成本…</p>
    <div v-else-if="loadError" class="cost-error" role="alert">{{ loadError }} <el-button data-test="retry-summary" @click="loadSummary">重试</el-button></div>
    <template v-else-if="summary">
      <div class="cost-totals">
        <div><span>订单金额</span><strong>{{ money(summary.order_amount) }}</strong></div>
        <div><span>当前记录成本 <em v-if="!summary.complete">已知部分</em></span><strong>{{ money(summary.recorded_cost) }}</strong><small v-if="summary.complete && summary.cost_ratio !== null">占订单金额 {{ summary.cost_ratio }}%</small></div>
        <div><span>当前差额</span><strong data-test="difference" :class="{ 'is-negative': summary.complete && Number(summary.current_difference) < 0 }">{{ money(summary.complete ? summary.current_difference : null) }}</strong></div>
      </div>
      <div v-if="!summary.complete || summary.warnings.length" class="cost-warning" role="status">
        <p v-if="!summary.complete">当前成本为已知部分，尚有 {{ summary.missing_count }} 项缺少金额依据；差额和比例暂不计算。</p>
        <p v-for="warning in summary.warnings" :key="warning">{{ warning }}</p>
      </div>
      <p class="cost-note">当前差额 = 订单金额 − 当前记录成本，仅反映当前记录，不代表最终利润。</p>
      <p v-if="!hasRecords" class="cost-state">暂无成本记录。采购、报工、外发及登记费用保存后将在此汇总。</p>
      <div class="cost-categories">
        <div class="cost-table-heading"><span>成本分类 / 来源</span><span>当前金额</span><span>占订单金额</span></div>
        <div v-for="category in summary.categories" :key="category.key" class="cost-category">
          <button :data-test="`category-${category.key}`" class="cost-category-toggle" type="button" :aria-expanded="expanded.includes(category.key)" @click="toggleCategory(category)">
            <span class="category-title"><span class="disclosure" aria-hidden="true">{{ expanded.includes(category.key) ? '▾' : '▸' }}</span>{{ category.label }}<small>{{ category.count }} 条<span v-if="category.missing_count"> · {{ category.missing_count }} 项缺项</span></small></span>
            <span class="category-amount">{{ money(category.amount) }}</span>
            <span class="category-ratio"><span class="ratio-track" aria-hidden="true"><i :style="{ width: `${Math.min(100, Math.max(0, share(category) ?? 0))}%` }" /></span>{{ share(category) === null ? '—' : `${share(category)!.toFixed(1)}%` }}</span>
          </button>
          <div v-if="expanded.includes(category.key)" class="cost-sources">
            <p v-if="!category.items.length" class="cost-state">暂无来源记录</p>
            <div v-for="item in category.items" :key="item.id" class="cost-source">
              <div class="source-label"><RouterLink v-if="item.href" :to="item.href">{{ item.number || item.label }}</RouterLink><span v-else>{{ item.number || item.label }}</span><small v-if="item.number">{{ item.label }}</small><small v-if="item.occurred_on">{{ item.occurred_on }}</small><small v-if="item.missing_reason" class="is-negative">未计入：{{ item.missing_reason }}</small></div>
              <div class="source-amount"><span>{{ item.amount_cny === null ? '待补充' : money(item.amount_cny) }}</span><small v-if="item.currency && item.currency !== 'CNY'">原币 {{ item.currency }} {{ item.amount === null ? '—' : money(item.amount) }}</small></div>
            </div>
            <div v-if="category.key === 'other'" class="expense-management">
              <p v-if="expensesLoading" role="status">正在加载费用…</p>
              <div v-if="expensesError" class="cost-error" role="alert">{{ expensesError }} <el-button @click="loadExpenses">刷新费用</el-button></div>
              <template v-if="canManage && expensesLoaded">
                <div v-for="expense in expenses" :key="expense.id" class="expense-actions"><span>{{ expenseTypes[expense.expense_type] }} · {{ expense.description }}</span><div><el-button :disabled="saving || !!voiding" @click="openExpense(expense)">编辑</el-button><el-button type="danger" plain :disabled="saving || !!voiding" :loading="voiding === expense.id" @click="voidExpense(expense)">作废</el-button></div></div>
              </template>
            </div>
          </div>
        </div>
      </div>
    </template>
    <AppWindowDialog v-model="dialogVisible" :title="editing ? '编辑费用' : '登记费用'" :width="560" :min-width="280" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" :minimizable="false">
      <el-form class="expense-form" label-position="top" @submit.prevent="saveExpense">
        <el-form-item label="费用类型" required><el-select v-model="form.expense_type" :disabled="saving"><el-option v-for="(label, value) in expenseTypes" :key="value" :label="label" :value="value" /></el-select></el-form-item>
        <el-form-item label="费用说明" required><el-input v-model="form.description" data-test="description" maxlength="100" show-word-limit :disabled="saving" /></el-form-item>
        <div class="expense-form-row"><el-form-item label="金额（人民币元）" required><el-input v-model="form.amount" data-test="amount" inputmode="decimal" :disabled="saving" placeholder="大于 0，最多 2 位小数" /></el-form-item><el-form-item label="发生日期" required><el-date-picker v-model="form.occurred_on" type="date" value-format="YYYY-MM-DD" format="YYYY-MM-DD" :disabled="saving" /></el-form-item></div>
        <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" :rows="3" maxlength="500" show-word-limit :disabled="saving" /></el-form-item>
        <p v-if="formError" class="cost-error" role="alert">{{ formError }}</p>
      </el-form>
      <template #footer><el-button :disabled="saving" @click="dialogVisible = false">取消</el-button><el-button data-test="save-expense" type="primary" :loading="saving" @click="saveExpense">保存费用</el-button></template>
    </AppWindowDialog>
  </section>
</template>

<style scoped>
.cost-panel { padding: 20px; background: var(--el-bg-color); border: 1px solid var(--el-border-color-light); border-radius: var(--el-border-radius-base); color: var(--el-text-color-primary); min-width: 0; }
.cost-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 20px; }
.cost-heading h2 { margin: 0; font-size: 16px; font-weight: 600; }
.cost-heading p, .cost-note { margin: 6px 0 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
.cost-panel :deep(.el-button) { height: 32px; }
.cost-totals { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 20px; padding-bottom: 18px; border-bottom: 1px solid var(--el-border-color-light); }
.cost-totals > div { min-width: 0; }
.cost-totals span { color: var(--el-text-color-secondary); font-size: 13px; }
.cost-totals strong { display: block; margin-top: 8px; font-size: clamp(18px, 2vw, 26px); font-variant-numeric: tabular-nums; font-weight: 600; overflow-wrap: anywhere; }
.cost-totals em { font-style: normal; font-size: 12px; color: var(--el-color-warning); }
.cost-totals small { display: block; margin-top: 6px; font-size: 12px; color: var(--el-text-color-secondary); }
.is-negative, .cost-error { color: var(--el-color-danger); }
.cost-warning { color: var(--el-color-warning-dark-2); background: var(--el-color-warning-light-9); padding: 10px 12px; margin-top: 12px; font-size: 13px; }
.cost-warning p { margin: 0; line-height: 1.7; }
.cost-error { font-size: 13px; line-height: 1.7; overflow-wrap: anywhere; }
.cost-state { margin: 0; padding: 18px 0; color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.6; }
.cost-categories { margin-top: 16px; }
.cost-table-heading, .cost-category-toggle { display: grid; grid-template-columns: minmax(0, 1fr) minmax(100px, .4fr) minmax(130px, .5fr); align-items: center; gap: 20px; }
.cost-table-heading { padding: 10px 12px; color: var(--el-text-color-secondary); font-size: 12px; background: var(--el-fill-color-light); }
.cost-table-heading > :nth-child(n+2) { text-align: right; }
.cost-category { border-bottom: 1px solid var(--el-border-color-lighter); }
.cost-category-toggle { width: 100%; padding: 14px 12px; border: 0; background: transparent; color: inherit; font: inherit; text-align: left; cursor: pointer; }
.cost-category-toggle:hover { background: var(--el-fill-color-light); }
.cost-category-toggle:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: -2px; }
.category-title { min-width: 0; overflow-wrap: anywhere; font-size: 14px; }
.category-title small { margin-left: 8px; font-size: 12px; color: var(--el-text-color-secondary); }
.disclosure { display: inline-block; width: 16px; color: var(--el-text-color-secondary); }
.category-amount { text-align: right; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.category-ratio { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 8px; min-width: 0; overflow-wrap: anywhere; font-size: 12px; font-variant-numeric: tabular-nums; }
.ratio-track { width: 64px; height: 5px; background: var(--el-fill-color); border-radius: 3px; overflow: hidden; }
.ratio-track i { display: block; height: 100%; background: var(--el-color-primary); }
.cost-sources { padding: 0 12px 12px 28px; }
.cost-source { display: flex; align-items: start; justify-content: space-between; gap: 12px; padding: 10px 0; font-size: 13px; border-top: 1px dashed var(--el-border-color-lighter); }
.source-label { min-width: 0; overflow-wrap: anywhere; }
.source-label a { color: var(--el-color-primary); }
.cost-source small { display: block; margin-top: 4px; font-size: 12px; color: var(--el-text-color-secondary); }
.cost-source small.is-negative { color: var(--el-color-danger); }
.source-amount { text-align: right; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.expense-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 10px; font-size: 12px; }
.expense-actions > span { min-width: 0; overflow-wrap: anywhere; }
.expense-actions > div { flex-shrink: 0; }
.expense-form { padding: 4px 0; }
.expense-form-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.expense-form :deep(.el-select), .expense-form :deep(.el-date-editor) { width: 100%; }
@media (max-width: 640px) {
  .cost-panel { padding: 14px; }
  .cost-totals { grid-template-columns: 1fr; gap: 12px; }
  .cost-totals span { font-size: 12px; }
  .cost-table-heading, .cost-category-toggle { grid-template-columns: minmax(0, 1fr) minmax(80px, .65fr) 60px; gap: 8px; padding-left: 4px; padding-right: 4px; }
  .ratio-track { display: none; }
  .category-title small { display: block; margin: 4px 0 0 16px; }
  .expense-form-row { grid-template-columns: 1fr; gap: 0; }
  .cost-sources { padding-left: 12px; }
}
</style>
