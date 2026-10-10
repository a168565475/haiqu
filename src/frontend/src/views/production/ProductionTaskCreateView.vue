<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { createProductionOrderFromSalesOrder, fetchProductionTaskOptions, submitProductionTask } from '@/api/productionTasks'
import { fetchSalesOrder, fetchSalesOrders } from '@/api/salesOrders'
import type { ProductionTaskOptions } from '@/types/productionTask'
import type { SalesOrder, SalesOrderBatchLine, SalesOrderDeliveryBatch, SalesOrderListItem } from '@/types/salesOrder'

interface ColorProductionLine {
  key: string
  sourceLineId: string
  productColorId: string
  quantity: number
  specialRequirements: string
  packagingMethod: string
}

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const orderLoading = ref(false)
const submitting = ref(false)
const activeStep = ref(1)
const sourceSearchKeyword = ref('')
const orderChoices = ref<SalesOrderListItem[]>([])
const selectedOrderId = ref('')
const selectedBatchId = ref('')
const order = ref<SalesOrder | null>(null)
const options = ref<ProductionTaskOptions | null>(null)
const colorLines = ref<ColorProductionLine[]>([])
const requestKey = crypto.randomUUID()
let latestOrderRequest = 0
const stepItems = [
  { title: '选择销售订单及交付批次', description: '选择来源订单与需要生产的交付批次' },
  { title: '核对产品与数量', description: '确认产品规格与本次生产数量' },
  { title: '完善生产要求', description: '填写计划、包装及其他生产要求' },
  { title: '保存并提交 PMC', description: '保存草稿或提交 PMC 确认' },
]
const plan = reactive({
  plannedStartDate: '',
  plannedEndDate: '',
  productionPriority: 'NORMAL' as 'URGENT' | 'HIGH' | 'NORMAL' | 'LOW',
  productionBatchNumber: '',
  plannerId: null as string | null,
})

const activeBatches = computed(() => order.value?.delivery_batches.filter((batch) => batch.status === 'ACTIVE') || [])
const selectedBatch = computed(() => activeBatches.value.find((batch) => batch.id === selectedBatchId.value) || null)
const sourceById = computed(() => new Map((selectedBatch.value?.lines || []).map((line) => [line.id, line])))
const totalOrderQuantity = computed(() => (selectedBatch.value?.lines || []).reduce((sum, line) => sum + Number(line.quantity), 0))
const totalAllocatedQuantity = computed(() => (selectedBatch.value?.lines || []).reduce((sum, line) => sum + Number(line.allocated_quantity || 0), 0))
const totalProductionQuantity = computed(() => colorLines.value.reduce((sum, line) => sum + Number(line.quantity || 0), 0))
const totalAvailableQuantity = computed(() => (selectedBatch.value?.lines || []).reduce((sum, line) => sum + Number(line.remaining_quantity || 0), 0))
const toleranceText = computed(() => {
  if (!order.value) return '—'
  const tolerance = Number(order.value.order_tolerance_percent || 0)
  const minimum = totalOrderQuantity.value * (1 - tolerance / 100)
  const maximum = totalOrderQuantity.value * (1 + tolerance / 100)
  const unit = selectedBatch.value?.lines[0]?.unit_code || ''
  return `±${tolerance}%（${formatQuantity(minimum)}～${formatQuantity(maximum)} ${unit}）`
})
const productionSummaryText = computed(() => colorLines.value.map((line) => `${colorName(line.productColorId)} ${formatQuantity(line.quantity)}`).join(' + ') || '—')
const packagingSummaryText = computed(() => [...new Set(colorLines.value
  .map((line) => line.packagingMethod.trim() || salesOrderLine(line)?.packaging_requirements?.trim())
  .filter(Boolean))].join('；') || '未填写')
const productSummaryText = computed(() => [...new Set(colorLines.value.map((line) => sourceLine(line)?.product_name).filter(Boolean))].join('、') || '—')
const sourcePackagingText = computed(() => [...new Set(colorLines.value.map((line) => salesOrderLine(line)?.packaging_requirements?.trim()).filter(Boolean))].join('；') || '销售订单未填写包装要求。')
const sourceProductionText = computed(() => [...new Set(colorLines.value.map((line) => salesOrderLine(line)?.quality_requirements?.trim()).filter(Boolean))].join('；') || '销售订单未填写生产要求。')
function key() {
  return crypto.randomUUID()
}

function apiError(error: unknown): string {
  const response = (error as { response?: { data?: { detail?: string; error?: { message?: string; field_errors?: Record<string, string[]> } } } })?.response?.data
  const fieldError = response?.error?.field_errors ? Object.values(response.error.field_errors).flat()[0] : ''
  return fieldError || response?.error?.message || response?.detail || '操作失败，请稍后重试。'
}

