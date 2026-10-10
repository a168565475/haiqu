<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

import {
  decideProductionTaskByPmc,
  fetchProductionTask,
  fetchProductionTaskOptions,
  finishProductionTask,
  submitProductionTask,
} from '@/api/productionTasks'
import ProductionTaskScheduleDialog from '@/components/productionScheduling/ProductionTaskScheduleDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { ProductionTask, ProductionTaskOptions, ProductionTaskStatus } from '@/types/productionTask'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const loading = ref(true)
const actionLoading = ref(false)
const loadError = ref('')
const task = ref<ProductionTask | null>(null)
const etag = ref('')
const options = ref<ProductionTaskOptions | null>(null)
const pmcDialogVisible = ref(false)
const optionsLoading = ref(false)
const optionsError = ref('')
const scheduleDialogVisible = ref(false)
let optionsRequest = 0
onBeforeUnmount(() => { optionsRequest += 1 })
const pmcMode = ref<'CONFIRM' | 'RETURN'>('CONFIRM')
const pmcForm = reactive({
  planned_start_date: '',
  planned_end_date: '',
  production_priority: 'NORMAL' as 'URGENT' | 'HIGH' | 'NORMAL' | 'LOW',
  production_batch_number: '',
  planner_id: '' as string,
  reason: '',
})

const taskId = computed(() => String(route.params.taskId || ''))
const canEdit = computed(() => (
  authStore.hasPermission('production_tasks.change_productiontask')
  && ['DRAFT', 'PENDING_VALIDATION', 'READY'].includes(task.value?.status || '')
))
const canSubmit = computed(() => (
  authStore.hasPermission('production_tasks.submit_productiontask') && task.value?.status === 'DRAFT'
))
const canConfirm = computed(() => (
  authStore.hasPermission('production_tasks.confirm_productiontask') && task.value?.status === 'PENDING_VALIDATION'
))
const canSchedule = computed(() => (
  authStore.hasPermission('production_scheduling.view_productionschedule')
  && authStore.hasPermission('production_scheduling.add_productionschedule')
  && task.value?.status === 'READY'
))
const canFinish = computed(() => (
  authStore.moduleCan('access_control.finish_productiontask', 'production_tasks.change_productiontask') && task.value?.status === 'IN_PRODUCTION'
))

const standardStatusSteps: Array<{ status: ProductionTaskStatus; label: string }> = [
  { status: 'DRAFT', label: '草稿' },
  { status: 'PENDING_VALIDATION', label: '待PMC确认' },
  { status: 'READY', label: '已接单' },
  { status: 'IN_PRODUCTION', label: '生产中' },
  { status: 'COMPLETED', label: '已完成' },
]

const statusSteps = computed<Array<{ status: ProductionTaskStatus; label: string }>>(() => {
  if (task.value?.status === 'PAUSED') {
    return [...standardStatusSteps.slice(0, 4), { status: 'PAUSED', label: '已暂停' }]
  }
  if (task.value?.status === 'CANCELLED') {
    return [{ status: 'CANCELLED', label: '已取消' }]
  }
  return standardStatusSteps
})
const currentStatusIndex = computed(() => statusSteps.value.findIndex((item) => item.status === task.value?.status))
const currentBomText = computed(() => {
  const boms = task.value?.current_boms || []
  if (!boms.length) return '尚未建立'
  return boms.map((item) => `${item.bom_number} V${item.version_number} ${item.status_display}`).join('；')
})
const packagingRequirement = computed(() => {
  const values = [...new Set((task.value?.products || []).map((item) => item.packaging_method.trim()).filter(Boolean))]
  return values.join('；') || '—'
})
const productionRequirement = computed(() => plainText(task.value?.special_requirements_html || '') || '—')
const preproductionSample = computed(() => task.value?.preproduction_sample_required ? '需要产前确认样' : '不需要产前确认样')

function apiError(error: unknown) {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '请求失败，请稍后重试。'
  const data = error.response?.data as { error?: { message?: string }; detail?: string } | undefined
  return data?.error?.message || data?.detail || '操作失败，请刷新后重试。'
}

