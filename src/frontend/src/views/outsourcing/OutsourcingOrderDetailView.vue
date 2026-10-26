<script setup lang="ts">
import { compactDecimal } from '@/utils/compactDecimal'
import { computed, onMounted, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import {
  deleteOutsourcingOrder,
  fetchOutsourcingOrder,
  outsourcingProductImageUrl,
  revokeDispatchedOutsourcingOrder,
} from '@/api/outsourcing'
import OutsourcingFlowActions from '@/components/outsourcing/OutsourcingFlowActions.vue'
import BomAttributesTooltip from '@/components/common/BomAttributesTooltip.vue'
import MetalProcessingP4View from './MetalProcessingP4View.vue'
import { useAuthStore } from '@/stores/auth'
import productImagePlaceholder from '@/assets/productionScheduling/product-image-placeholder.png'
import type { OutsourcingOrderDetail, VersionedOutsourcingOrder } from '@/types/outsourcing'
import { createClientUuid } from '@/utils/clientUuid'
import { formatOutsourcingMoney } from '@/utils/outsourcingPrices'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const canViewRegular = computed(() => Boolean(auth.user?.is_superuser || auth.hasPermission('outsourcing.view_outsourcingorder')))
const canViewMetal = computed(() => Boolean(auth.user?.is_superuser || auth.hasPermission('material_issues.view_metalprocessingsource')))
const metalProjectionOnly = computed(() => canViewMetal.value && (!canViewRegular.value || route.query?.view === 'metal'))
const detail = ref<OutsourcingOrderDetail | null>(null)
const showMetalOperations = computed(() => canViewMetal.value && (detail.value?.direct_handoff
  || (route.query?.view === 'metal' && !detail.value?.dispatch)))
const etag = ref('')
const loading = ref(false)
const deleting = ref(false)
const loadError = ref('')
let loadRequest = 0
const workflowSteps = computed(() => ['创建外发单', detail.value?.direct_handoff ? '金工直接交接' : '仓库外发', '加工厂加工', '回货入库', detail.value?.status === 'CLOSED' ? '备注结清' : '完成'])
const workflowCurrentIndex = computed(() => ({
  PENDING_DISPATCH: 1,
  PROCESSING: 2,
  PARTIAL_RETURN: 3,
  COMPLETED: 4,
  CLOSED: 4,
  CANCELLED: 0,
})[detail.value?.status || 'PENDING_DISPATCH'])

const returnQuantitiesByAllocation = computed(() => {
  const quantities = new Map<string, { good: number; defective: number }>()
  for (const record of detail.value?.returns || []) {
    for (const line of record.lines) {
      const current = quantities.get(line.allocation_id) || { good: 0, defective: 0 }
      if (line.quality === 'DEFECTIVE') current.defective += Number(line.returned_quantity)
      else current.good += Number(line.returned_quantity)
      quantities.set(line.allocation_id, current)
    }
  }
  return quantities
})

const allocationRows = computed(() => (detail.value?.products || []).flatMap(product =>
  product.processing_items.flatMap(item => item.allocations.map(allocation => {
    const quantities = returnQuantitiesByAllocation.value.get(allocation.id) || { good: 0, defective: 0 }
    const isDirect = Boolean(detail.value?.direct_handoff)
    const direct = isDirect ? detail.value?.direct_handoff_summary?.find(row => row.allocation_id === allocation.id) : undefined
    const returned = isDirect ? direct?.returned_good_pieces || 0 : quantities.good + quantities.defective
    return {
      ...allocation,
      allocated_quantity: Number(allocation.allocated_quantity),
      product_number: product.product.product_number || product.product.item_number || '—',
      product_name: product.product.product_name || '—',
      part_name: item.part_name,
      specification: item.specification,
      color: item.color,
      returned_quantity: returned,
      handoff_quantity: direct?.handoff_pieces || 0,
      unsprayed_quantity: direct?.returned_unsprayed_pieces || 0,
      good_quantity: isDirect ? direct?.returned_good_pieces || 0 : quantities.good,
      defective_quantity: quantities.defective,
      remaining_quantity: isDirect ? direct?.remaining_return_pieces || 0 : Math.max(Number(allocation.allocated_quantity) - returned, 0),
    }
  })),
))

const factoryProgressRows = computed(() => {
  const rows = new Map<string, typeof allocationRows.value[number]>()
  for (const allocation of allocationRows.value) {
    const progressKey = `${allocation.factory_id}|${allocation.unit}`
    const current = rows.get(progressKey)
    if (!current) {
      rows.set(progressKey, { ...allocation })
      continue
    }
    current.allocated_quantity += allocation.allocated_quantity
    current.handoff_quantity += allocation.handoff_quantity
    current.unsprayed_quantity += allocation.unsprayed_quantity
    current.returned_quantity += allocation.returned_quantity
    current.good_quantity += allocation.good_quantity
    current.defective_quantity += allocation.defective_quantity
    current.remaining_quantity += allocation.remaining_quantity
  }
  return Array.from(rows.values())
})

const materialRows = computed(() => (detail.value?.products || []).flatMap(product =>
  product.processing_items.flatMap(item => item.allocations.flatMap(allocation =>
    allocation.materials.map(material => ({
      ...material,
      product_name: product.product.product_name || '—',
      factory_name: allocation.factory_name,
      part_name: item.part_name,
    })),
  )),
))
const tooltipKeys = ['part_name', 'material', 'specification', 'hardware_color', 'plastic_color', 'fabric_color_name', 'accessory_color', 'packaging_color']
const returnMaterialValue = (row: { bom_attributes?: Array<{ key: string; value: string }> }) => {
  const field = (row.bom_attributes || []).find(item => item.key === 'material' && String(item.value || '').trim())
  return field?.value || '—'
}
const fixedColorValue = (row: { bom_attributes?: Array<{ key: string; value: string }> }) => {
  const field = (row.bom_attributes || []).find(item => ['hardware_color', 'plastic_color', 'fabric_color_name', 'accessory_color', 'packaging_color'].includes(item.key) && String(item.value || '').trim())
  return field?.value || '—'
}

const dispatchRecordRows = computed(() => {
  const dispatch = detail.value?.dispatch
  if (!dispatch) return []
  const materialById = new Map(materialRows.value.map(row => [row.id, row]))
  return dispatch.lines.map(line => {
    const material = materialById.get(line.material_item_id)
    return {
      id: line.id,
      dispatch_date: dispatch.dispatch_date,
      material_name: material?.name || line.inbound_number || '—',
      specification: material?.specification || '—',
      color: fixedColorValue(material || {}),
      bom_attributes: material?.bom_attributes || [],
      unit: line.material_unit || line.source_unit,
      quantity: line.material_quantity || line.source_quantity,
      pieces: line.issued_piece_count,
      meters: line.issued_meters,
      remark: dispatch.remark || '—',
    }
  })
})

const returnRecordRows = computed(() => (detail.value?.returns || []).flatMap(record => record.lines.map(line => ({
  ...record,
  ...line,
  good_quantity: line.quality === 'AVAILABLE' ? line.returned_quantity : '0',
  defective_quantity: line.quality === 'DEFECTIVE' ? line.returned_quantity : '0',
}))))

const hasDefectiveReturns = computed(() => returnRecordRows.value.some(row => Number(row.defective_quantity) > 0))

function productImage(imageFileId: string | null): string {
  if (!imageFileId || !detail.value?.id) return productImagePlaceholder
  return outsourcingProductImageUrl(detail.value.id, imageFileId)
}

function useProductImageFallback(event: Event): void {
  const image = event.currentTarget as HTMLImageElement
  if (image.src.endsWith(productImagePlaceholder)) return
  image.src = productImagePlaceholder
}

function errorText(error: unknown, fallback: string): string {
  if (!(error instanceof AxiosError)) return fallback
  const data = error.response?.data as { error?: { message?: string }; detail?: string } | undefined
  return data?.error?.message || data?.detail || fallback
}

function statusTone(value: OutsourcingOrderDetail['status']): string {
  return ({ PENDING_DISPATCH: 'pending', PROCESSING: 'processing', PARTIAL_RETURN: 'partial', COMPLETED: 'completed', CLOSED: 'cancelled', CANCELLED: 'cancelled' })[value]
}

function craftTone(code?: string): string {
  return ({ SEWING: 'sewing', CUTTING: 'cutting', POWDER_COATING: 'spray', SCREEN_PRINTING: 'printing' } as Record<string, string>)[code || ''] || 'neutral'
}

function allocationStage(row: typeof allocationRows.value[number]): string {
  if (detail.value?.status === 'CANCELLED') return '已作废'
  if (detail.value?.status === 'CLOSED') return '已结清 · 可补登记'
  if (detail.value?.status === 'COMPLETED') return detail.value.direct_handoff ? '已回齐' : '已结清'
  if (detail.value?.direct_handoff) {
    if (row.handoff_quantity <= 0) return '待交接'
    if (row.remaining_quantity <= 0) return '当前交接已处理'
    return row.returned_quantity > 0 ? '部分回货' : '加工中'
  }
  if (Number(row.remaining_quantity) <= 0) return '回货已齐·待结清'
  if (Number(row.returned_quantity) > 0) return '部分回货'
  return detail.value?.dispatch ? '加工中' : '待外发'
}

function allocationStageTone(row: typeof allocationRows.value[number]): string {
  if (detail.value?.status === 'CANCELLED') return 'cancelled'
  if (detail.value?.status === 'CLOSED') return 'cancelled'
  if (detail.value?.status === 'COMPLETED') return 'completed'
  if (detail.value?.direct_handoff) return row.handoff_quantity <= 0 ? 'pending' : row.returned_quantity > 0 ? 'partial' : 'processing'
  if (Number(row.remaining_quantity) <= 0) return 'completed'
  if (Number(row.returned_quantity) > 0) return 'partial'
  return detail.value?.dispatch ? 'processing' : 'pending'
}

async function load(): Promise<void> {
  const request = ++loadRequest
  if (metalProjectionOnly.value) { detail.value = null; loading.value = false; loadError.value = ''; return }
  const id = String(route.params.orderId || '')
  if (!id) return
  loading.value = true
  loadError.value = ''
  try {
    const result = await fetchOutsourcingOrder(id)
    if (request !== loadRequest) return
    detail.value = result.data
    etag.value = result.etag
  } catch (error) {
    if (request === loadRequest) loadError.value = errorText(error, '外发单详情加载失败。')
  } finally {
    if (request === loadRequest) loading.value = false
  }
}

async function deleteOrder(): Promise<void> {
  if (deleting.value || !detail.value || detail.value.direct_handoff || (!detail.value.can_delete && !detail.value.can_revoke_dispatched)) return
  deleting.value = true
  try {
    const latest = await fetchOutsourcingOrder(detail.value.id)
    applyFlowResult(latest)
    if (latest.data.direct_handoff || !latest.etag || (!latest.data.can_delete && !latest.data.can_revoke_dispatched)) {
      ElMessage.warning('当前外发单已不能删除，请核对最新状态。')
      return
    }
    if (latest.data.can_delete) {
      await ElMessageBox.confirm('删除后外发单及其产品、加工分配和材料计划将永久移除，无法恢复。', '删除外发单', {
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        type: 'warning',
        customClass: 'outsourcing-confirm-dialog',
      })
      await deleteOutsourcingOrder(latest.data.id, latest.etag)
      ElMessage.success('外发单已永久删除，加工额度已释放。')
      await router.replace('/workshop/outsourcing')
      return
    }
    const { value } = await ElMessageBox.prompt(
      detail.value.stock_mode === 'PUBLIC_V2'
        ? '仅未投入、未损耗、未回货的外发单可撤销。未用原料将退回原库区的公共库存，并恢复本订单可外发数量。请填写撤销原因。'
        : '仅未投入、未损耗、未回货的外发单可撤销。确认后将未用原料退回原发料批次与库区；单据保留为已取消。请填写撤销原因。',
      '撤销已发料外发单',
      {
        confirmButtonText: '确认撤销并退料',
        cancelButtonText: '取消',
        type: 'warning',
        inputType: 'textarea',
        inputPlaceholder: '请输入撤销原因',
        inputValidator: input => input.trim().length > 0 && input.trim().length <= 500 || '撤销原因须为 1 至 500 字。',
        customClass: 'outsourcing-confirm-dialog',
      },
    )
    const result = await revokeDispatchedOutsourcingOrder(latest.data.id, value.trim(), createClientUuid(), latest.etag)
    applyFlowResult(result)
    ElMessage.success(detail.value.stock_mode === 'PUBLIC_V2' ? '外发单已撤销，原料已退回原库区公共库存。' : '外发单已撤销，原料已退回原批次库存。')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorText(error, '操作结果未确认，请刷新详情核对状态，勿重复提交。'))
  } finally {
    deleting.value = false
  }
}

