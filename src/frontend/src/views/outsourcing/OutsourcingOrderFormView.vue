<script setup lang="ts">
import { decimalUnits, outsourcingPlan } from '@/utils/outsourcingQuantities' 
import { computed, onMounted, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import { createOutsourcingFactory, createOutsourcingOrder, fetchOutsourcingOptions, fetchOutsourcingSourceBom, fetchOutsourcingSourcePlans } from '@/api/outsourcing'
import { fetchP4Source } from '@/api/metalProcessingP4'
import type { P4Source } from '@/types/metalProcessingP4'
import FactoryFormDialog from '@/components/outsourcing/FactoryFormDialog.vue'
import OutsourcingMaterialDialog from '@/components/outsourcing/OutsourcingMaterialDialog.vue'
import OutsourcingProcessingDialog from '@/components/outsourcing/OutsourcingProcessingDialog.vue'
import OutsourcingSourcePlanDialog from '@/components/outsourcing/OutsourcingSourcePlanDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type {
  OutsourcingFactoryInput,
  OutsourcingOrderCreateInput,
  OutsourcingOptions,
  OutsourcingProcessingCandidate,
  OutsourcingSourceBomContext,
  OutsourcingSourcePlan,
  OutsourcingSourceProduct,
  SelectedOutsourcingMaterialRow,
  SelectedOutsourcingProcessingRow,
} from '@/types/outsourcing'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const options = ref<OutsourcingOptions | null>(null)
const selectedMetalSource = ref<P4Source | null>(null)
const metalSourceId = computed(() => typeof route.query.source_issue_line_id === 'string' ? route.query.source_issue_line_id : '')
const metalScheduleProductId = computed(() => {
  const plan = selectedMetalSource.value?.source_snapshot?.plan_source as { schedule_product_id?: unknown } | undefined
  return typeof plan?.schedule_product_id === 'string' ? plan.schedule_product_id : ''
})
const craftId = ref('')
const selectedPlan = ref<OutsourcingSourcePlan | null>(null)
const selectedProducts = ref<OutsourcingSourceProduct[]>([])
const activeProductId = ref('')
const sourceDialogVisible = ref(false)
const deliveryDate = ref('')
const loading = ref(false)
const loadError = ref('')
const sourceLoading = ref(false)
const bomLoading = ref(false)
const processingDialogVisible = ref(false)
const materialDialogVisible = ref(false)
const factoryDialogVisible = ref(false)
const factorySaving = ref(false)
const saving = ref(false)
const bomContexts = ref<Record<string, OutsourcingSourceBomContext>>({})
const processingRowsByProduct = ref<Record<string, SelectedOutsourcingProcessingRow[]>>({})
const materialRowsByProduct = ref<Record<string, SelectedOutsourcingMaterialRow[]>>({})
const hoveredProcessingRow = ref<SelectedOutsourcingProcessingRow | null>(null)
const processingHintStyle = ref<Record<string, string>>({})
let latestSourceRequest = 0
let latestBomRequest = 0
let lastSubmissionFingerprint = ''
let clientRequestId = ''

const selectedCraft = computed(() => options.value?.crafts.find((item) => item.id === craftId.value) || null)
const craftTone = computed(() => ({
  SEWING: 'sewing',
  CUTTING: 'cutting',
  POWDER_COATING: 'spray',
  SCREEN_PRINTING: 'printing',
} as Record<string, string>)[selectedCraft.value?.outsourcing_code || ''] || 'neutral')
const selectedProduct = computed(() => selectedProducts.value.find(item => item.id === activeProductId.value) || selectedProducts.value[0] || null)
const selectedProductIds = computed(() => selectedProducts.value.map(item => item.id))
const selectedBomContext = computed(() => selectedProduct.value ? bomContexts.value[selectedProduct.value.id] || null : null)
const processingRows = computed(() => selectedProduct.value ? processingRowsByProduct.value[selectedProduct.value.id] || [] : [])
const materialRows = computed(() => selectedProduct.value ? materialsForProduct(selectedProduct.value.id) : [])
const canCreateOrder = computed(() => auth.user?.is_superuser || auth.hasPermission('outsourcing.add_outsourcingorder'))
const canCreateFactory = computed(() => auth.user?.is_superuser || auth.hasPermission('outsourcing.add_outsourcingfactory'))
const availableFactories = computed(() => (options.value?.factories || []).filter(
  factory => factory.crafts.some(craft => craft.id === craftId.value),
))
const materialCardTitle = computed(() => selectedCraft.value?.outsourcing_code === 'POWDER_COATING'
  ? '原材料发料 · 管材 / 五金'
  : '原材料发料 · 面料 / 辅料')
