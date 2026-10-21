<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { pipeMeters, pipeRootError } from '@/utils/pipeQuantities'
import { computed, h, onBeforeUnmount, ref, watch } from 'vue'
import backIcon from '@/assets/procurement/create-back.svg'
import calendarIcon from '@/assets/procurement/create-calendar.svg'
import rightIcon from '@/assets/procurement/create-right.svg'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'

import {
  confirmVersionedPurchaseOrder,
  fetchPurchaseOrderSupplierOptions,
  fetchVersionedPurchaseOrder,
  updatePurchaseOrder,
} from '@/api/purchaseOrders'
import type { PurchaseOrderDetail, PurchaseOrderOptions } from '@/types/purchaseOrder'
import { materialAttributeFields, materialSpecificationValue } from '@/utils/materialAttributes'

const CalendarIcon = () => h('img', { src: calendarIcon, width: 16, height: 16, alt: '' })
const auth = useAuthStore()
const canEdit = computed(() => auth.moduleCan('procurement.change_purchaseorder', 'procurement.add_purchaseorder'))
const canSubmit = computed(() => auth.hasPermission('procurement.submit_purchaseorder'))
const route = useRoute()
const router = useRouter()
const loading = ref(false)
const saving = ref(false)
const confirming = ref(false)
const loadError = ref('')
const actionError = ref('')
const order = ref<PurchaseOrderDetail | null>(null)
const options = ref<Pick<PurchaseOrderOptions, 'suppliers'> | null>(null)
const optionsLoading = ref(false)
const optionsReady = ref(false)
const optionsError = ref('')
const hoveredLineId = ref('')
const etag = ref('')
let orderRequestId = 0
let optionsRequestId = 0

const today = new Date()
today.setHours(0, 0, 0, 0)

const supplierCount = computed(() => new Set(
  (order.value?.lines || []).map((line) => line.supplier_id).filter(Boolean),
).size)

const localTotal = computed(() => (order.value?.lines || []).reduce((sum, line) => {
  const quantity = Number(line.raw_bar_length_m ? pipeMeters(line.actual_bar_count, line.raw_bar_length_m) : line.actual_purchase_quantity)
  const price = Number(line.unit_price)
  return Number.isFinite(quantity) && Number.isFinite(price) ? sum + quantity * price : sum
}, 0))

const confirmationErrors = computed(() => {
  const errors: string[] = []
  if (!order.value?.lines.length) errors.push('采购明细为空，请返回补充明细。')
  for (const line of order.value?.lines || []) {
    const missing: string[] = []
    const rootError = line.raw_bar_length_m ? pipeRootError(line.actual_bar_count) : ''
    if (rootError) errors.push(`第 ${line.line_number} 行：${rootError}`)
    if (!line.supplier_id) missing.push('供应商')
    if (!line.delivery_date) missing.push('采购交期')
    const actualQuantity = line.raw_bar_length_m
      ? pipeMeters(line.actual_bar_count, line.raw_bar_length_m)
      : line.actual_purchase_quantity
    if (!rootError && (actualQuantity === null || actualQuantity === '' || !Number.isFinite(Number(actualQuantity)) || Number(actualQuantity) <= 0)) missing.push('实际采购数量')
    if (line.unit_price === null || line.unit_price === '' || !Number.isFinite(Number(line.unit_price)) || Number(line.unit_price) < 0) missing.push('采购单价')
    if (!line.source_unit_text) missing.push('单位')
    if (missing.length) errors.push(`第 ${line.line_number || '—'} 行缺少：${missing.join('、')}`)
  }
  if (order.value && order.value.currency_code !== 'CNY') {
    errors.push('采购金额单位固定为元，当前采购订单不是人民币。')
  }
  return errors
})

function formatQuantity(value: string | number | null): string {
  if (value === null || value === '') return '—'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return String(value)
  return parsed.toLocaleString('zh-CN', { maximumFractionDigits: 4, useGrouping: false })
}

function formatQuantityInput(value: string | number | null): string | null {
  if (value === null || value === '') return null
  const raw = String(value).trim()
  const matched = raw.match(/^(\d+)(?:\.(\d*))?$/)
  if (!matched) return raw

  const fraction = `${matched[2] || ''}000`
  let cents = BigInt(matched[1] || '0') * 100n + BigInt(fraction.slice(0, 2))
  if (Number(fraction[2]) >= 5) cents += 1n
  const fractionText = String(cents % 100n).padStart(2, '0').replace(/0+$/, '')
  return `${cents / 100n}${fractionText ? `.${fractionText}` : ''}`
}

