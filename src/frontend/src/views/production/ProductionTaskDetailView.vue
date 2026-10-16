<script setup lang="ts">
import { isTaskReadyForScheduling } from './productionTaskDisplay'
import ElDialog from '@/components/common/AppWindowDialog.vue'
import ProductImage from '@/components/products/ProductImage.vue'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, ArrowRight, Picture } from '@element-plus/icons-vue'

import {
  decideProductionTaskByPmc,
  fetchProductionTask,
  fetchProductionTaskOptions,
  finishProductionTask,
  submitProductionTask,
  productionTaskBusinessFileUrl,
} from '@/api/productionTasks'
import ProductionTaskScheduleDialog from '@/components/productionScheduling/ProductionTaskScheduleDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { ProductionTask, ProductionTaskOptions, ProductionDeliveryMethod, ProductionTaskStatus } from '@/types/productionTask'

import { quantityWithUnits, localAmountTotal } from './productionTaskDisplay'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const loading = ref(true)
const actionLoading = ref(false)
const loadError = ref('')
const task = ref<ProductionTask | null>(null)
const expandedProductIds = ref<string[]>([])
const failedImageIds = ref<string[]>([])
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
  follower_ids: [] as string[],
  delivery_date: '',
  includes_tax: false,
  tax_rate: null as 3 | 5 | 7 | null,
  order_tolerance_percent: '0',
  is_repeat_order: false,
  delivery_method: 'SINGLE' as ProductionDeliveryMethod,
})
watch(() => pmcForm.includes_tax, (includesTax) => { if (!includesTax) pmcForm.tax_rate = null })