const plannedAmount = computed(() => Object.values(processingRowsByProduct.value).flat().reduce(
  (sum, row) => sum + Number(outsourcingPlan(row.input_quantity, row.conversion_snapshot).output || 0) * Number(row.unit_price || 0), 0,
))
const plannedDateRange = computed(() => {
  if (!selectedPlan.value) return ''
  const { planned_start_date: start, planned_end_date: end } = selectedPlan.value
  if (start && end) return `${start} 至 ${end}`
  return start || end || '—'
})
const readyToSave = computed(() => Boolean(
  canCreateOrder.value
  && !loading.value && !sourceLoading.value && !bomLoading.value && !loadError.value
  && (!metalSourceId.value || selectedMetalSource.value)
  && selectedPlan.value
  && craftId.value
  && deliveryDate.value
  && selectedProducts.value.length
  && selectedProducts.value.every(product => {
    const context = bomContexts.value[product.id]
    const productProcessingRows = processingRowsByProduct.value[product.id] || []
    const productMaterialRows = materialsForProduct(product.id)
    return Boolean(
      context?.bom
      && productProcessingRows.length
      && productMaterialRows.length
      && productProcessingRows.every(row => row.factory_id && !outsourcingPlan(row.input_quantity, row.conversion_snapshot).error && row.unit_price >= 0)
      && productMaterialRows.every(row => row.factory_id && row.processing_bom_line_id && Number(row.planned_issue_quantity) > 0),
    )
  }),
))

function errorText(error: unknown, fallback: string): string {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : fallback
  const data = error.response?.data as { error?: { message?: string }; detail?: string } | undefined
  return data?.error?.message || data?.detail || fallback
}

function quantityText(value: number | string | null): string {
  if (value === null || value === undefined || value === '') return '—'
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
}

async function loadOptions(): Promise<void> {
  loadError.value = ''
  loading.value = true
  try {
    selectedMetalSource.value = null
    if (metalSourceId.value) {
      const source = await fetchP4Source(metalSourceId.value)
      if (source.status !== 'OPEN' || source.available_pieces <= 0 || !source.etag) throw new Error('所选金工来源当前没有可外发数量，请返回待外发材料重新选择。')
      selectedMetalSource.value = source
      if (!metalScheduleProductId.value) throw new Error('所选金工来源缺少排产记录，不能继续新建。')
    }
    options.value = await fetchOutsourcingOptions()
    const queryCraftId = typeof route.query.craft_id === 'string' ? route.query.craft_id : ''
    if (selectedMetalSource.value) {
      const metalCraft = options.value.crafts.find(item => item.outsourcing_code === 'POWDER_COATING')
      if (!metalCraft) throw new Error('当前没有可用的喷塑工艺，无法为所选金工来源新建外发单。')
      craftId.value = metalCraft.id
    } else if (queryCraftId && options.value.crafts.some((item) => item.id === queryCraftId)) craftId.value = queryCraftId
  } catch (error) {
    loadError.value = errorText(error, '外发单基础选项加载失败。')
  } finally {
    loading.value = false
  }
}

async function loadDeepLinkedSource(): Promise<void> {
  const requestNumber = ++latestSourceRequest
  const requestedCraftId = craftId.value
  const requestedProductId = metalScheduleProductId.value || (typeof route.query.schedule_product_id === 'string' ? route.query.schedule_product_id : '')
  if (!requestedCraftId || !requestedProductId) return
  sourceLoading.value = true
  try {
    const result = await fetchOutsourcingSourcePlans({
      craft_id: requestedCraftId,
      schedule_product_id: requestedProductId,
      page: 1,
      page_size: 1,
    })
    if (requestNumber !== latestSourceRequest || craftId.value !== requestedCraftId) return
    for (const plan of result.data) {
      const product = plan.products.find((item) => item.id === requestedProductId)
      if (product) {
        selectedPlan.value = plan
        selectedProducts.value = [product]
        activeProductId.value = product.id
        return
      }
    }
    ElMessage.warning('指定排产产品已失效或不包含所选厂外工艺。')
  } catch (error) {
    if (requestNumber !== latestSourceRequest || craftId.value !== requestedCraftId) return
    loadError.value = errorText(error, '排产来源加载失败。')
  } finally {
    if (requestNumber === latestSourceRequest) sourceLoading.value = false
  }
}