function money(value: number | string | null): string {
  const parsed = Number(value || 0)
  return parsed.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })
}

function lineAmount(line: PurchaseOrderDetail['lines'][number]): string {
  const quantity = Number(line.raw_bar_length_m ? pipeMeters(line.actual_bar_count, line.raw_bar_length_m) : line.actual_purchase_quantity)
  const price = Number(line.unit_price)
  if (!Number.isFinite(quantity) || !Number.isFinite(price)) return '—'
  return money(quantity * price)
}

function pipeMetersLabel(line: PurchaseOrderDetail['lines'][number]): string {
  return `${pipeMeters(line.actual_bar_count, line.raw_bar_length_m) || '—'} 米 · ${line.raw_bar_length_m} 米/根`
}

function disabledPastDate(date: Date): boolean {
  return date.getTime() < today.getTime()
}

function apiErrorMessage(error: unknown, fallback: string): string {
  const response = (error as {
    response?: { status?: number; data?: { error?: { message?: string; field_errors?: Record<string, string[] | string> }; detail?: string } }
  })?.response
  const fieldErrors = response?.data?.error?.field_errors
  if (fieldErrors) {
    const first = Object.values(fieldErrors).flat().find(Boolean)
    if (first) return String(first)
  }
  if (response?.status === 412) return '订单已被其他人修改，请刷新后再操作。'
  if (response?.status === 428) return '页面版本信息已失效，请刷新后再操作。'
  return response?.data?.error?.message || response?.data?.detail || fallback
}

function updateOrder(result: { data: PurchaseOrderDetail; etag: string }): void {
  order.value = {
    ...result.data,
    lines: result.data.lines.map((line) => ({
      ...line,
      actual_purchase_quantity: formatQuantityInput(line.actual_purchase_quantity),
    })),
  }
  etag.value = result.etag
}

async function loadOrder(): Promise<void> {
  const currentRequestId = ++orderRequestId
  loading.value = true
  loadError.value = ''
  actionError.value = ''
  order.value = null
  etag.value = ''
  try {
    const orderResult = await fetchVersionedPurchaseOrder(String(route.params.id || ''))
    if (currentRequestId !== orderRequestId) return
    updateOrder(orderResult)
  } catch (error) {
    if (currentRequestId !== orderRequestId) return
    loadError.value = apiErrorMessage(error, '采购订单加载失败，请稍后重试。')
  } finally {
    if (currentRequestId === orderRequestId) loading.value = false
  }
}

function materialTitle(line: PurchaseOrderDetail['lines'][number]): string {
  return line.part_name || line.material || line.raw_material || '未命名物料'
}

function materialDetail(line: PurchaseOrderDetail['lines'][number]): string {
  const values = [line.material, line.raw_material, line.specification]
  if (order.value?.source_type === 'SAMPLE') values.push(line.product_color)
  return [...new Set(values.filter(Boolean))].join(' · ') || '规格未填写'
}

function handleLineMouseEnter(line: PurchaseOrderDetail['lines'][number]): void {
  hoveredLineId.value = line.id
}

function handleLineMouseLeave(): void {
  hoveredLineId.value = ''
}

function productColor(product: PurchaseOrderDetail['product_summary'][number]): string {
  return [product.color_card, product.color_name, product.color_code]
    .map((value) => (value || '').trim())
    .filter((value) => value && value !== '/' && value !== '-' && value !== '—')
    .join(' · ') || '—'
}

async function loadOptions(): Promise<void> {
  const currentRequestId = ++optionsRequestId
  optionsLoading.value = true
  optionsReady.value = false
  optionsError.value = ''
  try {
    const result = await fetchPurchaseOrderSupplierOptions()
    if (currentRequestId !== optionsRequestId) return
    options.value = result
    optionsReady.value = true
  } catch (error) {
    if (currentRequestId !== optionsRequestId) return
    optionsError.value = apiErrorMessage(error, '供应商选项加载失败，请重试。')
  } finally {
    if (currentRequestId === optionsRequestId) optionsLoading.value = false
  }
}

async function load(): Promise<void> {
  await Promise.all([loadOrder(), loadOptions()])
}