const taskId = computed(() => String(route.params.taskId || ''))
const canEdit = computed(() => (
  authStore.hasPermission('production_tasks.change_productiontask')
  && ['DRAFT', 'PENDING_VALIDATION', 'READY', 'IN_PRODUCTION', 'PAUSED'].includes(task.value?.status || '')
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
  && isTaskReadyForScheduling(task.value)
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
  if (task.value?.status === 'PAUSED') return [...standardStatusSteps.slice(0, 4), { status: 'PAUSED', label: '已暂停' }]
  if (task.value?.status === 'CANCELLED') return [{ status: 'CANCELLED', label: '已取消' }]
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

function syncProductExpansion(id: string, event: Event) {
  const open = (event.target as HTMLDetailsElement).open
  if (open && !expandedProductIds.value.includes(id)) expandedProductIds.value.push(id)
  if (!open) expandedProductIds.value = expandedProductIds.value.filter(value => value !== id)
}

async function loadTask() {
  loading.value = true
  loadError.value = ''
  try {
    const result = await fetchProductionTask(taskId.value)
    task.value = result.data
    etag.value = result.etag
    expandedProductIds.value = result.data.products.slice(0, 1).map(product => product.id)
    failedImageIds.value = []
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
  pmcForm.follower_ids = task.value.followers.map((employee) => employee.id)
  pmcForm.delivery_date = task.value.delivery_date
  pmcForm.includes_tax = task.value.includes_tax ?? false
  pmcForm.tax_rate = task.value.tax_rate ?? null
  pmcForm.order_tolerance_percent = task.value.order_tolerance_percent || '0'
  pmcForm.is_repeat_order = task.value.is_repeat_order ?? false
  pmcForm.delivery_method = task.value.delivery_method || 'SINGLE'
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
    if (!pmcForm.follower_ids.length) { ElMessage.warning('请选择生产跟单员。'); return }
    if (!pmcForm.delivery_date || pmcForm.delivery_date < task.value.order_date) { ElMessage.warning('请选择不早于下单日期的交期。'); return }
    if (pmcForm.includes_tax && ![3, 5, 7].includes(Number(pmcForm.tax_rate))) { ElMessage.warning('含税时请选择税率。'); return }
    const tolerance = Number(pmcForm.order_tolerance_percent)
    if (pmcForm.order_tolerance_percent.trim() === '' || !Number.isFinite(tolerance) || tolerance < 0 || tolerance > 100) { ElMessage.warning('订单误差必须是 0 到 100 之间的百分比。'); return }
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
          follower_ids: [...pmcForm.follower_ids],
          delivery_date: pmcForm.delivery_date,
          includes_tax: pmcForm.includes_tax,
          tax_rate: pmcForm.includes_tax ? pmcForm.tax_rate : null,
          order_tolerance_percent: pmcForm.order_tolerance_percent,
          is_repeat_order: pmcForm.is_repeat_order,
          delivery_method: pmcForm.delivery_method,
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

onMounted(async () => {
  await loadTask()
  if (route.query?.pmc === 'confirm' && canConfirm.value) openPmcDialog('CONFIRM')
})
</script>

<template>
  <section class="task-detail-page" aria-label="生产任务单详情" :aria-busy="loading" v-loading="loading">
    <div v-if="loading" class="loading-state" role="status">正在加载生产任务单…</div>
    <div v-else-if="loadError" class="load-error" role="alert"><strong>详情加载失败</strong><span>{{ loadError }}</span><ElButton type="primary" @click="loadTask">重新加载</ElButton></div>
    <template v-else-if="task">
      <header class="detail-heading">
        <div class="detail-heading__title"><h1>生产任务单</h1><strong class="task-number">{{ task.task_number }}</strong><span class="task-status" :class="`status-${task.status.toLowerCase()}`">{{ task.status_display }}</span></div>
        <div class="detail-heading__actions">
          <ElButton v-if="canEdit" @click="router.push({ name: 'production-task-edit', params: { taskId: task.id } })">编辑</ElButton><ElButton @click="goBack">返回</ElButton>
          <ElButton v-if="canSubmit" type="primary" :loading="actionLoading" @click="submitTask">提交 PMC 确认</ElButton>
          <template v-if="canConfirm"><ElButton :loading="actionLoading" @click="openPmcDialog('RETURN')">退回修改</ElButton><ElButton type="primary" :loading="actionLoading" @click="openPmcDialog('CONFIRM')">PMC 确认通过</ElButton></template>
          <ElButton v-if="canSchedule" type="primary" @click="scheduleDialogVisible = true">计划排产</ElButton>
          <ElButton v-if="canFinish" type="primary" :loading="actionLoading" @click="finishTask">完成生产</ElButton>
        </div>
      </header>

      <section class="summary-bar" aria-label="任务汇总">
        <div><span>人民币金额合计</span><strong class="summary-money">¥ {{ localAmountTotal(task.products) }}</strong></div>
        <div><span>生产数量（按单位）</span><strong>{{ quantityWithUnits(task.products) }}</strong></div>
        <div><span>交期日期</span><strong>{{ task.delivery_date || '—' }}</strong></div>
      </section>

      <div class="dossier-layout">
        <aside class="task-sidebar">
          <section class="basic-card" aria-labelledby="task-info-title">
            <h2 id="task-info-title">任务资料</h2>
            <div class="info-grid">
              <label class="info-wide"><span>来源销售订单</span><strong>{{ task.source_sales_order_number || '手动创建（未关联销售订单）' }}</strong></label>
              <label><span>业务员</span><strong>{{ task.salesperson.display_name }}</strong></label>
              <label><span>跟单员</span><strong>{{ task.followers.map((item) => item.display_name).join('、') || '待选择' }}</strong></label>
              <label><span>计划员</span><strong>{{ task.planner?.display_name || '—' }}</strong></label>
              <label><span>下单日期</span><strong>{{ task.order_date }}</strong></label>
              <label><span>交期日期</span><strong>{{ task.delivery_date }}</strong></label>
              <label><span>交货方式</span><strong>{{ task.delivery_method === 'SPLIT' ? '分批交货' : '一次交货' }}</strong></label>
              <label><span>是否含税</span><strong>{{ task.includes_tax ? '含税' : '不含税' }}</strong></label>
              <label><span>税率</span><strong>{{ task.tax_rate ? `${task.tax_rate}%` : '—' }}</strong></label>
              <label><span>订单误差</span><strong>{{ task.order_tolerance_percent || '0' }}%</strong></label>
              <label><span>是否返单</span><strong>{{ task.is_repeat_order ? '是' : '否' }}</strong></label>
              <label><span>生产优先级</span><strong>{{ task.production_priority === 'URGENT' ? '紧急' : task.production_priority === 'HIGH' ? '高' : task.production_priority === 'LOW' ? '低' : '普通' }}</strong></label>
              <label><span>生产批号</span><strong>{{ task.production_batch_number || task.source_delivery_batch_number || '—' }}</strong></label>
            </div>
          </section>

          <section class="handoff-card" aria-labelledby="handoff-title">
          <div class="section-heading"><h2 id="handoff-title">生产交接</h2><span>当前：{{ task.status_display }}</span></div>
          <div class="status-steps" :class="{ 'status-steps--single': statusSteps.length === 1 }" aria-label="生产交接进度">
            <div v-for="(step, index) in statusSteps" :key="step.status" :class="{ 'is-done': index < currentStatusIndex, 'is-current': index === currentStatusIndex }" :aria-current="index === currentStatusIndex ? 'step' : undefined"><i aria-hidden="true"><Check v-if="index < currentStatusIndex" /><template v-else>{{ index + 1 }}</template></i><span><template v-if="step.status === 'PENDING_VALIDATION'">待PMC<br>确认</template><template v-else>{{ step.label }}</template></span></div>
          </div>
          <div class="status-branches"><span>分支状态</span><span :class="{ 'is-active': task.status === 'PAUSED' }">已暂停</span><span :class="{ 'is-active is-cancelled': task.status === 'CANCELLED' }">已取消</span></div>
          <dl class="side-info"><div><dt>PMC确认</dt><dd>{{ task.pmc_confirmation ? `已通过 · ${dateTime(task.pmc_confirmation.confirmed_at)}` : '尚未确认' }}</dd></div><div><dt>当前BOM</dt><dd>{{ currentBomText }}</dd></div></dl>
          <dl class="schedule-dates"><div><dt>计划开工</dt><dd>{{ task.planned_start_date || '—' }}</dd></div><div><dt>计划完工</dt><dd>{{ task.planned_end_date || '—' }}</dd></div></dl>
          </section>
        </aside>
        <div class="dossier-main">
          <section class="detail-card products-card" aria-labelledby="products-title">
            <div class="products-heading">
              <h2 id="products-title">生产产品档案</h2>
            </div>
            <div class="product-files">
              <details v-for="product in task.products" :key="product.id" class="product-file" :data-product-id="product.id" :open="expandedProductIds.includes(product.id)" @toggle="syncProductExpansion(product.id, $event)">
                <summary><ArrowRight class="file-arrow" aria-hidden="true"/><span class="file-name">{{ product.customer_product_name || product.product_name || '未命名产品' }}</span><span class="file-code">{{ product.item_number || '—' }}</span></summary>
                <div class="file-content">
                  <div class="product-figure">
                    <div class="product-photo">
                      <img v-if="product.images?.[0] && !failedImageIds.includes(product.images[0].id)" :src="productionTaskBusinessFileUrl(task.id, product.images[0].id)" :alt="product.images[0].name" @error="failedImageIds.push(product.images[0].id)" />
                      <template v-else><Picture aria-hidden="true"/><span>{{ product.images?.length ? '图片加载失败' : '暂无产品图片' }}</span></template>
                    </div>
                    <div class="product-images" aria-label="产品图片预览"><ProductImage v-for="image in product.images || []" :key="image.id" :src="productionTaskBusinessFileUrl(task.id, image.id)" :name="image.name"/></div>
                    <span v-if="product.images?.length" class="image-hint">点击缩略图查看大图</span>
                  </div>
                  <dl class="file-fields">
                    <div><dt>产品</dt><dd>{{ product.customer_product_name || product.product_name || '—' }}</dd></div><div><dt>货号</dt><dd>{{ product.item_number || '—' }}</dd></div>
                    <div><dt>颜色</dt><dd>{{ product.customer_color || product.color_name || product.color_code || '—' }}</dd></div><div><dt>规格</dt><dd>{{ product.specification_display || product.customer_specification || product.specification || '—' }}</dd></div>
                    <div><dt>材质</dt><dd>{{ product.material || '—' }}</dd></div><div><dt>数量</dt><dd>{{ number(product.quantity) }} {{ product.unit_name || product.unit_code || '单位未知' }}</dd></div>
                    <div><dt>人民币单价</dt><dd>¥ {{ product.local_unit_price ?? '—' }}</dd></div><div class="file-amount"><dt>人民币金额</dt><dd>¥ {{ product.local_total_amount ?? '—' }}</dd></div>
                    <div><dt>计划开工</dt><dd>{{ task.planned_start_date || '—' }}</dd></div><div><dt>计划完工</dt><dd>{{ task.planned_end_date || '—' }}</dd></div>
                    <div class="file-pack"><dt>包装要求</dt><dd>{{ product.packaging_method || '—' }}</dd></div><div class="file-note"><dt>备注</dt><dd>{{ product.special_requirements || '—' }}</dd></div>
                  </dl>
                </div>
              </details>
              <p v-if="!task.products.length" class="products-empty">暂无产品明细{{ canEdit ? '，可通过页面顶部“编辑”补充。' : '。' }}</p>
            </div>
          </section>
          <div class="bottom-grid">
          <section class="detail-card requirements-card">
            <h2>详细要求</h2>
            <dl><div><dt>包装要求</dt><dd>{{ packagingRequirement }}</dd></div><div><dt>生产说明</dt><dd>{{ productionRequirement }}</dd></div><div><dt>产前样</dt><dd :class="{ 'sample-required': task.preproduction_sample_required }">{{ preproductionSample }}</dd></div><div><dt>其他要求</dt><dd>{{ task.status_reason || '—' }}</dd></div></dl>
          </section>
          <section class="detail-card activity-card">
          <h2 class="timeline-title">操作记录</h2>
          <ol v-if="task.audit_timeline?.length" class="timeline"><li v-for="event in task.audit_timeline" :key="event.id"><time>{{ dateTime(event.occurred_at) }}</time><strong>{{ event.action_display }}</strong><small>操作人：{{ event.actor_name || '系统' }}</small><p v-if="event.reason">{{ event.reason }}</p></li></ol>
          <div v-else class="timeline-empty">暂无操作记录</div>
      </section>
          </div>
        </div>
      </div>
    </template>

    <ElDialog v-model="pmcDialogVisible" :title="pmcMode === 'CONFIRM' ? 'PMC 确认生产任务' : '退回修改'" width="760px" destroy-on-close>
      <ElAlert v-if="pmcMode === 'CONFIRM' && optionsError" :title="optionsError" type="error" :closable="false"><ElButton link @click="loadPmcOptions">重新加载员工选项</ElButton></ElAlert>
      <div v-if="pmcMode === 'CONFIRM'" class="pmc-form">
        <label><span>生产任务单号</span><ElInput :model-value="task?.task_number" readonly /></label>
        <label><span>跟单员 *</span><ElSelect v-model="pmcForm.follower_ids" multiple filterable :loading="optionsLoading" :disabled="optionsLoading || !!optionsError" placeholder="请选择生产跟单员"><ElOption v-for="employee in options?.employees || task?.followers || []" :key="employee.id" :label="employee.display_name" :value="employee.id" /></ElSelect></label>
        <label><span>交期日期 *</span><ElDatePicker v-model="pmcForm.delivery_date" type="date" value-format="YYYY-MM-DD" /></label>
        <label><span>是否含税 *</span><ElSelect v-model="pmcForm.includes_tax"><ElOption label="含税" :value="true" /><ElOption label="不含税" :value="false" /></ElSelect></label>
        <label v-if="pmcForm.includes_tax"><span>税率 *</span><ElSelect v-model="pmcForm.tax_rate" placeholder="请选择税率"><ElOption v-for="rate in [3, 5, 7]" :key="rate" :label="`${rate}%`" :value="rate" /></ElSelect></label>
        <label><span>订单误差 *</span><ElInput v-model="pmcForm.order_tolerance_percent"><template #append>%</template></ElInput></label>
        <label><span>是否返单 *</span><ElSelect v-model="pmcForm.is_repeat_order"><ElOption label="是" :value="true" /><ElOption label="否" :value="false" /></ElSelect></label>
        <label><span>交货方式 *</span><ElSelect v-model="pmcForm.delivery_method"><ElOption label="一次交货" value="SINGLE" /><ElOption label="分批交货" value="SPLIT" /></ElSelect></label><label><span>计划开始日期 *</span><ElDatePicker v-model="pmcForm.planned_start_date" type="date" value-format="YYYY-MM-DD" /></label><label><span>计划完工日期 *</span><ElDatePicker v-model="pmcForm.planned_end_date" type="date" value-format="YYYY-MM-DD" /></label><label><span>优先级</span><ElSelect v-model="pmcForm.production_priority"><ElOption label="紧急" value="URGENT" /><ElOption label="高" value="HIGH" /><ElOption label="普通" value="NORMAL" /><ElOption label="低" value="LOW" /></ElSelect></label><label><span>生产批号</span><ElInput v-model="pmcForm.production_batch_number" maxlength="50" /></label><label><span>计划员</span><ElSelect v-model="pmcForm.planner_id" :loading="optionsLoading" :disabled="optionsLoading || !!optionsError" clearable filterable><ElOption v-for="employee in options?.employees || []" :key="employee.id" :label="employee.display_name" :value="employee.id" /></ElSelect></label></div>
      <ElInput v-else v-model="pmcForm.reason" type="textarea" :rows="5" maxlength="500" show-word-limit placeholder="请填写需要修改的内容" />
      <template #footer><ElButton @click="pmcDialogVisible = false">取消</ElButton><ElButton type="primary" :loading="actionLoading" :disabled="pmcMode === 'CONFIRM' && (optionsLoading || !options)" @click="decideByPmc">{{ pmcMode === 'CONFIRM' ? '确认通过' : '确认退回' }}</ElButton></template>
    </ElDialog>
    <ProductionTaskScheduleDialog v-model="scheduleDialogVisible" :task="task" @saved="handleScheduleSaved" />
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.task-detail-page { min-width: 0; color: token.$crm-text-primary; font: 13px/20px token.$crm-font-body; }
h1, h2, p, dl { margin: 0; }
h2 { font-size: 16px; line-height: 24px; font-weight: 600; }
dt { color: token.$crm-text-secondary; font-size: 12px; line-height: 18px; }
dd { margin: 2px 0 0; min-width: 0; overflow-wrap: anywhere; }
.detail-heading, .detail-heading__title, .detail-heading__actions { display: flex; align-items: center; flex-wrap: wrap; }
.detail-heading { justify-content: space-between; gap: 12px; min-height: 46px; margin-bottom: 14px; }
.detail-heading__title { gap: 14px; min-width: 0; }
.detail-heading h1 { font: 600 34px/44px token.$crm-font-display; }
.task-number { font-size: 15px; font-weight: 600; overflow-wrap: anywhere; }
.task-status { display: inline-flex; align-items: center; justify-content: center; min-width: 56px; height: 24px; padding: 0 8px; border: 0; border-radius: 999px; background: token.$crm-warning; color: #faf9f5; font-size: 12px; font-weight: 500; line-height: 18px; }
.status-draft { background: token.$crm-neutral; }
.status-in_production, .status-completed { background: token.$crm-success; }
.status-cancelled { background: token.$crm-danger; }
.detail-heading__actions { display: flex; gap: 8px; flex-wrap: wrap; }
.task-detail-page :deep(.el-button) { height: 32px; margin: 0; border-radius: 5px; font-size: 13px; }
.task-detail-page :deep(.el-button:focus-visible), summary:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 2px; }
.summary-bar, .task-sidebar, .detail-card { box-sizing: border-box; border: 1px solid token.$crm-border-default; border-radius: 5px; background: token.$crm-color-surface; }
.summary-bar { display: grid; grid-template-columns: 1.2fr 1fr 1fr; padding: 12px 16px; margin-bottom: 14px; }
.summary-bar > div { display: flex; flex-direction: column; justify-content: center; gap: 4px; min-width: 0; }
.summary-bar > div + div { padding-left: 24px; border-left: 1px solid token.$crm-border-default; }
.summary-bar span { color: token.$crm-text-secondary; font-size: 12px; line-height: 18px; }
.summary-bar strong { font-size: 18px; line-height: 26px; font-weight: 600; overflow-wrap: anywhere; }
.summary-bar .summary-money { font-size: 22px; line-height: 28px; }
.summary-bar, .file-amount, .task-number { font-variant-numeric: tabular-nums; }
.dossier-layout { display: grid; grid-template-columns: 380px minmax(0, 1fr); gap: 14px; align-items: start; }
.task-sidebar, .dossier-main { min-width: 0; }
.basic-card > h2 { padding: 10px 14px; background: token.$crm-color-subtle; border-bottom: 1px solid token.$crm-border-default; border-radius: 4px 4px 0 0; }
.info-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 14px; padding: 14px; }
.info-grid label { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.info-grid label > span { color: token.$crm-text-secondary; font-size: 12px; line-height: 18px; }
.info-grid strong { font-weight: 500; overflow-wrap: anywhere; }
.info-wide { grid-column: 1 / -1; }
.handoff-card { border-top: 1px solid token.$crm-border-default; padding: 14px; }
.section-heading { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.section-heading h2 { font-size: 13px; line-height: 20px; }
.section-heading > span { color: token.$crm-text-secondary; font-size: 12px; }
.status-steps { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); margin: 16px 0 12px; }
.status-steps--single { grid-template-columns: minmax(0, 1fr); }
.status-steps > div { position: relative; display: flex; align-items: center; flex-direction: column; gap: 8px; min-width: 0; color: token.$crm-text-secondary; font-size: 13px; line-height: 20px; text-align: center; }
.status-steps > div:not(:last-child)::after { content: ''; position: absolute; top: 13px; left: calc(50% + 17px); right: calc(-50% + 17px); height: 2px; background: token.$crm-border-default; }
.status-steps i { display: grid; place-items: center; width: 28px; height: 28px; border: 1px solid token.$crm-border-default; border-radius: 50%; background: token.$crm-color-surface; font-style: normal; }
.status-steps i svg { width: 16px; height: 16px; }
.status-steps .is-done i { color: #faf9f5; background: token.$crm-primary; border-color: token.$crm-primary; }
.status-steps .is-done::after { background: token.$crm-primary; }
.status-steps .is-current { color: token.$crm-text-primary; font-weight: 600; }
.status-steps .is-current i { color: token.$crm-primary; border-color: token.$crm-primary; }
.status-branches { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; color: token.$crm-text-secondary; font-size: 12px; }
.status-branches > span + span { border-left: 2px solid token.$crm-border-default; padding-left: 8px; }
.status-branches .is-active { color: token.$crm-warning; border-color: token.$crm-warning; font-weight: 600; }
.status-branches .is-cancelled { color: token.$crm-danger; border-color: token.$crm-danger; }
.side-info > div { display: grid; grid-template-columns: 65px minmax(0, 1fr); gap: 10px; border-top: 1px solid token.$crm-border-default; padding: 8px 0; }
.side-info dd { margin: 0; }
.schedule-dates { display: flex; justify-content: space-between; gap: 12px; border-top: 1px solid token.$crm-border-default; padding-top: 12px; }
.detail-card { padding: 14px 16px; min-width: 0; }
.products-heading { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; }
.product-files { display: flex; flex-direction: column; gap: 10px; }
.product-file { border: 1px solid token.$crm-border-default; border-radius: 5px; min-width: 0; }
.product-file summary { display: flex; align-items: center; gap: 8px; min-height: 32px; padding: 5px 10px; list-style: none; cursor: pointer; border-radius: 4px; }
.product-file summary::-webkit-details-marker { display: none; }
.product-file summary:hover { background: token.$crm-color-row-hover; }
.product-file[open] > summary { border-bottom: 1px solid token.$crm-border-default; border-radius: 4px 4px 0 0; background: #f8f5ef; }
.file-arrow { width: 16px; height: 16px; flex: 0 0 16px; color: token.$crm-text-secondary; }
.product-file[open] .file-arrow { transform: rotate(90deg); color: token.$crm-primary; }
.file-name { min-width: 0; overflow-wrap: anywhere; font-weight: 500; }
.file-code { margin-left: auto; color: token.$crm-text-secondary; overflow-wrap: anywhere; text-align: right; }
.file-content { display: grid; grid-template-columns: 118px minmax(0, 1fr); gap: 20px; padding: 12px 16px; }
.product-figure { min-width: 0; }
.product-photo { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; width: 118px; height: 98px; background: token.$crm-color-subtle; border-radius: 5px; color: token.$crm-text-secondary; font-size: 12px; }
.product-photo img { width: 100%; height: 100%; object-fit: contain; border-radius: inherit; }
.product-photo svg { width: 24px; height: 24px; }
.product-images { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.image-hint { display: block; color: token.$crm-text-secondary; font-size: 11px; line-height: 16px; margin-top: 6px; }
.file-fields { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px 24px; align-content: start; }
.file-fields > div { min-width: 0; }
.file-fields dd { white-space: pre-wrap; }
.file-amount dd { font-weight: 600; }
.file-pack { grid-column: span 2; }
.file-note { grid-column: 1 / -1; }
.bottom-grid { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr); gap: 14px; margin-top: 14px; align-items: start; }
.requirements-card dl { margin-top: 6px; }
.requirements-card dl > div { display: grid; grid-template-columns: 80px minmax(0, 1fr); gap: 10px; padding: 8px 0; border-bottom: 1px solid token.$crm-border-default; }
.requirements-card dl > div:last-child { border-bottom: 0; }
.requirements-card dd { margin: 0; white-space: pre-wrap; }
.sample-required { color: token.$crm-primary; font-weight: 600; }
.timeline { margin: 10px 0 0; padding: 0; list-style: none; }
.timeline li { position: relative; display: grid; grid-template-columns: 132px minmax(0, 1fr); gap: 2px 12px; padding: 0 0 16px 22px; overflow-wrap: anywhere; }
.timeline li::before { content: ''; position: absolute; left: 3px; top: 6px; width: 7px; height: 7px; border-radius: 50%; background: token.$crm-border-strong; }
.timeline li:first-child::before { background: token.$crm-primary; }
.timeline li:not(:last-child)::after { content: ''; position: absolute; left: 6px; top: 15px; bottom: 0; width: 1px; background: token.$crm-border-default; }
.timeline li:last-child { padding-bottom: 0; }
.timeline time, .timeline small { color: token.$crm-text-secondary; font-size: 12px; }
.timeline strong { font-weight: 500; }
.timeline small, .timeline p { grid-column: 2; }
.timeline p { color: token.$crm-text-regular; white-space: pre-wrap; }
.timeline-empty, .products-empty { padding: 24px 0; color: token.$crm-text-secondary; text-align: center; }
.load-error { padding: 48px 16px; display: flex; align-items: center; flex-direction: column; gap: 16px; color: token.$crm-text-secondary; }
.load-error strong { color: token.$crm-text-primary; font-size: 20px; }
.loading-state { padding: 80px 16px 24px; text-align: center; color: token.$crm-text-secondary; }
.pmc-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
.pmc-form label { display: flex; flex-direction: column; gap: 8px; color: token.$crm-text-secondary; font-size: 13px; }
.pmc-form .el-date-editor, .pmc-form .el-select { width: 100%; }
@media (max-width: 1350px) {
  .file-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .bottom-grid { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 1100px) {
  .dossier-layout { grid-template-columns: minmax(0, 1fr); }
  .task-sidebar { display: grid; grid-template-columns: 1fr 1fr; align-items: start; }
  .handoff-card { border-top: 0; border-left: 1px solid token.$crm-border-default; }
}
@media (max-width: 650px) {
  .task-sidebar, .summary-bar, .pmc-form { grid-template-columns: minmax(0, 1fr); }
  .handoff-card { border-left: 0; border-top: 1px solid token.$crm-border-default; }
  .summary-bar { gap: 12px; }
  .summary-bar > div + div { padding: 12px 0 0; border-left: 0; border-top: 1px solid token.$crm-border-default; }
  .file-content { grid-template-columns: minmax(0, 1fr); gap: 12px; padding: 12px; }
  .file-fields { column-gap: 12px; }
  .product-figure { display: flex; flex-wrap: wrap; align-items: start; gap: 8px; }
  .image-hint { flex-basis: 100%; margin-top: 0; }
  .product-images { margin-top: 0; max-width: 118px; }
  .detail-card { padding: 14px 12px; }
  .timeline li { grid-template-columns: minmax(0, 1fr); }
  .timeline small, .timeline p { grid-column: 1; }
  .requirements-card dl > div { grid-template-columns: minmax(0, 1fr); gap: 4px; }
}
@media (max-width: 420px) {
  .file-fields { grid-template-columns: minmax(0, 1fr); }
  .file-pack { grid-column: auto; }
  .status-steps > div { overflow-wrap: anywhere; }
}
</style>