watch(craftId, async () => {
  latestBomRequest += 1
  selectedPlan.value = null
  selectedProducts.value = []
  activeProductId.value = ''
  bomContexts.value = {}
  processingRowsByProduct.value = {}
  materialRowsByProduct.value = {}
  await loadDeepLinkedSource()
})

watch([() => selectedProduct.value?.id || '', craftId], ([productId, selectedCraftId]) => {
  hoveredProcessingRow.value = null
  if (productId && selectedCraftId) void loadBomContext(productId, selectedCraftId)
})

async function loadBomContext(productId: string, selectedCraftId: string): Promise<void> {
  loadError.value = ''
  const requestNumber = ++latestBomRequest
  bomLoading.value = true
  try {
    const context = await fetchOutsourcingSourceBom(productId, selectedCraftId)
    if (requestNumber !== latestBomRequest || activeProductId.value !== productId || craftId.value !== selectedCraftId) return
    bomContexts.value = { ...bomContexts.value, [productId]: context }
  } catch (error) {
    if (requestNumber !== latestBomRequest) return
    loadError.value = errorText(error, '产品 BOM 加载失败。')
  } finally {
    if (requestNumber === latestBomRequest) bomLoading.value = false
  }
}

async function retryLoad(): Promise<void> {
  await loadOptions()
  if (loadError.value) return
  if (selectedProduct.value) await loadBomContext(selectedProduct.value.id, craftId.value)
  else await loadDeepLinkedSource()
}

function chooseSource(): void {
  if (metalSourceId.value) return
  if (!craftId.value) {
    ElMessage.warning('请先选择工艺类型。')
    return
  }
  sourceDialogVisible.value = true
}

function confirmSource(plan: OutsourcingSourcePlan, productIds: string[]): void {
  const allowedIds = new Set(productIds)
  selectedPlan.value = plan
  selectedProducts.value = plan.products.filter(product => allowedIds.has(product.id))
  activeProductId.value = selectedProducts.value[0]?.id || ''
  bomContexts.value = {}
  processingRowsByProduct.value = {}
  materialRowsByProduct.value = {}
}

function openProcessingDialog(): void {
  if (!selectedProduct.value || bomLoading.value) return
  if (!selectedBomContext.value?.bom) {
    ElMessage.warning('当前产品暂无可用 BOM。')
    return
  }
  processingDialogVisible.value = true
}

function materialsForProduct(productId: string): SelectedOutsourcingMaterialRow[] {
  const context = bomContexts.value[productId]
  const processing = processingRowsByProduct.value[productId] || []
  const primaryIds = new Set(processing.map(row => row.conversion_snapshot?.material_line_id))
  const primary = processing.flatMap(row => {
    const source = context?.material_items.find(item => item.id === row.conversion_snapshot?.material_line_id)
    return source ? [{ ...source, planned_issue_quantity: row.input_quantity, factory_id: row.factory_id, processing_bom_line_id: row.id }] : []
  })
  return [...primary, ...(materialRowsByProduct.value[productId] || []).filter(row => !primaryIds.has(row.id))]
}

function confirmProcessing(rows: OutsourcingProcessingCandidate[]): void {
  if (!selectedProduct.value) return
  const previous = processingRows.value
  processingRowsByProduct.value = { ...processingRowsByProduct.value, [selectedProduct.value.id]: rows.flatMap(row => {
    const existing = previous.filter(item => item.id === row.id)
    return existing.length ? existing : [{ ...row, input_quantity: '', row_key: crypto.randomUUID(), allocated_quantity: 0, factory_id: '', unit_price: 0 }]
  }) }
  const ids = new Set(rows.map(row => row.id))
  materialRowsByProduct.value = { ...materialRowsByProduct.value, [selectedProduct.value.id]: (materialRowsByProduct.value[selectedProduct.value.id] || []).filter(row => ids.has(row.processing_bom_line_id)) }
}