function dateOnly(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : '—'
}

function applyFlowResult(result: VersionedOutsourcingOrder): void {
  detail.value = result.data
  etag.value = result.etag
}

onMounted(() => { void load() })
watch(() => [route.params.orderId, route.query?.view], () => { void load() })
</script>

<template>
  <section class="outsourcing-page outsourcing-order-detail-page" data-testid="outsourcing-order-detail-page">
    <header class="outsourcing-heading detail-heading">
      <div class="detail-title"><h1>外发单详情</h1></div>
      <div class="heading-actions">
        <ElButton @click="router.push('/workshop/outsourcing')">返回</ElButton>
        <ElButton v-if="metalProjectionOnly && canViewRegular" @click="router.replace({ path: route.path, query: { ...route.query, view: undefined, source_issue_line_id: undefined } })">查看基础详情</ElButton>
        <ElButton v-if="(detail?.can_delete || detail?.can_revoke_dispatched) && !detail.direct_handoff" class="delete-order-button" type="danger" plain :loading="deleting" @click="deleteOrder">{{ detail.can_delete ? '永久删除外发单' : '撤销并退料' }}</ElButton>
        <ElButton v-if="detail?.status === 'PENDING_DISPATCH' && !detail.dispatch && !detail.direct_handoff && canViewMetal && !showMetalOperations" @click="router.replace({ path: route.path, query: { ...route.query, view: 'metal' } })">选择金工加工件</ElButton>
        <ElButton v-if="detail?.status === 'PENDING_DISPATCH' && !detail.dispatch && !detail.direct_handoff && showMetalOperations" @click="router.replace({ path: route.path, query: { ...route.query, view: undefined, source_issue_line_id: undefined } })">改选仓库原料</ElButton>
        <OutsourcingFlowActions v-if="detail && !showMetalOperations" :detail="detail" :etag="etag" @updated="applyFlowResult" />
      </div>
    </header>

    <MetalProcessingP4View v-if="metalProjectionOnly" mode="original" embedded :original-order-id="String(route.params.orderId || '')" />
    <ElAlert v-else-if="loadError" :title="loadError" type="error" show-icon :closable="false"><ElButton @click="load">重试</ElButton></ElAlert>
    <div v-else-if="loading || !detail" v-loading="loading" class="page-loading">正在加载外发单详情…</div>
    <template v-else>
      <ElAlert v-if="detail.direct_handoff" data-testid="original-direct-handoff-note" :title="canViewMetal ? '此单由金工直接交接；在下方登记交接、回货及原单收尾，原料不重复扣库。' : '此单由金工直接交接，当前账号可查看基础详情；交接与回货操作需要金工来源权限。'" type="info" :closable="false" show-icon />
      <ElAlert v-if="detail.status === 'CANCELLED' && detail.dispatch && !detail.direct_handoff" :title="detail.stock_mode === 'PUBLIC_V2' ? '本单已撤销；发料记录保留，未用原料已退回原库区公共库存。' : '本单已撤销；发料记录保留，未用原料已退回原批次库存。'" type="success" :closable="false" show-icon />
      <section v-if="!showMetalOperations" class="detail-card order-workflow-card" :class="{ 'is-cancelled': detail.status === 'CANCELLED' }">
        <div class="detail-card-heading"><h2>流程步骤</h2><span>{{ detail.status_display }}</span></div>
        <div class="order-workflow-steps" aria-label="外发单流程步骤">
          <template v-for="(step, index) in workflowSteps" :key="step">
            <div class="order-workflow-step" :class="{ 'is-done': index < workflowCurrentIndex, 'is-current': detail.status !== 'CANCELLED' && index === workflowCurrentIndex }" :aria-current="detail.status !== 'CANCELLED' && index === workflowCurrentIndex ? 'step' : undefined">
              <i>{{ index < workflowCurrentIndex ? '✓' : index + 1 }}</i><span>{{ step }}</span>
            </div>
            <b v-if="index < workflowSteps.length - 1" :class="{ 'is-done': index < workflowCurrentIndex }" />
          </template>
        </div>
      </section>
      <div class="order-detail-overview">
        <section class="detail-card order-basic-card">
          <div class="detail-card-heading"><h2>基本信息</h2></div>
          <dl class="order-basic-grid">
            <div><dt>外发单号</dt><dd>{{ detail.order_number }}</dd></div>
            <div><dt>计划单号</dt><dd>{{ detail.schedule_number }}</dd></div>
            <div><dt>任务单号</dt><dd>{{ detail.production_task_number }}</dd></div>
            <div><dt>创建日期</dt><dd>{{ dateOnly(detail.created_at) }}</dd></div>
            <div><dt>创建人</dt><dd>{{ detail.created_by?.name || '—' }}</dd></div>
            <div><dt>加工工艺</dt><dd><span class="craft-tag" :class="`craft-${craftTone(detail.craft.outsourcing_code)}`">{{ detail.craft.name }}</span></dd></div>
            <div><dt>状态</dt><dd><span class="status-tag" :class="`status-${statusTone(detail.status)}`">{{ detail.status_display }}</span></dd></div>
            <div><dt>下单日期</dt><dd>{{ detail.order_date || '—' }}</dd></div>
            <div><dt>要求交货日期</dt><dd>{{ detail.delivery_date }}</dd></div>
            <div><dt>备注</dt><dd>{{ detail.remark || '—' }}</dd></div>
          </dl>
        </section>

        <section class="detail-card order-product-card">
          <div class="detail-card-heading"><h2>产品信息</h2></div>
          <div class="detail-product-list">
            <article v-for="product in detail.products" :key="product.id">
              <div class="detail-product-image"><img :src="productImage(product.image_file_id)" :class="{ 'is-placeholder': !product.image_file_id }" :alt="String(product.product.product_name || '产品图片')" @error="useProductImageFallback"></div>
              <dl>
                <div><dt>产品</dt><dd>{{ product.product.product_number || product.product.item_number || '—' }} {{ product.product.product_name || '—' }}</dd></div>
                <div><dt>颜色</dt><dd>{{ product.product.color_name || '—' }}</dd></div>
                <div><dt>BOM部位</dt><dd>{{ Array.from(new Set(product.processing_items.map(item => item.part_name).filter(Boolean))).join('、') || '—' }}</dd></div>
                <div><dt>计划数量</dt><dd>{{ compactDecimal(product.planned_quantity) }} {{ product.unit_name || '套' }}</dd></div>
                <div><dt>计量单位</dt><dd>{{ product.unit_name || '套' }}</dd></div>
              </dl>
            </article>
          </div>
        </section>
      </div>

      <MetalProcessingP4View v-if="showMetalOperations" mode="original" embedded :original-order-id="detail.id" @updated="load" />

      <section class="detail-card order-price-card">
        <div class="detail-card-heading"><h2>加工价格</h2><span>计划加工金额合计：{{ formatOutsourcingMoney(detail.planned_amount) }} 元</span></div>
        <ElTable :data="allocationRows" border row-key="id" empty-text="暂无加工价格明细">
          <ElTableColumn prop="product_name" label="产品" min-width="150" />
          <ElTableColumn prop="part_name" label="部位" min-width="130" />
          <ElTableColumn prop="factory_name" label="加工厂" min-width="150" />
          <ElTableColumn label="计划加工量" width="130" align="right"><template #default="{ row }">{{ compactDecimal(row.allocated_quantity) }} {{ row.unit }}</template></ElTableColumn>
          <ElTableColumn label="加工单价" width="145" align="right"><template #default="{ row }">{{ formatOutsourcingMoney(row.unit_price) }}<template v-if="row.unit_price != null"> 元/{{ row.unit }}</template></template></ElTableColumn>
          <ElTableColumn label="计划金额（元）" width="145" align="right"><template #default="{ row }">{{ formatOutsourcingMoney(row.planned_amount) }}</template></ElTableColumn>
        </ElTable>
      </section>

      <section v-if="!showMetalOperations" class="detail-card order-progress-card">
        <div class="detail-card-heading"><h2>分厂加工进度</h2></div>
        <ElTable :data="factoryProgressRows" border :show-summary="detail.status !== 'CANCELLED'" sum-text="合计" empty-text="暂无加工分配">
          <ElTableColumn prop="factory_name" label="加工厂" min-width="210" />
          <ElTableColumn prop="unit" label="单位" width="90" />
          <ElTableColumn prop="allocated_quantity" label="分配数量" min-width="140" ><template #default="{ row }">{{ compactDecimal(row.allocated_quantity) }}</template></ElTableColumn>
          <ElTableColumn v-if="detail.direct_handoff" prop="handoff_quantity" label="实际交接" min-width="120" ><template #default="{ row }">{{ compactDecimal(row.handoff_quantity) }}</template></ElTableColumn>
          <ElTableColumn prop="returned_quantity" label="累计收货数量" min-width="160" ><template #default="{ row }">{{ compactDecimal(row.returned_quantity) }}</template></ElTableColumn>
          <ElTableColumn prop="good_quantity" label="合格数量" min-width="140" ><template #default="{ row }">{{ compactDecimal(row.good_quantity) }}</template></ElTableColumn>
          <ElTableColumn v-if="detail.direct_handoff" prop="unsprayed_quantity" label="未喷塑退回" min-width="120" ><template #default="{ row }">{{ compactDecimal(row.unsprayed_quantity) }}</template></ElTableColumn>
          <ElTableColumn v-else prop="defective_quantity" label="不良数量" min-width="140" ><template #default="{ row }">{{ compactDecimal(row.defective_quantity) }}</template></ElTableColumn>
          <ElTableColumn prop="remaining_quantity" label="待回数量" min-width="140"><template #default="{ row }">{{ detail.status === 'CANCELLED' ? '—' : compactDecimal(row.remaining_quantity) }}</template></ElTableColumn>
          <ElTableColumn label="加工状态" min-width="130"><template #default="{ row }"><span class="status-tag progress-status" :class="`status-${allocationStageTone(row)}`">{{ allocationStage(row) }}</span></template></ElTableColumn>
        </ElTable>
        <div v-if="hasDefectiveReturns" class="order-progress-alert">异常情况：存在不良品待处理，数量按各加工明细的 BOM 单位记录。</div>
      </section>

      <div v-if="!showMetalOperations" class="order-record-grid">
        <section class="detail-card order-record-card">
          <div class="detail-card-heading"><h2>发料记录</h2></div>
          <ElTable :data="dispatchRecordRows" border :empty-text="detail.direct_handoff ? '已由金工直接交接，不重复执行仓库原料发料' : detail.status === 'CANCELLED' ? '外发单已作废，未执行仓库发料' : '尚未执行仓库发料'">
            <ElTableColumn prop="dispatch_date" label="发料日期" width="118" />
            <ElTableColumn label="物料名称" min-width="150"><template #default="{ row }"><div class="two-line-cell"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys"><span>{{ row.material_name }}</span></BomAttributesTooltip><small>{{ row.color }}</small></div></template></ElTableColumn>
            <ElTableColumn prop="specification" label="规格" min-width="90" />
            <ElTableColumn prop="unit" label="单位" width="64" />
            <ElTableColumn label="实际发料 / 扣库" min-width="190"><template #default="{ row }"><div class="two-line-cell"><span v-if="row.pieces !== null">{{ row.pieces }} 支</span><span>{{ compactDecimal(row.quantity) }} {{ row.unit }}<template v-if="row.meters"> / {{ compactDecimal(row.meters) }} 米</template></span></div></template></ElTableColumn>
            <ElTableColumn prop="remark" label="备注" width="80" />
          </ElTable>
        </section>
        <section class="detail-card order-record-card">
          <div class="detail-card-heading"><h2>回货记录</h2></div>
          <ElTable :data="returnRecordRows" border :empty-text="detail.status === 'CANCELLED' ? '外发单已作废，无加工厂回货记录' : '尚无加工厂回货记录'">
            <ElTableColumn prop="return_number" label="回货单号" min-width="167" />
            <ElTableColumn prop="factory_name" label="加工厂" min-width="132" />
            <ElTableColumn prop="return_date" label="回货日期" width="138" />
            <ElTableColumn label="部位" min-width="150"><template #default="{ row }"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys">{{ row.component || '—' }}</BomAttributesTooltip></template></ElTableColumn>
            <ElTableColumn label="材质" min-width="105"><template #default="{ row }">{{ returnMaterialValue(row) }}</template></ElTableColumn>
            <ElTableColumn prop="specification" label="规格" min-width="135" />
            <ElTableColumn prop="color" label="颜色" min-width="105" />
            <ElTableColumn prop="unit" label="单位" width="72" />
            <ElTableColumn prop="returned_quantity" label="回货数量" width="120" ><template #default="{ row }">{{ compactDecimal(row.returned_quantity) }}</template></ElTableColumn>
            <ElTableColumn prop="good_quantity" label="合格数量" width="120" ><template #default="{ row }">{{ compactDecimal(row.good_quantity) }}</template></ElTableColumn>
            <ElTableColumn prop="defective_quantity" label="不良数量" width="120" ><template #default="{ row }">{{ compactDecimal(row.defective_quantity) }}</template></ElTableColumn>
          </ElTable>
        </section>
      </div>
    </template>


  </section>
</template>

<style lang="scss">@use '@/styles/outsourcing.scss';</style>