function updatePayload() {
  if (!order.value) return null
  return {
    is_mailed: order.value.is_mailed,
    lines: order.value.lines.map((line) => ({
      id: line.id,
      supplier_id: line.supplier_id || null,
      delivery_date: line.delivery_date || null,
      actual_purchase_quantity: line.raw_bar_length_m ? null : line.actual_purchase_quantity || null,
      ...(line.raw_bar_length_m ? { actual_bar_count: line.actual_bar_count } : {}),
      unit_price: line.unit_price === '' ? null : line.unit_price,
    })),
  }
}

async function saveChanges(showSuccess = true): Promise<boolean> {
  if (!canEdit.value || !order.value || saving.value || loading.value || !optionsReady.value) return false
  const payload = updatePayload()
  if (!payload) return false
  saving.value = true
  actionError.value = ''
  try {
    updateOrder(await updatePurchaseOrder(order.value.id, payload, etag.value))
    if (showSuccess) ElMessage.success('采购订单已保存。')
    return true
  } catch (error) {
    actionError.value = apiErrorMessage(error, '采购订单保存失败。')
    ElMessage.error(actionError.value)
    return false
  } finally {
    saving.value = false
  }
}

async function confirmAndContinue(): Promise<void> {
  if (!order.value || !canEdit.value || (order.value.status === 'DRAFT' && !canSubmit.value) || saving.value || confirming.value || loading.value || !optionsReady.value) return
  actionError.value = ''
  if (confirmationErrors.value.length) {
    await ElMessageBox.alert(
      h('div', { class: 'purchase-confirm-errors' }, [
        h('p', `还有 ${confirmationErrors.value.length} 项内容需要处理：`),
        h('ul', confirmationErrors.value.map((message) => h('li', message))),
      ]),
      '请完善采购信息',
      { type: 'warning', confirmButtonText: '知道了', customClass: 'purchase-confirm-message-box' },
    ).catch(() => undefined)
    return
  }
  confirming.value = true
  const saved = await saveChanges(false)
  if (!saved || !order.value) {
    confirming.value = false
    return
  }
  if (order.value.status === 'DRAFT') {
    try {
      await ElMessageBox.confirm(
        `确认采购订单 ${order.value.order_number} 后，将进入供应商采购表模板选择。确认后仍可在生成采购表前修改。`,
        '确认采购订单',
        { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消', customClass: 'purchase-confirm-message-box' },
      )
    } catch {
      confirming.value = false
      return
    }
    try {
      updateOrder(await confirmVersionedPurchaseOrder(order.value.id))
      ElMessage.success('采购订单已确认。')
    } catch (error) {
      actionError.value = apiErrorMessage(error, '采购订单确认失败。')
      ElMessage.error(actionError.value)
      confirming.value = false
      return
    }
  }
  confirming.value = false
  void router.push({ name: 'purchase-sheet-template-select', params: { id: order.value.id } })
}

watch(() => route.params.id, () => void load(), { immediate: true })
onBeforeUnmount(() => { orderRequestId++; optionsRequestId++ })
</script>

<template>
  <section v-loading="loading" class="confirm-page erp-glass-form">
    <header class="page-heading">
      <div><h1>确认采购订单</h1><p>核对供应商、交期、数量及单价</p></div>
      <ElButton class="back-button" @click="router.push({ name: 'purchase-orders' })"><img :src="backIcon" alt="" class="purchase-icon" />返回列表</ElButton>
    </header>
    <section v-if="loadError" class="load-error" role="alert"><ElAlert type="error" :title="loadError" :closable="false" show-icon /><ElButton @click="load">重新加载</ElButton></section>
    <template v-else-if="order">
      <ElAlert v-if="optionsError" type="error" :title="optionsError" :closable="false" show-icon>
        <ElButton link @click="loadOptions">重试供应商</ElButton>
      </ElAlert>
      <section class="detail-card">
        <header>
          <div class="detail-title-context">
            <h2>采购明细</h2><span>{{ order.lines.length }} 项</span>
            <div class="source-context"><span>{{ order.source_type === 'SAMPLE' ? '打样单号' : '生产单号' }}</span><strong>{{ (order.source_type === 'SAMPLE' ? order.source_number : order.production_task_number) || '—' }}</strong></div>
            <div v-if="order.product_summary[0]" class="product-context" :title="`${order.product_summary[0].product_name || '—'}\n规格：${order.product_summary[0].specification || '—'}\n颜色：${productColor(order.product_summary[0])}`">
              <span>产品</span><strong>{{ order.product_summary[0].product_name || '—' }}<template v-if="order.product_summary.length > 1"> 等{{ order.product_summary.length }}款</template></strong><small>规格：{{ order.product_summary[0].specification || '—' }}　颜色：{{ productColor(order.product_summary[0]) }}</small>
            </div>
          </div>
          <strong class="purchase-order-number">{{ order.order_number }}</strong>
        </header>
        <ElTable :data="order.lines" row-key="id" height="100%" class="erp-table-editor detail-table" @cell-mouse-enter="handleLineMouseEnter" @mouseleave="handleLineMouseLeave">
          <ElTableColumn type="index" label="序号" width="48" align="center" />
          <ElTableColumn label="分类" prop="section_title" width="106" />
          <ElTableColumn label="物料信息" width="208">
            <template #default="{ row }"><div class="material-cell"><strong>{{ materialTitle(row) }}</strong></div></template>
          </ElTableColumn>
          <ElTableColumn v-if="order.source_type === 'SAMPLE'" label="材质规格" width="220">
            <template #default="{ row }"><ElTooltip :content="materialDetail(row)" placement="top" :show-after="200"><span class="material-detail">{{ materialDetail(row) }}</span></ElTooltip></template>
          </ElTableColumn>
          <ElTableColumn v-else label="规格" width="220">
            <template #default="{ row }"><ElTooltip placement="top" :show-after="80" :visible="hoveredLineId === row.id" :teleported="true"><template #content><div class="material-attribute-tooltip"><div v-for="field in materialAttributeFields(row)" :key="field.key"><span>{{ field.label }}</span><strong>{{ field.value }}</strong></div></div></template><span class="material-detail">{{ materialSpecificationValue(row) }}</span></ElTooltip></template>
          </ElTableColumn>
          <ElTableColumn label="建议采购量" width="180" align="right" header-align="left">
            <template #default="{ row }"><div class="quantity-cell"><strong v-if="row.raw_bar_length_m">{{ row.suggested_bar_count }} 根</strong><strong v-else>{{ formatQuantity(row.required_quantity) }}</strong><small>{{ row.raw_bar_length_m ? row.suggested_purchase_meters + ' 米' : row.source_unit_text || '单位未识别' }}</small></div></template>
          </ElTableColumn>
          <ElTableColumn label="供应商" width="271">
            <template #default="{ row }">
              <ElSelect v-model="row.supplier_id" filterable clearable :loading="optionsLoading" :disabled="!optionsReady" :placeholder="optionsLoading ? '正在加载供应商' : '请选择供应商'" teleported>
                <ElOption
                  v-for="supplier in options?.suppliers || []"
                  :key="supplier.id"
                  :value="supplier.id"
                  :label="supplier.supplier_name"
                />
                <template #label="{ value }">{{ options?.suppliers.find(supplier => supplier.id === value)?.supplier_name || row.supplier_name || '—' }}</template>
              </ElSelect>
            </template>
          </ElTableColumn>
          <ElTableColumn label="采购交期" width="195">
            <template #default="{ row }">
              <ElDatePicker
                v-model="row.delivery_date"
                :prefix-icon="CalendarIcon"
                type="date"
                value-format="YYYY-MM-DD"
                format="YYYY-MM-DD"
                placeholder="选择采购交期"
                :disabled-date="disabledPastDate"
                teleported
              />
            </template>
          </ElTableColumn>
          <ElTableColumn label="实际采购数量" width="163">
            <template #default="{ row }">
              <ElInput v-if="row.raw_bar_length_m" v-model="row.actual_bar_count" inputmode="numeric" maxlength="14" aria-label="实际采购根数"><template #append>根</template></ElInput>
              <ElInput
                v-if="!row.raw_bar_length_m"
                v-model="row.actual_purchase_quantity"
                :aria-label="`第 ${row.line_number} 行实际采购数量`"
                data-testid="confirm-quantity"
                inputmode="decimal"
                placeholder="请输入数量"
                @blur="row.actual_purchase_quantity = formatQuantityInput(row.actual_purchase_quantity)"
              ><template #append>{{ row.source_unit_text || '单位未识别' }}</template></ElInput>
            </template>
          </ElTableColumn>
          <ElTableColumn label="折算采购米数" width="180">
            <template #default="{ row }"><span v-if="row.raw_bar_length_m" class="pipe-meters" :title="pipeMetersLabel(row)">{{ pipeMetersLabel(row) }}</span><span v-else>—</span></template>
          </ElTableColumn>
          <ElTableColumn label="采购单价（管材元/米）" width="164">
            <template #default="{ row }"><ElInput v-model="row.unit_price" :aria-label="`第 ${row.line_number} 行采购单价`" data-testid="confirm-price" inputmode="decimal" placeholder="请输入单价" /></template>
          </ElTableColumn>
          <ElTableColumn label="采购金额（元）" width="173" align="left">
            <template #default="{ row }"><strong>{{ lineAmount(row) }}</strong></template>
          </ElTableColumn>
        </ElTable>
      </section>

      <footer class="action-bar">
        <div class="summary-counts">采购明细 <strong>{{ order.lines.length }}</strong> 项 <span>·</span> 已选供应商 <strong>{{ supplierCount }}</strong> 家</div>
        <div class="summary-actions">
          <div class="mailing-panel"><span>是否邮寄</span><ElRadioGroup v-model="order.is_mailed" aria-label="是否邮寄"><ElRadio :value="false">否</ElRadio><ElRadio :value="true">是</ElRadio></ElRadioGroup></div>
          <div class="total"><span>采购总金额</span><strong>¥ {{ money(localTotal) }}</strong></div>
          <ElButton class="save-button" :loading="saving" :disabled="!canEdit || confirming || loading || !optionsReady" @click="saveChanges()">保存修改</ElButton>
          <ElButton class="confirm-button" data-testid="confirm-next" type="primary" :loading="confirming" :disabled="!canEdit || (order.status === 'DRAFT' && !canSubmit) || saving || loading || !optionsReady" @click="confirmAndContinue">
            {{ order.status === 'DRAFT' ? '确认并选择模板' : '保存并继续' }}<img :src="rightIcon" alt="" class="purchase-icon" />
          </ElButton>
        </div>
      </footer>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as crm;
@use '@/styles/theme/detail' as detail;
.confirm-page { height: auto; min-height: 0; box-sizing: border-box; padding: 0; display: flex; flex-direction: column; color: crm.$crm-text-primary; background: transparent; font-family: crm.$crm-font-body; font-size: 14px;
  --el-color-primary: #{crm.$crm-primary}; --el-text-color-primary: #{crm.$crm-text-primary}; --el-text-color-regular: #{crm.$crm-text-regular}; --el-text-color-placeholder: #{crm.$crm-text-muted}; --el-border-color: #{crm.$crm-border-default}; --el-border-color-light: #{crm.$crm-border-subtle}; --el-fill-color-blank: #{crm.$crm-color-surface}; --el-fill-color-light: #{crm.$crm-color-subtle}; --el-border-radius-base: 5px;
}
.purchase-icon { width: 16px; height: 16px; flex: none; }
.confirm-page :deep(.el-button > span) { display: inline-flex; align-items: center; gap: 10px; }
.page-heading { flex: none; min-height: 50px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 14px; }
.page-heading > div { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; }
.page-heading h1 { margin: 0; font: 700 38px/50px crm.$crm-font-display; letter-spacing: -1px; }
.page-heading p { margin: 8px 0 0; font-size: 13px; color: crm.$crm-text-secondary; }
.back-button { width: 142px; height: 42px; border-color: crm.$crm-primary; }
.detail-card { @include detail.surface; overflow: hidden; }
.detail-card h2 { margin: 0; font-size: 20px; line-height: 28px; }
.detail-card { flex: none; min-height: 150px; display: flex; flex-direction: column; margin-bottom: 14px; }
.detail-card > header { display: flex; flex: 0 0 53px; align-items: center; justify-content: space-between; padding: 0 18px; }
.detail-title-context { display: flex; min-width: 0; align-items: center; gap: 14px; }
.detail-title-context > span, .source-context span, .product-context span { flex: none; color: crm.$crm-text-secondary; font-size: 12px; }
.source-context, .product-context { display: flex; min-width: 0; align-items: center; gap: 8px; padding-left: 14px; border-left: 1px solid crm.$crm-border-default; }
.source-context strong, .product-context strong, .purchase-order-number { overflow: hidden; color: crm.$crm-text-primary; font-size: 13px; font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.product-context { flex: 1; }
.product-context strong { max-width: 190px; }
.product-context small { overflow: hidden; color: crm.$crm-text-secondary; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.purchase-order-number { flex: none; margin-left: 14px; }
.detail-table { flex: none; min-height: 0; width: 100%; --el-table-border-color: var(--erp-table-grid); --el-table-tr-bg-color: var(--erp-table-body-fill); --el-table-bg-color: var(--erp-table-body-fill); --el-table-header-bg-color: var(--erp-table-header-fill); --el-table-row-hover-bg-color: var(--erp-color-hover); }
.confirm-page .detail-card .detail-table :deep(.el-table__header tr),
.confirm-page .detail-card .detail-table :deep(.el-table__header th.el-table__cell) { height: 40px !important; }
.confirm-page .detail-card .detail-table :deep(.el-table__header th.el-table__cell) { padding: 0 !important; border-right: 1px solid var(--erp-table-grid); background: var(--erp-table-header-fill); color: var(--erp-table-header-text); font-size: 11px; font-weight: 400; }
.confirm-page .detail-card .detail-table :deep(.el-table__body tr),
.confirm-page .detail-card .detail-table :deep(.el-table__body td.el-table__cell) { height: 40px !important; }
.confirm-page .detail-card .detail-table :deep(.el-table__body td.el-table__cell) { padding: 0 !important; border-right: 1px solid var(--erp-table-grid); color: var(--erp-table-text); }
.confirm-page .detail-card .detail-table :deep(.el-table__header th:first-child),
.confirm-page .detail-card .detail-table :deep(.el-table__body td:first-child) { border-left: 0; }
.confirm-page .detail-card .detail-table :deep(.cell) { padding: 0 16px; font-size: 12px; line-height: 18px; }
.confirm-page .detail-card .detail-table :deep(th:first-child .cell),
.confirm-page .detail-card .detail-table :deep(td:first-child .cell) { padding: 0 8px !important; }
.confirm-page .detail-card .detail-table :deep(th .cell) { font-size: 11px; line-height: 16px; white-space: nowrap; }
.detail-table :deep(.el-table__inner-wrapper::before), .detail-table :deep(.el-table__inner-wrapper::after) { display: none; }
.confirm-page .detail-card .detail-table :deep(.el-table__header th.el-table__cell:last-child),
.confirm-page .detail-card .detail-table :deep(.el-table__body td.el-table__cell:last-child) { border-right: 0; }
.detail-table :deep(.el-table__body tr:last-child td) { border-bottom: 0; }
.detail-table :deep(.el-input), .detail-table :deep(.el-select), .detail-table :deep(.el-date-editor) { width: 100%; height: 32px; }
.detail-table :deep(.el-input__wrapper), .detail-table :deep(.el-select__wrapper) { height: 32px; min-height: 32px; box-sizing: border-box; font-size: 12px; }
.detail-table :deep(.el-input__wrapper) { padding: 1px 13px; }
.detail-table :deep(.el-input__prefix) { margin-right: 4px; }
.detail-table :deep(.el-input-group__append) { box-sizing: border-box; flex: 0 0 64px; width: 64px; padding: 0; font-size: 12px; }
.material-cell, .quantity-cell { display: flex; min-width: 0; }
.material-cell strong, .quantity-cell strong { font-size: 13px; font-weight: 500; }
.material-cell strong, .material-detail { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.material-detail { display: block; color: crm.$crm-text-secondary; font-size: 12px; }
.material-attribute-tooltip { min-width: 180px; line-height: 24px; font-size: 14px; }
.material-attribute-tooltip > div { display: flex; gap: 8px; }
.material-attribute-tooltip span { color: var(--erp-color-text-secondary); min-width: 42px; }
.quantity-cell { flex-direction: row; align-items: center; justify-content: flex-end; gap: 4px; white-space: nowrap; }
.quantity-cell small { color: crm.$crm-text-secondary; font-size: 12px; line-height: 19px; }
.action-bar { @include detail.surface; display: flex; flex: none; flex-wrap: wrap; min-height: 72px; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 16px; }
.summary-counts { display: flex; align-items: center; gap: 10px; font-size: 16px; white-space: nowrap; }
.summary-counts strong { color: crm.$crm-primary; font-weight: 500; }
.summary-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; }
.summary-actions :deep(.el-button) { height: 42px; margin: 0; }
.save-button { width: 134px; border-color: crm.$crm-primary; color: crm.$crm-primary; }
.confirm-button { width: 200px; }
.mailing-panel { display: flex; align-items: center; gap: 24px; width: 228px; white-space: nowrap; }
.mailing-panel :deep(.el-radio) { margin-right: 24px; }
.mailing-panel :deep(.el-radio:last-child) { margin: 0; }
.mailing-panel :deep(.el-radio__inner) { width: 18px; height: 18px; border-color: crm.$crm-text-muted; }
.mailing-panel :deep(.is-checked .el-radio__inner) { border-color: crm.$crm-primary; }
.total { display: flex; align-items: center; gap: 12px; padding-left: 38px; margin-left: 16px; border-left: 1px solid crm.$crm-border-default; height: 44px; white-space: nowrap; }
.total strong { font-size: 28px; color: crm.$crm-primary; font-weight: 500; }
.load-error { display: flex; align-items: center; gap: 20px; padding: 30px; background: crm.$crm-color-surface; }

:global(.purchase-confirm-message-box) {
  box-sizing: border-box;
  width: 480px;
  max-width: calc(100vw - 32px);
  padding: 0;
  border: 1px solid crm.$crm-border-default;
  border-radius: crm.$crm-radius-2;
  background: crm.$crm-color-surface;
  font-family: crm.$crm-font-body;
  --el-color-primary: #{crm.$crm-primary};
  --el-color-primary-light-3: #{crm.$crm-primary-light-3};
  --el-color-primary-dark-2: #{crm.$crm-primary-pressed};
  --el-color-primary-light-9: #{crm.$crm-color-selected};
  --el-text-color-primary: #{crm.$crm-text-primary};
  --el-text-color-regular: #{crm.$crm-text-regular};
  --el-border-color: #{crm.$crm-border-default};
}
:global(.purchase-confirm-message-box .el-message-box__header) { min-height: 44px; box-sizing: border-box; padding: 12px 48px 8px 16px; }
:global(.purchase-confirm-message-box .el-message-box__title) { color: crm.$crm-text-primary; font-size: 16px; font-weight: 500; line-height: 24px; }
:global(.purchase-confirm-message-box .el-message-box__headerbtn) { top: 6px; right: 8px; width: 32px; height: 32px; font-size: 16px; }
:global(.purchase-confirm-message-box .el-message-box__content) { padding: 4px 16px 16px; color: crm.$crm-text-regular; font-size: 13px; line-height: 20px; }
:global(.purchase-confirm-message-box .el-message-box__status) { margin-right: 12px; font-size: 20px !important; }
:global(.purchase-confirm-message-box .el-message-box__message) { line-height: 20px; }
:global(.purchase-confirm-message-box .el-message-box__btns) { gap: 12px; padding: 0 16px 16px; }
:global(.purchase-confirm-message-box .el-message-box__btns .el-button) { min-width: 72px; height: 32px !important; min-height: 32px !important; margin-left: 0; padding: 0 16px; border-radius: crm.$crm-radius-2; font-size: 13px; }
:global(.purchase-confirm-message-box .el-message-box__btns .el-button--primary) { border-color: var(--erp-button-primary-border); color: var(--erp-color-text-inverse); background: var(--erp-button-primary-surface); }
:global(.purchase-confirm-message-box .el-message-box__btns .el-button--primary:hover) { border-color: var(--erp-button-primary-border); background: var(--erp-button-primary-hover-surface); }
:global(.purchase-confirm-errors p) { margin: 0 0 8px; }
:global(.purchase-confirm-errors ul) { box-sizing: border-box; max-height: min(50dvh, 360px); margin: 0; padding-left: 20px; overflow-y: auto; }
:global(.purchase-confirm-errors li + li) { margin-top: 4px; }

.pipe-meters { white-space: nowrap; }
@media (max-width: 1300px) {
  .summary-actions { gap: 10px; }
  .mailing-panel { width: 200px; gap: 12px; }
  .mailing-panel :deep(.el-radio) { margin-right: 12px; }
  .total { padding-left: 20px; margin-left: 0; }
  .total strong { font-size: 24px; }
  .save-button { width: 118px; }
  .confirm-button { width: 178px; }
}
</style>