function plainText(html: string) {
  if (!html) return ''
  const element = document.createElement('div')
  element.innerHTML = html
  return (element.textContent || '').replace(/\s+/g, ' ').trim()
}

function number(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed)
    ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(parsed)
    : String(value)
}

function dateTime(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(parsed).replaceAll('/', '-')
}

async function loadTask() {
  loading.value = true
  loadError.value = ''
  try {
    const result = await fetchProductionTask(taskId.value)
    task.value = result.data
    etag.value = result.etag
  } catch (error) {
    loadError.value = apiError(error)
  } finally {
    loading.value = false
  }
}

async function submitTask() {
  if (!task.value || !canSubmit.value) return
  try {
    await ElMessageBox.confirm('提交后状态将变为“待 PMC 确认”。', '提交 PMC', {
      type: 'warning', confirmButtonText: '确认提交', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  actionLoading.value = true
  try {
    const result = await submitProductionTask(task.value.id, etag.value)
    task.value = result.data
    etag.value = result.etag
    ElMessage.success('已提交 PMC 确认。')
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    actionLoading.value = false
  }
}

async function loadPmcOptions() {
  const requestId = ++optionsRequest
  optionsLoading.value = true
  optionsError.value = ''
  options.value = null
  try {
    const result = await fetchProductionTaskOptions()
    if (requestId === optionsRequest) options.value = result
  } catch (error) {
    if (requestId === optionsRequest) optionsError.value = apiError(error)
  } finally {
    if (requestId === optionsRequest) optionsLoading.value = false
  }
}

function openPmcDialog(mode: 'CONFIRM' | 'RETURN') {
  if (!task.value) return
  pmcMode.value = mode
  pmcForm.planned_start_date = task.value.planned_start_date || ''
  pmcForm.planned_end_date = task.value.planned_end_date || ''
  pmcForm.production_priority = task.value.production_priority || 'NORMAL'
  pmcForm.production_batch_number = task.value.production_batch_number || ''
  pmcForm.planner_id = task.value.planner?.id || ''
  pmcForm.reason = ''
  pmcDialogVisible.value = true
  if (mode === 'CONFIRM') void loadPmcOptions()
}

async function decideByPmc() {
  if (!task.value) return
  if (pmcMode.value === 'CONFIRM' && (optionsLoading.value || !options.value)) return
  if (pmcMode.value === 'RETURN' && !pmcForm.reason.trim()) {
    ElMessage.warning('请填写退回原因。')
    return
  }
  if (pmcMode.value === 'CONFIRM') {
    if (!pmcForm.planned_start_date || !pmcForm.planned_end_date) {
      ElMessage.warning('请填写计划开始和计划完工日期。')
      return
    }
    if (pmcForm.planned_end_date < pmcForm.planned_start_date) {
      ElMessage.warning('计划完工日期不能早于计划开始日期。')
      return
    }
  }
  actionLoading.value = true
  try {
    const payload = pmcMode.value === 'RETURN'
      ? { decision: 'RETURN' as const, reason: pmcForm.reason.trim() }
      : {
          decision: 'CONFIRM' as const,
          planned_start_date: pmcForm.planned_start_date,
          planned_end_date: pmcForm.planned_end_date,
          production_priority: pmcForm.production_priority,
          production_batch_number: pmcForm.production_batch_number.trim(),
          planner_id: pmcForm.planner_id || null,
        }
    const result = await decideProductionTaskByPmc(task.value.id, payload, etag.value)
    task.value = result.data
    etag.value = result.etag
    pmcDialogVisible.value = false
    ElMessage.success(pmcMode.value === 'RETURN' ? '已退回修改。' : 'PMC 已确认。')
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    actionLoading.value = false
  }
}

async function finishTask() {
  if (!task.value || !canFinish.value) return
  try {
    const result = await ElMessageBox.prompt('请输入完工说明。', '完成生产', {
      type: 'warning', inputType: 'textarea', confirmButtonText: '确认完成', cancelButtonText: '取消',
      inputValidator: (value) => Boolean(String(value || '').trim()) || '请填写完工说明。',
    })
    actionLoading.value = true
    const updated = await finishProductionTask(task.value.id, result.value.trim(), etag.value)
    task.value = updated.data
    etag.value = updated.etag
    ElMessage.success('生产任务已完成。')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(apiError(error))
  } finally {
    actionLoading.value = false
  }
}

async function handleScheduleSaved() {
  await loadTask()
}

function goBack() {
  void router.push({ name: 'production-tasks' })
}

onMounted(() => { void loadTask() })
</script>

<template>
  <section class="task-detail-page" aria-label="生产任务单详情" v-loading="loading">
    <div v-if="loadError" class="load-error"><strong>详情加载失败</strong><span>{{ loadError }}</span><ElButton type="primary" @click="loadTask">重新加载</ElButton></div>
    <template v-else-if="task">
      <header class="detail-heading">
        <div class="detail-heading__title"><h1>生产任务单详情</h1><strong>{{ task.task_number }}</strong><span :class="`status-${task.status.toLowerCase()}`">{{ task.status_display }}</span></div>
        <div class="detail-heading__actions"><ElButton v-if="canEdit" @click="router.push({ name: 'production-task-edit', params: { taskId: task.id } })">编辑</ElButton><ElButton @click="goBack">返回</ElButton></div>
      </header>

      <div class="detail-grid">
        <main class="detail-main">
          <section class="detail-card basic-card">
            <h2>基本信息</h2>
            <div class="info-grid">
              <label><span>生产任务单号</span><strong>{{ task.task_number }}</strong></label>
              <label><span>交付批次</span><strong>{{ task.source_delivery_batch_number || task.production_batch_number || '—' }}</strong></label>
              <label><span>来源销售订单</span><strong>{{ task.source_sales_order_number || task.order_number || '历史未关联' }}</strong></label>
              <label><span>计划完成日期</span><strong>{{ task.planned_end_date || '—' }}</strong></label>
              <label><span>客户</span><strong>{{ task.customer_name }}</strong></label>
              <label><span>计划员</span><strong>{{ task.planner?.display_name || '—' }}</strong></label>
              <label><span>产品</span><strong>{{ task.products.length }} 个颜色明细</strong></label>
              <label><span>业务跟单</span><strong>{{ task.followers.map((item) => item.display_name).join('、') || task.salesperson.display_name }}</strong></label>
              <label><span>生产数量</span><strong>{{ number(task.total_quantity) }}</strong></label>
              <label><span>生产优先级</span><strong>{{ task.production_priority === 'URGENT' ? '紧急' : task.production_priority === 'HIGH' ? '高' : task.production_priority === 'LOW' ? '低' : '普通' }}</strong></label>
            </div>
          </section>

          <section class="detail-card products-card">
            <h2>生产产品明细</h2>
            <div class="table-wrap">
              <table>
                <thead><tr><th>颜色 / 规格</th><th>产品编码</th><th>产品名称</th><th>生产数量</th><th>计划开工</th><th>计划完工</th><th>包装要求</th><th>备注</th></tr></thead>
                <tbody>
                  <tr v-for="product in task.products" :key="product.id">
                    <td :title="[product.color_name, product.color_code, product.specification].filter(Boolean).join(' / ') || '—'"><span class="color-dot" />{{ [product.color_name, product.color_code, product.specification].filter(Boolean).join(' / ') || '—' }}</td>
                    <td>{{ product.product_code || product.product_number }}</td><td :title="product.product_name">{{ product.product_name }}</td><td>{{ number(product.quantity) }}</td>
                    <td>{{ task.planned_start_date || '—' }}</td><td>{{ task.planned_end_date || '—' }}</td><td :title="product.packaging_method || '—'">{{ product.packaging_method || '—' }}</td><td :title="product.special_requirements || '—'">{{ product.special_requirements || '—' }}</td>
                  </tr>
                  <tr class="total-row"><td colspan="3">合计</td><td>{{ number(task.total_quantity) }}</td><td>—</td><td>—</td><td>—</td><td>—</td></tr>
                </tbody>
              </table>
            </div>
          </section>

          <section class="detail-card requirements-card">
            <h2>详细要求</h2>
            <dl><div><dt>包装要求</dt><dd>{{ packagingRequirement }}</dd></div><div><dt>生产说明</dt><dd>{{ productionRequirement }}</dd></div><div><dt>产前样</dt><dd>{{ preproductionSample }}</dd></div><div><dt>其他要求</dt><dd>{{ task.status_reason || '—' }}</dd></div></dl>
          </section>
        </main>

        <aside class="handoff-card">
          <h2>生产交接</h2>
          <div class="status-steps">
            <div v-for="(step, index) in statusSteps" :key="step.status" :class="{ 'is-done': index < currentStatusIndex, 'is-current': index === currentStatusIndex }"><i /><span>{{ step.label }}</span></div>
          </div>
          <p class="start-hint is-ready">计划排产前会核对产品 BOM 与采购状态；保存后任务进入生产中。</p>

          <h2>当前负责人</h2>
          <dl class="side-info"><div><dt>计划员</dt><dd>{{ task.planner?.display_name || '—' }}</dd></div><div><dt>业务跟单</dt><dd>{{ task.followers.map((item) => item.display_name).join('、') || task.salesperson.display_name }}</dd></div></dl>
          <h2>关键信息</h2>
          <dl class="side-info"><div><dt>PMC确认</dt><dd>{{ task.pmc_confirmation ? `已通过 · ${dateTime(task.pmc_confirmation.confirmed_at)}` : '尚未确认' }}</dd></div><div><dt>当前BOM</dt><dd>{{ currentBomText }}</dd></div><div><dt>计划完成日期</dt><dd>{{ task.planned_end_date || '—' }}</dd></div></dl>

          <div class="primary-actions">
            <ElButton v-if="canSubmit" type="primary" :loading="actionLoading" @click="submitTask">提交 PMC 确认</ElButton>
            <template v-if="canConfirm"><ElButton type="primary" :loading="actionLoading" @click="openPmcDialog('CONFIRM')">PMC 确认通过</ElButton><ElButton :loading="actionLoading" @click="openPmcDialog('RETURN')">退回修改</ElButton></template>
            <ElButton v-if="canSchedule" type="primary" @click="scheduleDialogVisible = true">计划排产</ElButton>
            <ElButton v-if="canFinish" type="primary" :loading="actionLoading" @click="finishTask">完成生产</ElButton>
          </div>

          <h2 class="timeline-title">操作记录</h2>
          <div v-if="task.audit_timeline?.length" class="timeline"><div v-for="event in task.audit_timeline" :key="event.id"><i /><time>{{ dateTime(event.occurred_at) }}</time><strong>{{ event.action_display }}</strong><small>操作人：{{ event.actor_name || '系统' }}</small><p v-if="event.reason">{{ event.reason }}</p></div></div>
          <div v-else class="timeline-empty">暂无操作记录</div>
        </aside>
      </div>
    </template>

    <ElDialog v-model="pmcDialogVisible" :title="pmcMode === 'CONFIRM' ? 'PMC 确认生产任务' : '退回修改'" width="560px" destroy-on-close>
      <ElAlert v-if="pmcMode === 'CONFIRM' && optionsError" :title="optionsError" type="error" :closable="false"><ElButton link @click="loadPmcOptions">重新加载计划员</ElButton></ElAlert>
      <div v-if="pmcMode === 'CONFIRM'" class="pmc-form"><label><span>计划开始日期 *</span><ElDatePicker v-model="pmcForm.planned_start_date" type="date" value-format="YYYY-MM-DD" /></label><label><span>计划完工日期 *</span><ElDatePicker v-model="pmcForm.planned_end_date" type="date" value-format="YYYY-MM-DD" /></label><label><span>优先级</span><ElSelect v-model="pmcForm.production_priority"><ElOption label="紧急" value="URGENT" /><ElOption label="高" value="HIGH" /><ElOption label="普通" value="NORMAL" /><ElOption label="低" value="LOW" /></ElSelect></label><label><span>生产批号</span><ElInput v-model="pmcForm.production_batch_number" maxlength="50" /></label><label><span>计划员</span><ElSelect v-model="pmcForm.planner_id" :loading="optionsLoading" :disabled="optionsLoading || !!optionsError" clearable filterable><ElOption v-for="employee in options?.employees || []" :key="employee.id" :label="employee.display_name" :value="employee.id" /></ElSelect></label></div>
      <ElInput v-else v-model="pmcForm.reason" type="textarea" :rows="5" maxlength="500" show-word-limit placeholder="请填写需要修改的内容" />
      <template #footer><ElButton @click="pmcDialogVisible = false">取消</ElButton><ElButton type="primary" :loading="actionLoading" :disabled="pmcMode === 'CONFIRM' && (optionsLoading || !options)" @click="decideByPmc">{{ pmcMode === 'CONFIRM' ? '确认通过' : '确认退回' }}</ElButton></template>
    </ElDialog>
    <ProductionTaskScheduleDialog v-model="scheduleDialogVisible" :task="task" @saved="handleScheduleSaved" />
  </section>
</template>

<style scoped lang="scss">
.task-detail-page { box-sizing: border-box; min-width: 1320px; min-height: calc(100vh - 64px); padding: 28px 28px 46px; background: var(--erp-page-background); color: #202124; }
.detail-heading { display: flex; height: 113px; align-items: flex-start; justify-content: space-between; }
.detail-heading__title { display: flex; align-items: center; gap: 24px; }
.detail-heading h1, .detail-heading strong { margin: 0; font-family: 'Noto Serif SC', serif; font-size: 32px; line-height: 42px; }
.detail-heading__title > span { min-width: 118px; height: 31px; display: grid; place-items: center; padding: 0 10px; border-radius: 5px; color: #b86613; background: #fbead3; font-size: 14px; }
.detail-heading__title > span.status-in_production { color: #17633c; background: #e5f5ec; }
.detail-heading__title > span.status-completed { color: #4b5563; background: #eceff2; }
.detail-heading__title > span.status-cancelled { color: #991b1b; background: #fee2e2; }
.detail-heading__actions { display: flex; gap: 16px; padding-top: 10px; }
.detail-heading__actions .el-button { min-width: 124px; height: 41px; }
.detail-grid { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 10px; align-items: start; }
.detail-main { display: flex; flex-direction: column; gap: 13px; }
.detail-card, .handoff-card { box-sizing: border-box; border: 1px solid #e3dfd7; border-radius: 5px; background: #fdfcf9; }
.detail-card { padding: 14px 17px 16px; }
.detail-card h2, .handoff-card h2 { margin: 0; padding-bottom: 11px; border-bottom: 1px solid #e3dfd7; font-family: 'Noto Serif SC', serif; font-size: 20px; line-height: 30px; }
.basic-card { min-height: 296px; }
.info-grid { display: grid; grid-template-columns: repeat(2, 1fr); column-gap: 28px; margin-top: 10px; }
.info-grid label { min-width: 0; height: 38px; display: grid; grid-template-columns: 150px 1fr; align-items: center; font-size: 14px; }
.info-grid label:nth-child(odd) { border-right: 1px solid #e3dfd7; }
.info-grid span, dt { color: #68686a; font-weight: 400; }
.info-grid strong { overflow: hidden; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.products-card { min-height: 296px; }
.table-wrap { overflow: auto; margin-top: 12px; border-radius: 4px; }
table { width: 100%; min-width: 980px; border-collapse: collapse; table-layout: fixed; font-size: 12px; }
th { height: 40px; padding: 0 12px; color: #68686a; background: #efede7; font-weight: 500; text-align: left; }
td { height: 54px; padding: 0 12px; overflow: hidden; border: 1px solid #e3dfd7; text-overflow: ellipsis; white-space: nowrap; }
th:nth-child(1) { width: 180px; } th:nth-child(2) { width: 130px; } th:nth-child(3) { width: 160px; } th:nth-child(4) { width: 90px; } th:nth-child(5), th:nth-child(6) { width: 100px; } th:nth-child(7) { width: 150px; }
.color-dot { width: 14px; height: 14px; display: inline-block; margin-right: 8px; border: 1px solid #b8b5ad; border-radius: 50%; background: #777; vertical-align: -2px; }
.total-row td { font-weight: 600; }
.requirements-card { min-height: 260px; }
.requirements-card dl { margin: 8px 0 0; }
.requirements-card dl > div { min-height: 43px; display: grid; grid-template-columns: 150px 1fr; align-items: center; border-bottom: 1px solid #e3dfd7; font-size: 14px; }
.requirements-card dl > div:last-child { border-bottom: 0; }
dd { margin: 0; min-width: 0; }
.handoff-card { min-height: 869px; padding: 14px 18px 24px; }
.status-steps { position: relative; display: grid; grid-template-columns: repeat(5, 1fr); margin: 18px 0 16px; }
.status-steps::before { content: ''; position: absolute; left: 8%; right: 8%; top: 9px; height: 1px; background: #bdb4a6; }
.status-steps > div { position: relative; display: flex; align-items: center; flex-direction: column; gap: 11px; color: #68686a; font-size: 12px; }
.status-steps i { z-index: 1; width: 16px; height: 16px; box-sizing: border-box; border: 4px solid #fdfcf9; border-radius: 50%; background: #c4c4c4; outline: 1px solid #c4c4c4; }
.status-steps .is-done i { background: #b6aa97; outline-color: #b6aa97; }
.status-steps .is-current { color: #202124; font-weight: 600; }
.status-steps .is-current i { background: #d7491c; outline-color: #d7491c; }
.start-hint { min-height: 49px; display: flex; align-items: center; margin: 0 0 18px; padding: 0 16px; color: #b86613; background: #fff3e3; font-size: 13px; }
.start-hint.is-ready { color: #17633c; background: #eaf7ef; }
.handoff-card h2:not(:first-child) { margin-top: 17px; }
.side-info { margin: 4px 0 0; }
.side-info > div { min-height: 38px; display: grid; grid-template-columns: 150px 1fr; align-items: center; font-size: 13px; }
.side-info dd { overflow-wrap: anywhere; }
.primary-actions { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 17px; }
.primary-actions .el-button { min-height: 41px; flex: 1 1 180px; margin: 0; }
.primary-actions :deep(.el-button--primary:not(.is-disabled)) { border-color: #d7491c; background: #d7491c; color: #fff; }
.timeline-title { margin-top: 20px !important; }
.timeline { position: relative; margin-top: 13px; max-height: 250px; overflow: auto; }
.timeline::before { content: ''; position: absolute; left: 7px; top: 10px; bottom: 12px; width: 1px; background: #b8b9bb; }
.timeline > div { position: relative; min-height: 66px; display: grid; grid-template-columns: 145px 1fr; padding-left: 28px; box-sizing: border-box; }
.timeline i { position: absolute; left: 2px; top: 6px; z-index: 1; width: 10px; height: 10px; border: 2px solid #fdfcf9; border-radius: 50%; background: #aeb0b2; outline: 1px solid #aeb0b2; }
.timeline > div:first-child i { background: #d7491c; outline-color: #d7491c; }
.timeline time, .timeline small { color: #68686a; font-size: 11px; }
.timeline strong { font-size: 13px; }
.timeline small { grid-column: 2; margin-top: -22px; }
.timeline p { grid-column: 2; margin: -5px 0 8px; color: #b86613; font-size: 11px; }
.timeline-empty { padding: 30px 0; color: #949498; font-size: 13px; text-align: center; }
.load-error { min-height: 480px; display: flex; align-items: center; justify-content: center; flex-direction: column; gap: 16px; color: #68686a; }
.load-error strong { color: #202124; font-size: 20px; }
.pmc-form { display: grid; grid-template-columns: repeat(2, 1fr); gap: 18px; }
.pmc-form label { display: flex; flex-direction: column; gap: 8px; color: #68686a; font-size: 13px; }
.pmc-form .el-date-editor, .pmc-form .el-select { width: 100%; }
</style>