function addFactoryRow(row: SelectedOutsourcingProcessingRow): void {
  if (!selectedProduct.value) return
  processingRowsByProduct.value[selectedProduct.value.id] = [...processingRows.value, { ...row, row_key: crypto.randomUUID(), factory_id: '', input_quantity: '' }]
}

function materialPlan(row: SelectedOutsourcingMaterialRow) {
  const processing = processingRows.value.find(item => item.id === row.processing_bom_line_id && item.factory_id === row.factory_id)
  if (processing?.conversion_snapshot?.material_line_id === row.id) return outsourcingPlan(processing.input_quantity, processing.conversion_snapshot)
  return null
}


function openMaterialDialog(): void {
  if (!selectedProduct.value || bomLoading.value) return
  if (!selectedBomContext.value?.bom) {
    ElMessage.warning('当前产品暂无可用 BOM。')
    return
  }
  if (!processingRows.value.length) {
    ElMessage.warning('请先选择加工明细。')
    return
  }
  materialDialogVisible.value = true
}

function confirmMaterials(rows: SelectedOutsourcingMaterialRow[]): void {
  if (!selectedProduct.value) return
  materialRowsByProduct.value = { ...materialRowsByProduct.value, [selectedProduct.value.id]: rows }
}

function openFactoryDialog(): void {
  factoryDialogVisible.value = true
}

async function saveFactory(payload: OutsourcingFactoryInput): Promise<void> {
  factorySaving.value = true
  try {
    const result = await createOutsourcingFactory(payload)
    if (options.value) {
      const created = result.data
      options.value = {
        ...options.value,
        factories: [
          ...options.value.factories.filter(factory => factory.id !== created.id),
          { id: created.id, name: created.name, crafts: created.crafts },
        ],
      }
    }
    factoryDialogVisible.value = false
    ElMessage.success('加工厂已新增，可直接用于当前加工明细。')
  } catch (error) {
    ElMessage.error(errorText(error, '加工厂保存失败，请检查后重试。'))
  } finally {
    factorySaving.value = false
  }
}

function removeProcessing(rowKey: string): void {
  if (!selectedProduct.value) return
  if (hoveredProcessingRow.value?.row_key === rowKey) hoveredProcessingRow.value = null
  processingRowsByProduct.value[selectedProduct.value.id] = processingRows.value.filter(row => row.row_key !== rowKey)
}

function removeMaterial(id: string): void {
  if (!selectedProduct.value) return
  materialRowsByProduct.value = {
    ...materialRowsByProduct.value,
    [selectedProduct.value.id]: materialRows.value.filter(row => row.id !== id),
  }
}

function materialAllocationKey(row: SelectedOutsourcingMaterialRow): string {
  return row.processing_bom_line_id && row.factory_id ? `${row.processing_bom_line_id}|${row.factory_id}` : ''
}

function selectMaterialAllocation(row: SelectedOutsourcingMaterialRow, value: string): void {
  const [processingBomLineId = '', factoryId = ''] = value.split('|')
  row.processing_bom_line_id = processingBomLineId
  row.factory_id = factoryId
}

function processingHint(row: SelectedOutsourcingProcessingRow): string {
  const plan = outsourcingPlan(row.input_quantity, row.conversion_snapshot)
  if (row.conversion_snapshot?.kind === 'PIPE') {
    const conversion = row.conversion_snapshot
    const detail = `切割长度 ${conversion.cutting_length_mm} mm · 每根 ${conversion.pieces_per_bar} 支 · 原材料 ${conversion.raw_bar_length_m} 米/根`
    return `${detail} · ${plan.error || `预计扣 ${plan.raw} 根 / ${plan.meters} 米`}`
  }
  const detail = `每套耗米 ${row.conversion_snapshot?.fabric_meters_per_set ?? '—'} 米 · 预计余料 ${plan.remainder || '—'} 米`
  return plan.error ? `${detail} · ${plan.error}` : detail
}

function showProcessingHint(row: SelectedOutsourcingProcessingRow, _column: unknown, cell: HTMLElement): void {
  const rectangle = cell.closest('tr')?.getBoundingClientRect() || cell.getBoundingClientRect()
  const width = Math.min(600, window.innerWidth - 32)
  const top = rectangle.bottom + 8 + 72 <= window.innerHeight
    ? rectangle.bottom + 8
    : Math.max(8, rectangle.top - 80)
  processingHintStyle.value = {
    left: `${Math.max(16, Math.min(rectangle.left, window.innerWidth - width - 16))}px`,
    top: `${top}px`,
    width: `${width}px`,
  }
  hoveredProcessingRow.value = row
}