function formatQuantity(value: string | number) {
  return Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

function sourceLine(draft: ColorProductionLine) {
  return sourceById.value.get(draft.sourceLineId)
}

function salesOrderLine(draft: ColorProductionLine) {
  const batchLine = sourceLine(draft)
  return order.value?.lines?.find((line) => line.id === batchLine?.sales_order_line_id)
}

function colorLabel(colorId: string) {
  const color = options.value?.colors.find((item) => item.id === colorId)
  return color ? `${color.color_name} · ${color.color_code}` : '未选择颜色'
}

function colorName(colorId: string) {
  return options.value?.colors.find((item) => item.id === colorId)?.color_name || '未选择颜色'
}

function priorityLabel(value: string) {
  return ({ URGENT: '紧急', HIGH: '高', NORMAL: '普通', LOW: '低' } as Record<string, string>)[value] || value
}

function colorOptionsFor(draft: ColorProductionLine) {
  const used = new Set(colorLines.value
    .filter((item) => item.sourceLineId === draft.sourceLineId && item.key !== draft.key)
    .map((item) => item.productColorId))
  return (options.value?.colors || []).filter((item) => !used.has(item.id) || item.id === draft.productColorId)
}

function draftQuantity(line: SalesOrderBatchLine) {
  const nominalRemaining = Math.max(Number(line.quantity) - Number(line.allocated_quantity || 0), 0)
  return Math.max(0, Math.floor(Math.min(nominalRemaining, Number(line.remaining_quantity || nominalRemaining))))
}

function resetLines(batch: SalesOrderDeliveryBatch | null) {
  colorLines.value = (batch?.lines || [])
    .map((line) => {
      const orderLine = order.value?.lines?.find((item) => item.id === line.sales_order_line_id)
      return {
        key: key(),
        sourceLineId: line.id,
        productColorId: '',
        quantity: draftQuantity(line),
        specialRequirements: orderLine?.quality_requirements || '',
        packagingMethod: orderLine?.packaging_requirements || '',
      }
    })
    .filter((line) => line.quantity > 0)
  plan.productionBatchNumber = batch?.batch_number || ''
  plan.plannedStartDate = ''
  plan.plannedEndDate = ''
}

async function loadOrders(keyword = '') {
  orderLoading.value = true
  try {
    const query = keyword.trim() || undefined
    const [confirmed, fulfilling] = await Promise.all([
      fetchSalesOrders({ status: 'CONFIRMED', page_size: 100, q: query }),
      fetchSalesOrders({ status: 'FULFILLING', page_size: 100, q: query }),
    ])
    const unique = new Map([...confirmed.data, ...fulfilling.data].map((item) => [item.id, item]))
    orderChoices.value = [...unique.values()]
  } finally {
    orderLoading.value = false
  }
}

async function searchSourceOrders() {
  try {
    await loadOrders(sourceSearchKeyword.value)
  } catch (error) {
    ElMessage.error(apiError(error))
  }
}

async function loadOrder(orderId: string, preferredBatchId = '') {
  const requestId = ++latestOrderRequest
  if (!orderId) {
    order.value = null
    selectedBatchId.value = ''
    colorLines.value = []
    return
  }
  loading.value = true
  try {
    const result = await fetchSalesOrder(orderId)
    if (requestId !== latestOrderRequest || selectedOrderId.value !== orderId) return
    if (!['CONFIRMED', 'FULFILLING'].includes(result.data.status)) {
      order.value = null
      selectedBatchId.value = ''
      colorLines.value = []
      ElMessage.warning('该销售订单尚未确认或已结束，不能创建生产任务单。')
      return
    }
    order.value = result.data
    const batch = result.data.delivery_batches.find((item) => item.id === preferredBatchId && item.status === 'ACTIVE')
      || result.data.delivery_batches.find((item) => item.status === 'ACTIVE')
      || null
    selectedBatchId.value = batch?.id || ''
    resetLines(batch)
  } catch (error) {
    if (requestId !== latestOrderRequest) return
    order.value = null
    ElMessage.error(apiError(error))
  } finally {
    if (requestId === latestOrderRequest) loading.value = false
  }
}

async function changeOrder() {
  activeStep.value = 1
  await loadOrder(selectedOrderId.value)
}

async function selectSourceOrder(orderId: string) {
  if (selectedOrderId.value === orderId && order.value) return
  selectedOrderId.value = orderId
  await changeOrder()
}

function sourceProductText(item: SalesOrderListItem) {
  if (order.value?.id !== item.id) return `共 ${item.line_count} 项产品`
  const names = [...new Set((selectedBatch.value?.lines || []).map((line) => line.product_name))]
  return names.join('、') || `共 ${item.line_count} 项产品`
}

function sourceBatchText(item: SalesOrderListItem) {
  if (order.value?.id === item.id && selectedBatch.value) return selectedBatch.value.batch_number
  return `共 ${item.delivery_batch_count} 批`
}

function changeBatch() {
  activeStep.value = 1
  resetLines(selectedBatch.value)
}

function addColorLine(sourceId?: string) {
  const source = sourceId ? sourceById.value.get(sourceId) : selectedBatch.value?.lines[0]
  if (!source) return
  const orderLine = order.value?.lines?.find((item) => item.id === source.sales_order_line_id)
  colorLines.value.push({
    key: key(),
    sourceLineId: source.id,
    productColorId: '',
    quantity: 1,
    specialRequirements: orderLine?.quality_requirements || '',
    packagingMethod: orderLine?.packaging_requirements || '',
  })
}

function removeColorLine(index: number) {
  colorLines.value.splice(index, 1)
}

function validateStepOne() {
  if (!order.value || !selectedBatch.value) {
    ElMessage.warning('请选择已确认的销售订单和有效交付批次。')
    return false
  }
  return true
}

function validateLines() {
  if (!colorLines.value.length) {
    ElMessage.warning('当前批次没有可安排的产品，请检查已分配数量。')
    return false
  }
  const totals = new Map<string, number>()
  const pairs = new Set<string>()
  for (const [index, line] of colorLines.value.entries()) {
    if (!sourceById.value.has(line.sourceLineId)) {
      ElMessage.warning(`第 ${index + 1} 行的来源产品无效。`)
      return false
    }
    if (!line.productColorId) {
      ElMessage.warning(`第 ${index + 1} 行请选择颜色。`)
      return false
    }
    if (!Number.isInteger(line.quantity) || line.quantity < 1) {
      ElMessage.warning(`第 ${index + 1} 行生产数量必须是大于 0 的整数。`)
      return false
    }
    const pair = `${line.sourceLineId}:${line.productColorId}`
    if (pairs.has(pair)) {
      ElMessage.warning(`第 ${index + 1} 行与已有产品颜色重复。`)
      return false
    }
    pairs.add(pair)
    totals.set(line.sourceLineId, (totals.get(line.sourceLineId) || 0) + line.quantity)
  }
  for (const [sourceId, quantity] of totals) {
    const source = sourceById.value.get(sourceId)
    if (source && quantity > Number(source.remaining_quantity)) {
      ElMessage.warning(`${source.product_name} 本次合计不能超过可安排数量 ${formatQuantity(source.remaining_quantity)} ${source.unit_code}。`)
      return false
    }
  }
  return true
}

function validatePlan() {
  if (Boolean(plan.plannedStartDate) !== Boolean(plan.plannedEndDate)) {
    ElMessage.warning('计划开始和计划完工日期需同时填写或同时留空。')
    return false
  }
  if (plan.plannedStartDate && plan.plannedEndDate < plan.plannedStartDate) {
    ElMessage.warning('计划完工日期不能早于计划开始日期。')
    return false
  }
  return true
}

function nextStep() {
  if (activeStep.value === 1 && !validateStepOne()) return
  if (activeStep.value === 2 && !validateLines()) return
  if (activeStep.value === 3 && !validatePlan()) return
  activeStep.value = Math.min(4, activeStep.value + 1)
}

async function save(submitToPmc: boolean) {
  if (!validateStepOne() || !validateLines() || !validatePlan() || !selectedBatch.value) return
  submitting.value = true
  let createdId = ''
  try {
    const created = await createProductionOrderFromSalesOrder({
      request_key: requestKey,
      delivery_batch_id: selectedBatch.value.id,
      lines: colorLines.value.map((line) => {
        const orderLine = salesOrderLine(line)
        return {
          delivery_batch_line_id: line.sourceLineId,
          product_color_id: line.productColorId,
          quantity: line.quantity,
          special_requirements: line.specialRequirements.trim() || orderLine?.quality_requirements || '',
          packaging_method: line.packagingMethod.trim() || orderLine?.packaging_requirements || '',
        }
      }),
      planned_start_date: plan.plannedStartDate || null,
      planned_end_date: plan.plannedEndDate || null,
      production_priority: plan.productionPriority,
      production_batch_number: plan.productionBatchNumber.trim(),
      planner_id: plan.plannerId,
    })
    createdId = created.data.id
    if (submitToPmc) {
      try {
        const submitted = await submitProductionTask(created.data.id, created.etag)
        ElMessage.success(`生产任务单 ${submitted.data.task_number} 已提交 PMC。`)
      } catch (error) {
        ElMessage.warning(`生产任务单已保存为草稿，但提交 PMC 失败：${apiError(error)}`)
      }
    } else {
      ElMessage.success(`生产任务单 ${created.data.task_number} 已保存为草稿。`)
    }
    await router.replace({ name: 'production-task-detail', params: { taskId: created.data.id } })
  } catch (error) {
    if (!createdId) ElMessage.error(apiError(error))
  } finally {
    submitting.value = false
  }
}

watch(selectedBatchId, () => {
  if (activeStep.value > 1) activeStep.value = 1
})

onMounted(async () => {
  loading.value = true
  try {
    const [taskOptions] = await Promise.all([fetchProductionTaskOptions(), loadOrders()])
    options.value = taskOptions
    const queryOrderId = typeof route.query.sales_order_id === 'string' ? route.query.sales_order_id : ''
    const queryBatchId = typeof route.query.delivery_batch_id === 'string' ? route.query.delivery_batch_id : ''
    selectedOrderId.value = queryOrderId || orderChoices.value[0]?.id || ''
    if (selectedOrderId.value) await loadOrder(selectedOrderId.value, queryBatchId)
  } catch (error) {
    ElMessage.error(apiError(error))
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section v-loading="loading" class="production-create-page">
    <header class="page-heading">
      <div class="heading-title"><h1>新增生产任务单</h1><span>未保存</span></div>
      <p>从已确认销售订单创建；每个颜色明细独立维护数量与 BOM。</p>
    </header>

    <ol class="steps" aria-label="新增生产任务单步骤">
      <li v-for="(item, index) in stepItems" :key="item.title" :class="{ active: activeStep === index + 1, done: activeStep > index + 1 }">
        <b>{{ activeStep > index + 1 ? '✓' : index + 1 }}</b>
        <div><span>{{ item.title }}</span><small>{{ item.description }}</small></div>
      </li>
    </ol>

    <div class="content-grid" :class="{ 'is-source-step': activeStep === 1 }">
      <main class="form-card">
        <template v-if="activeStep === 1">
          <div class="section-title"><div><h2>选择已确认销售订单</h2><p>只显示已确认或履约中的销售订单；选择后核对可安排数量。</p></div></div>
          <el-input v-model="sourceSearchKeyword" class="source-search" clearable placeholder="搜索销售订单号、客户或产品" @keyup.enter="searchSourceOrders" @clear="searchSourceOrders" />
          <el-table v-loading="orderLoading" :data="orderChoices" border class="source-order-table" empty-text="没有符合条件的销售订单">
            <el-table-column prop="order_number" label="销售订单号" width="190" />
            <el-table-column prop="customer_name" label="客户" min-width="190" show-overflow-tooltip />
            <el-table-column label="产品" min-width="220" show-overflow-tooltip><template #default="{ row }">{{ sourceProductText(row) }}</template></el-table-column>
            <el-table-column label="交付批次" width="190">
              <template #default="{ row }">
                <el-select v-if="order?.id === row.id && activeBatches.length > 1" v-model="selectedBatchId" size="small" @click.stop @change="changeBatch">
                  <el-option v-for="batch in activeBatches" :key="batch.id" :label="batch.batch_number" :value="batch.id" />
                </el-select>
                <span v-else>{{ sourceBatchText(row) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="交付日期" width="150"><template #default="{ row }">{{ order?.id === row.id ? selectedBatch?.planned_delivery_date : (row.next_delivery_date || '—') }}</template></el-table-column>
            <el-table-column label="可分配数量" width="160" align="right"><template #default="{ row }">{{ order?.id === row.id ? `${formatQuantity(totalAvailableQuantity)} ${selectedBatch?.lines[0]?.unit_code || ''}` : '—' }}</template></el-table-column>
            <el-table-column label="操作" width="150" align="center"><template #default="{ row }"><el-button link type="primary" @click="selectSourceOrder(row.id)">{{ order?.id === row.id ? '已选择' : '选择该订单' }}</el-button></template></el-table-column>
          </el-table>
          <el-alert class="source-tip" type="info" :closable="false" title="仅能选择已确认订单的可用交付批次，后续核对本次生产数量。" />
        </template>

        <template v-else-if="activeStep === 2">
          <div class="section-title compact"><div><h2>来源订单信息</h2></div></div>
          <div class="source-facts">
            <div><span>销售订单号</span><strong>{{ order?.order_number }}</strong></div><div><span>客户名称</span><strong>{{ order?.customer_name }}</strong></div>
            <div><span>交付批次</span><strong>{{ selectedBatch?.batch_number }}</strong></div><div><span>要求交付日期</span><strong>{{ selectedBatch?.planned_delivery_date }}</strong></div>
            <div><span>客户下单总量</span><strong>{{ formatQuantity(totalOrderQuantity) }} {{ selectedBatch?.lines[0]?.unit_code }}</strong></div><div><span>已分配生产量</span><strong>{{ formatQuantity(totalAllocatedQuantity) }} {{ selectedBatch?.lines[0]?.unit_code }}</strong></div>
            <div><span>本次生产量</span><strong>{{ formatQuantity(totalProductionQuantity) }} {{ selectedBatch?.lines[0]?.unit_code }}</strong></div><div><span>客户数量容差</span><strong>{{ toleranceText }}</strong></div>
          </div>
          <div class="section-title"><div><h2>产品与数量</h2><p>同一产品可拆分多个颜色；每行将生成独立产品明细和独立 BOM。</p></div></div>
          <el-table :data="colorLines" border class="product-table">
            <el-table-column label="产品图片" width="105"><template #default><div class="product-image-placeholder">暂无图片</div></template></el-table-column>
            <el-table-column label="产品编码" width="120"><template #default="{ row }">{{ sourceLine(row)?.product_number }}</template></el-table-column>
            <el-table-column label="产品名称 / 规格" min-width="230"><template #default="{ row }"><strong>{{ sourceLine(row)?.product_name }}</strong><small>{{ salesOrderLine(row)?.specification_snapshot || '未填写规格' }}</small></template></el-table-column>
            <el-table-column label="颜色 *" width="180"><template #default="{ row, $index }"><el-select v-model="row.productColorId" filterable placeholder="请选择颜色"><el-option v-for="color in colorOptionsFor(row)" :key="color.id" :label="`${color.color_name} · ${color.color_code}`" :value="color.id" /></el-select><div class="color-line-actions"><button type="button" @click="addColorLine(row.sourceLineId)">添加颜色</button><button type="button" class="danger" @click="removeColorLine($index)">移除</button></div></template></el-table-column>
            <el-table-column label="销售订单数量" width="145"><template #default="{ row }">{{ formatQuantity(sourceLine(row)?.quantity || 0) }} {{ sourceLine(row)?.unit_code }}</template></el-table-column>
            <el-table-column label="已配生产量" width="130"><template #default="{ row }">{{ formatQuantity(sourceLine(row)?.allocated_quantity || 0) }} {{ sourceLine(row)?.unit_code }}</template></el-table-column>
            <el-table-column label="本次生产数量 *" width="190"><template #default="{ row }"><el-input-number v-model="row.quantity" :min="1" :max="Math.floor(Number(sourceLine(row)?.remaining_quantity || 0))" :precision="0" :controls="false" /><small>可安排 {{ formatQuantity(sourceLine(row)?.remaining_quantity || 0) }} {{ sourceLine(row)?.unit_code }}</small></template></el-table-column>
          </el-table>
          <div class="totals"><strong>合计</strong><span>销售订单 <b>{{ formatQuantity(totalOrderQuantity) }}</b></span><span>已分配 <b>{{ formatQuantity(totalAllocatedQuantity) }}</b></span><span>本次生产 <b>{{ formatQuantity(totalProductionQuantity) }}</b></span></div>
          <h3>来源生产要求（下一步完善）</h3>
          <div class="source-requirements"><article><strong>包装要求</strong><p>{{ sourcePackagingText }}</p></article><article><strong>生产要求</strong><p>{{ sourceProductionText }}</p></article></div>
        </template>

        <template v-else-if="activeStep === 3">
          <div class="section-title"><div><h2>生产安排</h2><p>草稿可暂不填写计划日期，提交 PMC 前请核对安排信息。</p></div></div>
          <div class="plan-grid">
            <label><span>计划员</span><el-select v-model="plan.plannerId" clearable filterable><el-option v-for="item in options?.employees || []" :key="item.id" :label="item.display_name" :value="item.id" /></el-select></label>
            <label><span>生产优先级</span><el-select v-model="plan.productionPriority"><el-option label="紧急" value="URGENT" /><el-option label="高" value="HIGH" /><el-option label="普通" value="NORMAL" /><el-option label="低" value="LOW" /></el-select></label>
            <label><span>要求交付日期</span><el-input :model-value="selectedBatch?.planned_delivery_date || ''" readonly /></label>
            <label><span>计划开始</span><el-date-picker v-model="plan.plannedStartDate" type="date" value-format="YYYY-MM-DD" /></label>
            <label><span>计划完工</span><el-date-picker v-model="plan.plannedEndDate" type="date" value-format="YYYY-MM-DD" /></label>
            <label><span>生产批次号</span><el-input v-model="plan.productionBatchNumber" maxlength="100" /></label>
          </div>
          <h3>逐颜色生产要求</h3>
          <div v-for="line in colorLines" :key="line.key" class="requirement-row">
            <header><strong>{{ sourceLine(line)?.product_name }} · {{ colorLabel(line.productColorId) }}</strong><span>{{ formatQuantity(line.quantity) }} {{ sourceLine(line)?.unit_code }}</span></header>
            <label><span>包装要求</span><el-input v-model="line.packagingMethod" type="textarea" :rows="2" placeholder="留空时沿用销售订单包装要求" maxlength="2000" show-word-limit /></label>
            <label><span>生产要求</span><el-input v-model="line.specialRequirements" type="textarea" :rows="2" placeholder="留空时沿用销售订单质量要求" maxlength="2000" show-word-limit /></label>
          </div>
          <p class="production-detail-note"><strong>产前样要求</strong><span>按来源销售订单的产前样要求执行。</span></p>
          <el-alert type="info" :closable="false" title="计划开工与完工日期由 PMC 确认后最终确定。" />
        </template>

        <template v-else>
          <div class="section-title"><div><h2>核对本次生产任务</h2><p>保存草稿可继续修改；提交后进入待 PMC 确认。</p></div></div>
          <dl class="review-summary">
            <dt>来源订单</dt><dd>{{ order?.order_number }} · {{ selectedBatch?.batch_number }}</dd>
            <dt>客户</dt><dd>{{ order?.customer_name }}</dd>
            <dt>产品</dt><dd>{{ productSummaryText }}</dd>
            <dt>生产数量</dt><dd>{{ productionSummaryText }}，合计 {{ formatQuantity(totalProductionQuantity) }} {{ selectedBatch?.lines[0]?.unit_code }}</dd>
            <dt>要求交期</dt><dd>{{ selectedBatch?.planned_delivery_date }}</dd>
            <dt>生产安排</dt><dd>{{ priorityLabel(plan.productionPriority) }} · {{ plan.plannedStartDate || '计划开始待 PMC 确认' }} 至 {{ plan.plannedEndDate || '计划完工待 PMC 确认' }}</dd>
            <dt>包装要求</dt><dd>{{ packagingSummaryText }}</dd>
          </dl>
          <el-alert type="info" :closable="false" title="保存草稿可继续修改；提交后进入待 PMC 确认。" />
        </template>

        <footer class="form-actions">
          <span class="action-spacer" />
          <template v-if="activeStep === 1"><el-button @click="router.push({ name: 'production-tasks' })">返回列表</el-button><el-button type="primary" @click="nextStep">选择并继续</el-button></template>
          <template v-else-if="activeStep === 2"><el-button :loading="submitting" @click="save(false)">保存草稿</el-button><el-button type="primary" :disabled="submitting" @click="nextStep">下一步</el-button></template>
          <template v-else-if="activeStep === 3"><el-button :disabled="submitting" @click="activeStep--">上一步</el-button><el-button :loading="submitting" @click="save(false)">保存草稿</el-button><el-button type="primary" :disabled="submitting" @click="nextStep">下一步</el-button></template>
          <template v-else><el-button :disabled="submitting" @click="activeStep--">上一步</el-button><el-button :loading="submitting" @click="save(false)">保存草稿</el-button><el-button type="primary" :loading="submitting" @click="save(true)">保存并提交 PMC</el-button></template>
        </footer>
      </main>

      <aside v-if="activeStep > 1" class="summary-card">
        <header><h2>来源订单明细</h2><el-button v-if="order" link type="primary" @click="router.push({ name: 'sales-order-detail', params: { orderId: order.id } })">查看销售订单 ›</el-button></header>
        <dl><dt>销售订单号</dt><dd>{{ order?.order_number || '—' }}</dd><dt>客户名称</dt><dd>{{ order?.customer_name || '—' }}</dd><dt>交付批次</dt><dd>{{ selectedBatch?.batch_number || '—' }}</dd><dt>要求交期</dt><dd>{{ selectedBatch?.planned_delivery_date || '—' }}</dd><dt>下单日期</dt><dd>{{ order?.order_date || '—' }}</dd></dl>
        <div class="summary-divider" />
        <dl><dt>订单产品总数</dt><dd>{{ formatQuantity(totalOrderQuantity) }}</dd><dt>已分配生产量</dt><dd>{{ formatQuantity(totalAllocatedQuantity) }}</dd><dt>本次生产量</dt><dd class="accent">{{ formatQuantity(totalProductionQuantity) }}</dd><dt>客户数量容差</dt><dd>{{ toleranceText }}</dd></dl>
        <div class="summary-divider" />
        <h3>客户备注</h3><p class="customer-note">{{ selectedBatch?.notes || '暂无客户备注。' }}</p>
      </aside>
    </div>
  </section>
</template>

<style scoped lang="scss">
.production-create-page {
  box-sizing: border-box;
  min-height: 0;
  padding: 26px 28px 36px;
  background: var(--erp-page-background);
  color: #202124;
  font-family: "Noto Sans SC", "Microsoft YaHei", sans-serif;
  --el-color-primary: #d7491c;
}
.page-heading { display: flex; height: 46px; align-items: flex-start; justify-content: space-between; margin-bottom: 13px; }
.page-heading h1 { margin: 0; font-family: "Noto Serif SC", "Songti SC", serif; font-size: 32px; line-height: 46px; }
.page-heading p { margin: 8px 0 0; color: #68686a; font-size: 13px; }
.heading-title { display: flex; align-items: center; gap: 14px; }
.heading-title span { padding: 5px 13px; border-radius: 4px; background: #fbead3; color: #b86613; font-size: 13px; }
.steps { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; height: 69px; margin: 0 0 17px; padding: 0; list-style: none; }
.steps li { position: relative; display: flex; align-items: flex-start; gap: 16px; color: #888; }
.steps li:not(:last-child)::after { position: absolute; top: 16px; right: -8px; left: 230px; height: 1px; background: #d8d2c7; content: ""; }
.steps b { z-index: 1; display: grid; width: 32px; height: 32px; flex: none; place-items: center; border-radius: 50%; background: #c5c3bd; color: #fff; font-size: 14px; }
.steps li > div { min-width: 0; padding-top: 4px; }
.steps span, .steps small { display: block; }
.steps span { color: inherit; font-size: 14px; font-weight: 600; line-height: 20px; }
.steps small { margin-top: 5px; color: #888; font-size: 12px; line-height: 18px; white-space: nowrap; }
.steps .active, .steps .done { color: #202124; }
.steps .active b { background: #d7491c; }
.steps .done b { background: #a99f8d; }
.steps .done small { color: #68686a; }
.content-grid { display: grid; grid-template-columns: minmax(0, 1fr) 398px; gap: 14px; align-items: start; }
.content-grid.is-source-step { grid-template-columns: 1fr; }
.form-card, .summary-card { box-sizing: border-box; min-height: calc(100vh - 271px); border: 1px solid #e3dfd7; border-radius: 5px; background: #fdfcf9; }
.form-card { display: flex; flex-direction: column; padding: 20px 20px 0; overflow: hidden; }
.section-title { display: flex; flex: none; align-items: flex-start; justify-content: space-between; margin-bottom: 16px; }
.section-title.compact { margin-bottom: 10px; }
.section-title h2, .summary-card h2 { margin: 0; font: 700 20px/1.5 "Noto Sans SC", sans-serif; }
.section-title p { margin: 3px 0 0; color: #68686a; font-size: 13px; }
.source-search { width: 600px; margin-bottom: 16px; }
.source-search :deep(.el-input__wrapper) { min-height: 38px; border-radius: 5px; }
.source-order-table { width: 100%; }
.source-order-table :deep(.el-table__header-wrapper th) { height: 38px; padding: 0; background: #efebe3; color: #68686a; font-size: 12px; font-weight: 500; }
.source-order-table :deep(.el-table__body tr) { height: 72px; }
.source-order-table :deep(.el-table__cell) { padding: 0; }
.source-order-table :deep(.cell) { padding: 0 14px; }
.source-order-table :deep(.el-select) { width: 100%; }
.source-tip { margin-top: 16px; }
.source-facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); flex: none; margin-bottom: 16px; border-top: 1px solid #e3dfd7; border-left: 1px solid #e3dfd7; }
.source-facts div { box-sizing: border-box; min-height: 60px; padding: 9px 12px; border-right: 1px solid #e3dfd7; border-bottom: 1px solid #e3dfd7; background: #f2f3f4; }
.source-facts span, .source-facts strong { display: block; }
.source-facts span { margin-bottom: 5px; color: #68686a; font-size: 12px; }
.source-facts strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.product-table { flex: none; }
.product-table :deep(.el-table__header-wrapper th) { height: 42px; padding: 0; background: #efebe3; color: #68686a; font-size: 12px; font-weight: 500; }
.product-table :deep(.el-table__body tr) { height: 86px; }
.product-table :deep(.el-table__cell) { padding: 0; }
.product-table :deep(.cell) { display: flex; flex-direction: column; gap: 5px; padding: 7px 12px; }
.product-table small { display: block; color: #68686a; font-size: 11px; }
.product-table :deep(.el-input-number), .product-table :deep(.el-select) { width: 100%; }
.product-image-placeholder { display: grid; width: 68px; height: 68px; place-items: center; border: 1px solid #e3dfd7; border-radius: 4px; background: #f2f3f4; color: #968f84; font-size: 11px; }
.color-line-actions { display: flex; gap: 10px; }
.color-line-actions button { padding: 0; border: 0; color: #287abe; background: transparent; font-size: 11px; cursor: pointer; }
.color-line-actions button.danger { color: #b53333; }
.totals { display: flex; flex: none; align-items: center; justify-content: flex-end; gap: 38px; min-height: 50px; padding: 0 16px; border: 1px solid #e3dfd7; border-top: 0; background: #efebe3; font-size: 13px; }
.totals > strong { margin-right: auto; }
.totals b { margin-left: 8px; font-size: 14px; }
.form-card h3, .summary-card h3 { margin: 18px 0 10px; font-size: 15px; }
.source-requirements { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.source-requirements article { box-sizing: border-box; min-height: 88px; padding: 13px 14px; border: 1px solid #e3dfd7; border-radius: 5px; background: #f2f3f4; }
.source-requirements p { margin: 12px 0 0; color: #4f4e4a; font-size: 13px; line-height: 20px; }
.plan-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; margin-bottom: 16px; }
.plan-grid label > span, .requirement-row label > span { display: block; margin-bottom: 7px; font-size: 13px; font-weight: 600; }
.plan-grid :deep(.el-select), .plan-grid :deep(.el-date-editor), .plan-grid :deep(.el-input) { width: 100%; }
.requirement-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 12px; padding: 12px 14px; border: 1px solid #e3dfd7; border-radius: 5px; background: #f7f5f0; }
.requirement-row header { grid-column: 1 / -1; display: flex; justify-content: space-between; }
.requirement-row header span { color: #68686a; font-size: 13px; }
.production-detail-note { display: flex; flex-direction: column; gap: 8px; margin: 14px 0; font-size: 13px; }
.production-detail-note span { color: #68686a; }
.review-summary { display: grid; grid-template-columns: 120px minmax(0, 1fr); gap: 16px 18px; margin: 0 0 24px; font-size: 14px; line-height: 22px; }
.review-summary dt { color: #68686a; }
.review-summary dd { margin: 0; font-weight: 500; overflow-wrap: anywhere; }
.form-actions { display: flex; flex: none; align-items: center; gap: 10px; margin: auto -20px 0; padding: 14px 20px; border-top: 1px solid #e3dfd7; }
.form-actions :deep(.el-button) { min-width: 110px; height: 36px; margin: 0; border-radius: 5px; }
.form-actions :deep(.el-button--primary) { min-width: 140px; }
.form-actions :deep(.el-button--primary:not(.is-disabled)) { border-color: #d7491c; background: #d7491c; color: #fff; }
.form-actions :deep(.el-button--primary:not(.is-disabled):hover) { border-color: #c84e28; background: #c84e28; }
.action-spacer { flex: 1; }
.summary-card { position: sticky; top: 16px; padding: 18px 18px 22px; }
.summary-card header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18px; }
.summary-card dl { display: grid; grid-template-columns: 118px 1fr; gap: 12px 8px; margin: 0; font-size: 13px; }
.summary-card dt { color: #68686a; }
.summary-card dd { margin: 0; font-weight: 500; overflow-wrap: anywhere; }
.summary-card dd.accent { color: #d7491c; font-weight: 700; }
.summary-divider { height: 1px; margin: 20px 0; background: #e3dfd7; }
.customer-note { min-height: 70px; margin: 0; padding: 12px; border: 1px solid #e3dfd7; border-radius: 4px; background: #f2f3f4; color: #68686a; font-size: 13px; line-height: 1.7; }
@media (max-width: 1200px) {
  .content-grid { grid-template-columns: 1fr; }
  .summary-card { position: static; min-height: auto; }
  .source-facts { grid-template-columns: repeat(2, 1fr); }
}
</style>