function hideProcessingHint(_row: SelectedOutsourcingProcessingRow, _column: unknown, cell: HTMLElement, event: MouseEvent): void {
  const next = event.relatedTarget
  if (next instanceof Element && cell.closest('tr')?.contains(next)) return
  hoveredProcessingRow.value = null
}

function createPayload(): OutsourcingOrderCreateInput {
  if (!selectedPlan.value) throw new Error('缺少排产来源。')
  if (metalSourceId.value && (!selectedMetalSource.value || selectedProducts.value.length !== 1 || selectedProducts.value[0]?.id !== metalScheduleProductId.value)) {
    throw new Error('当前排产产品与所选金工来源不一致，请重新选择来源。')
  }
  return {
    client_request_id: clientRequestId,
    schedule_id: selectedPlan.value.id,
    craft_id: craftId.value,
    delivery_date: deliveryDate.value,
    remark: '',
    products: selectedProducts.value.map(product => {
      const context = bomContexts.value[product.id]
      if (!context?.bom) throw new Error(`产品 ${product.product_name} 缺少可用 BOM。`)
      return {
        schedule_product_id: product.id,
        bom_id: context.bom.id,
        processing_items: [...new Set((processingRowsByProduct.value[product.id] || []).map(row => row.id))].map(id => {
          const rows = (processingRowsByProduct.value[product.id] || []).filter(row => row.id === id)
          if (new Set(rows.map(row => row.factory_id)).size !== rows.length) throw new Error('同一部位不能重复分配给同一家加工厂。')
          let inputTotal = 0n
          const allocations = rows.map(row => {
            const plan = outsourcingPlan(row.input_quantity, row.conversion_snapshot)
            if (plan.error) throw new Error(plan.error)
            inputTotal += decimalUnits(row.input_quantity)!
            return { factory_id: row.factory_id, allocated_quantity: plan.output, input_quantity: row.input_quantity, unit_price: Number(row.unit_price || 0).toFixed(2), remark: '' }
          })
          if (inputTotal > (decimalUnits(rows[0]?.available_quantity) || 0n)) throw new Error('各厂合计输入超过当前可外发原料额度。')
          return { bom_line_id: id, quantity: String(allocations.reduce((sum, row) => sum + BigInt(row.allocated_quantity), 0n)), processing_requirement: rows[0]?.technical_reference || '', allocations }
        }),
        materials: materialsForProduct(product.id).map(row => ({
          bom_line_id: row.id,
          processing_bom_line_id: row.processing_bom_line_id,
          factory_id: row.factory_id,
          planned_issue_quantity: String(row.planned_issue_quantity),
          difference_reason: '',
          remark: row.notes || '',
        })),
      }
    }),
  }
}

async function save(): Promise<void> {
  if (!canCreateOrder.value) {
    ElMessage.error('当前账号没有新增外发单权限。')
    return
  }
  if (!readyToSave.value) {
    ElMessage.warning('请为全部产品完成加工明细、加工厂、数量、单价和材料接收分配。')
    return
  }
  saving.value = true
  try {
  const draft = createPayload()
  const fingerprint = JSON.stringify({ ...draft, client_request_id: '' })
  if (!clientRequestId || fingerprint !== lastSubmissionFingerprint) clientRequestId = crypto.randomUUID()
  lastSubmissionFingerprint = fingerprint
  const payload = { ...draft, client_request_id: clientRequestId }
    const result = await createOutsourcingOrder(payload)
    ElMessage.success('外发单已保存，材料尚未扣减库存。')
    await router.replace({ path: `/workshop/outsourcing/${result.data.id}`, query: selectedMetalSource.value ? {
      view: 'metal', source_issue_line_id: selectedMetalSource.value.issue_line_id,
    } : {} })
  } catch (error) {
    ElMessage.error(errorText(error, '外发单保存失败，请核对来源和明细后重试。'))
  } finally {
    saving.value = false
  }
}

onMounted(() => { void loadOptions() })
</script>

<template>
  <section v-loading="loading || sourceLoading || bomLoading" class="outsourcing-page outsourcing-order-form-page" data-testid="outsourcing-order-form-page">
    <header class="outsourcing-heading"><div class="heading-title"><h1>新增外发单</h1></div></header>
    <ElAlert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon><ElButton @click="retryLoad">重新加载</ElButton></ElAlert>
    <ElAlert v-if="selectedMetalSource" data-testid="metal-source-context" :title="`已选金工来源：${selectedMetalSource.issue_number} · ${selectedMetalSource.part_name}，可交接 ${selectedMetalSource.available_pieces} 支。保存后进入详情登记交接，按实际交接确定材料来源。`" type="info" :closable="false" show-icon />
    <div class="order-form-layout">
      <aside class="source-card form-card">
        <h2>来源信息</h2>
        <div class="source-fields">
          <label><span>工艺类型</span><ElSelect v-model="craftId" :disabled="Boolean(metalSourceId)" placeholder="请选择厂外工艺" popper-class="outsourcing-select-popper"><template #label="{ label }"><span class="craft-tag craft-select-tag" :class="`craft-${craftTone}`">{{ label }}</span></template><ElOption v-for="item in options?.crafts || []" :key="item.id" :label="item.name" :value="item.id"><span class="craft-tag" :class="`craft-${({ SEWING: 'sewing', CUTTING: 'cutting', POWDER_COATING: 'spray', SCREEN_PRINTING: 'printing' } as Record<string, string>)[item.outsourcing_code || ''] || 'neutral'}`">{{ item.name }}</span></ElOption></ElSelect></label>
          <label><span>排产计划</span><button type="button" class="source-select-control" aria-label="选择排产计划" :disabled="Boolean(metalSourceId)" @click="chooseSource"><strong :class="{ 'is-placeholder': !selectedPlan }">{{ selectedPlan?.schedule_number || '请选择排产计划' }}</strong><span>{{ metalSourceId ? '来源带入' : '选择' }}</span></button></label>
          <label><span>生产任务单</span><ElInput :model-value="selectedPlan?.production_task_number || ''" disabled placeholder="选择排产计划后带入" /></label>
          <label><span>任务状态</span><ElInput :model-value="selectedPlan?.production_task_status_display || ''" disabled placeholder="选择排产计划后带入" /></label>
          <label><span>计划周期</span><ElInput :model-value="plannedDateRange" disabled placeholder="选择排产计划后带入" /></label>
          <label><span>委外交货日期</span><ElDatePicker v-model="deliveryDate" value-format="YYYY-MM-DD" placeholder="请选择日期" /></label>
        </div>
        <div v-if="selectedCraft" class="source-rule-note"><span class="craft-tag" :class="`craft-${craftTone}`">{{ selectedCraft.name }}</span><p><template v-if="selectedPlan">已选择 {{ selectedProducts.length }} 个产品，来源生产任务单 {{ selectedPlan.production_task_number }}。</template><template v-else>仅显示排产产品中明确勾选该厂外工艺的来源。</template></p></div>
      </aside>

      <main class="order-form-content">
        <section class="form-card product-info-card">
          <div class="product-info-heading"><h2>产品信息</h2><div v-if="selectedProducts.length > 1" class="selected-product-tabs"><button v-for="product in selectedProducts" :key="product.id" type="button" :class="{ 'is-active': selectedProduct?.id === product.id }" @click="activeProductId = product.id">{{ product.product_number || product.item_number || product.product_name }}</button></div><span v-if="selectedProducts.length">已选 {{ selectedProducts.length }} 个产品</span></div>
          <div v-if="selectedProduct" class="selected-product-panel">
            <div class="line-art-product" aria-label="产品简笔画"><i /><b /></div>
            <dl><div><dt>产品编号</dt><dd>{{ selectedProduct.product_number || '—' }}</dd></div><div><dt>订单数量</dt><dd>{{ selectedProduct.source_quantity }} {{ selectedProduct.unit_name }}</dd></div><div><dt>产品名称</dt><dd>{{ selectedProduct.product_name }}</dd></div><div><dt>排产数量</dt><dd>{{ selectedProduct.planned_quantity }} {{ selectedProduct.unit_name }}</dd></div><div><dt>规格/颜色</dt><dd>{{ selectedProduct.specification || '—' }} / {{ selectedProduct.color_name || '—' }}</dd></div><div><dt>BOM编号</dt><dd>{{ selectedBomContext?.bom?.bom_number || (bomLoading ? '加载中…' : '暂无可用BOM') }}</dd></div></dl>
          </div>
          <div v-else class="product-empty"><div class="line-art-product" aria-hidden="true"><i /><b /></div><p>选择排产计划后显示产品基础信息</p></div>
        </section>

        <section class="form-card processing-card">
          <div class="card-title-row"><h2>加工明细</h2><div class="card-title-actions"><ElButton v-if="canCreateFactory" :disabled="!craftId || bomLoading" @click="openFactoryDialog">＋ 添加加工厂</ElButton><ElButton :disabled="!selectedProduct || bomLoading" @click="openProcessingDialog">＋ 选择加工明细</ElButton></div></div>
          <ElTable :data="processingRows" :max-height="272" border empty-text="选择产品后，从对应 BOM 加工明细中选择" @cell-mouse-enter="showProcessingHint" @cell-mouse-leave="hideProcessingHint">
            <ElTableColumn type="index" label="#" width="45" />
            <ElTableColumn prop="part_name" label="部位" min-width="120" /><ElTableColumn prop="specification" label="规格" min-width="100" />
            <ElTableColumn label="订单需求" width="108"><template #default="{ row }">{{ quantityText(row.required_quantity) }} {{ row.unit }}</template></ElTableColumn>
            <ElTableColumn label="原料可外发" width="120"><template #default="{ row }">{{ quantityText(row.available_quantity) }} {{ row.input_unit }}</template></ElTableColumn>
            <ElTableColumn label="本次外发" width="160"><template #default="{ row }"><div class="quantity-input-with-unit"><ElInput v-model="row.input_quantity" aria-label="本次外发数量" inputmode="decimal" /><span>{{ row.input_unit }}</span></div></template></ElTableColumn>
            <ElTableColumn label="加工厂" min-width="145"><template #default="{ row }"><ElSelect v-model="row.factory_id" placeholder="请选择加工厂"><ElOption v-for="factory in availableFactories" :key="factory.id" :label="factory.name" :value="factory.id" /></ElSelect></template></ElTableColumn>
            <ElTableColumn label="加工单价" width="145"><template #default="{ row }"><div class="quantity-input-with-unit"><ElInputNumber v-model="row.unit_price" :min="0" :precision="2" :controls="false" /><span>元/{{ row.unit }}</span></div></template></ElTableColumn>
            <ElTableColumn label="预计加工" width="105"><template #default="{ row }">{{ outsourcingPlan(row.input_quantity, row.conversion_snapshot).output || '—' }} {{ row.unit }}</template></ElTableColumn>
            <ElTableColumn label="操作" width="120"><template #default="{ row }"><ElButton link @click="addFactoryRow(row)">分厂</ElButton><ElButton link type="danger" @click="removeProcessing(row.row_key)">移除</ElButton></template></ElTableColumn>
          </ElTable>
          <Teleport to="body"><div v-if="hoveredProcessingRow" class="processing-row-tip" :style="processingHintStyle" role="tooltip"><strong>{{ hoveredProcessingRow.part_name }}</strong><span>{{ processingHint(hoveredProcessingRow) }}</span></div></Teleport>
        </section>

        <section class="form-card material-card">
          <div class="card-title-row"><h2>{{ materialCardTitle }}</h2><ElButton :disabled="!selectedProduct || bomLoading" @click="openMaterialDialog">＋ 添加五金 / 辅料</ElButton></div>
          <ElTable :data="materialRows" :max-height="272" border empty-text="选择加工明细后，再选择本次需要外发的 BOM 材料">
            <ElTableColumn type="index" label="#" width="45" /><ElTableColumn prop="name" label="原材料" min-width="150" /><ElTableColumn prop="specification" label="规格" min-width="120" />
            <ElTableColumn label="加工厂 / 部位" min-width="230"><template #default="{ row }"><span v-if="materialPlan(row)">{{ availableFactories.find(item => item.id === row.factory_id)?.name || '待选择加工厂' }} / {{ processingRows.find(item => item.id === row.processing_bom_line_id)?.part_name }}</span><ElSelect v-else :model-value="materialAllocationKey(row)" @change="selectMaterialAllocation(row, $event)"><ElOption v-for="item in processingRows.filter(item => item.factory_id)" :key="item.row_key" :value="`${item.id}|${item.factory_id}`" :label="`${availableFactories.find(factory => factory.id === item.factory_id)?.name} / ${item.part_name}`" /></ElSelect></template></ElTableColumn>
            <ElTableColumn label="本次输入" width="180"><template #default="{ row }"><span v-if="materialPlan(row)">{{ row.planned_issue_quantity || '—' }} {{ row.unit }}</span><ElInput v-else v-model="row.planned_issue_quantity" /></template></ElTableColumn>
            <ElTableColumn label="预计扣库" min-width="205"><template #default="{ row }"><span v-if="materialPlan(row) && !materialPlan(row)?.error">{{ materialPlan(row)?.raw }} {{ row.procurement_unit }}<template v-if="row.category === 'PROFILE'"> / {{ materialPlan(row)?.meters }} 米</template></span><span v-else>{{ materialPlan(row)?.error || `${row.planned_issue_quantity || '—'} ${row.unit}` }}</span></template></ElTableColumn>
            <ElTableColumn label="操作" width="90"><template #default="{ row }"><ElButton v-if="!materialPlan(row)" link type="danger" @click="removeMaterial(row.id)">移除</ElButton><span v-else>随部位联动</span></template></ElTableColumn>
          </ElTable>
        </section>
        <section class="form-card return-measure-card"><h2>回货计量</h2><p>管材半成品按支回货，裁片半成品按套回货，均填写整数；合格与不良分别入库。</p><p>保存外发单不扣库存。仓库确认发料后扣原料，回货不重复扣原料；原料和产出去向均对平后手动结清。</p></section>
      </main>
    </div>
    <footer class="order-form-footer"><div><span>计划加工金额合计：</span><strong>{{ plannedAmount.toFixed(2) }} 元</strong></div><div><ElButton :disabled="saving" @click="router.push('/workshop/outsourcing')">取消</ElButton><ElButton type="primary" :disabled="!readyToSave" :loading="saving" @click="save">保存外发单</ElButton></div></footer>
    <FactoryFormDialog v-model="factoryDialogVisible" mode="create" :factory="null" :initial-craft-id="craftId" :crafts="options?.crafts || []" :saving="factorySaving" @submit="saveFactory" />
    <OutsourcingSourcePlanDialog
      v-if="selectedCraft"
      v-model="sourceDialogVisible"
      :craft="selectedCraft"
      :selected-plan="selectedPlan"
      :selected-product-ids="selectedProductIds"
      @confirm="confirmSource"
    />
    <OutsourcingProcessingDialog
      v-model="processingDialogVisible"
      :plan="selectedPlan"
      :product="selectedProduct"
      :context="selectedBomContext"
      :selected-rows="processingRows"
      @confirm="confirmProcessing"
    />
    <OutsourcingMaterialDialog
      v-model="materialDialogVisible"
      :product="selectedProduct"
      :context="selectedBomContext"
      :processing-rows="processingRows"
      :selected-rows="materialRows"
      :factories="availableFactories"
      @confirm="confirmMaterials"
    />
  </section>
</template>

<style lang="scss">@use '@/styles/outsourcing.scss';</style>

<style lang="scss" scoped>
.outsourcing-order-form-page .processing-card,
.outsourcing-order-form-page .material-card { max-height: none; overflow: visible; }
.processing-row-tip { position: fixed; z-index: 3000; display: flex; flex-wrap: wrap; gap: 4px 12px; box-sizing: border-box; padding: 10px 12px; border: 1px solid #d8c6aa; border-radius: 4px; background: #fffdf8; box-shadow: 0 8px 24px #2d241c22; color: #76543a; font-size: 12px; line-height: 20px; pointer-events: none; }
.processing-row-tip strong { color: #3b2b20; white-space: nowrap; }
.quantity-input-with-unit { display: flex; align-items: center; gap: 6px; min-width: 0; }
.quantity-input-with-unit > span { flex: none; white-space: nowrap; }
.quantity-input-with-unit :deep(.el-input),
.quantity-input-with-unit :deep(.el-input-number) { flex: 1; width: 0; min-width: 0; }
.return-measure-card p { font-size: 13px; color: #76685b; line-height: 1.6; }
</style>
