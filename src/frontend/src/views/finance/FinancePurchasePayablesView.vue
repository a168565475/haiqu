<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import {
  confirmPurchasePayable,
  fetchPurchasePayable,
  fetchPurchasePayableLines,
  fetchPurchasePayableFilterOptions,
  updatePurchasePayablePricing,
  voidPurchasePayable,
} from '@/api/financePurchasePayables'
import type {
  PurchasePayable,
  PurchasePayablePricingInput,
  PurchasePayableQuery,
  PurchasePayableStatus,
  PurchasePayableListLine,
  PurchasePayableFilterOptions,
} from '@/types/financePurchasePayables'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const can = (action: 'view' | 'change' | 'confirm' | 'void') => auth.user?.is_superuser === true || auth.hasPermission(`finance.${action}_purchasepayable`)
const rows = ref<PurchasePayableListLine[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const loaded = ref(false)
const listError = ref('')
const search = ref('')
const status = ref<PurchasePayableStatus | ''>('')
const supplier = ref('')
const dates = ref<[string, string] | null>(null)
const suppliers = ref<PurchasePayableFilterOptions['suppliers']>([])
const optionsError = ref('')
const applied = reactive<Omit<PurchasePayableQuery, 'page' | 'page_size'>>({})
const filtered = computed(() => !!(applied.q || applied.status || applied.supplier_id || applied.inbound_date_from || applied.inbound_date_to))
const dialog = ref(false)
const detailLoading = ref(false)
const record = ref<PurchasePayable>()
const detailError = ref('')
const saving = ref(false)
const voidReason = ref('')
const voiding = ref(false)
const form = reactive<PurchasePayablePricingInput>({ tax_mode: '', freight_mode: '', lines: [] })

const statusLabel: Record<PurchasePayableStatus, string> = {
  WAITING_PRICE: '待核价',
  WAITING_FINANCE_CONFIRM: '待财务确认',
  WAITING_PAYMENT: '待付款',
  VOID: '已作废',
}

const detailTitle = computed(() => record.value ? `采购应付 ${record.value.number}` : '采购应付详情')
const canEditPrice = computed(() => !!record.value && ['WAITING_PRICE', 'WAITING_FINANCE_CONFIRM'].includes(record.value.status) && can('change'))
const canConfirm = computed(() => !!record.value && record.value.status === 'WAITING_FINANCE_CONFIRM' && can('confirm'))
const canVoid = computed(() => !!record.value && !['WAITING_PAYMENT', 'VOID'].includes(record.value.status) && can('void'))
const supplierName = (item: PurchasePayable) => item.supplier_name || item.supplier_name_snapshot || item.supplier?.name || item.supplier_number || item.supplier_number_snapshot || '—'
const purchaseOrderNumber = (item: PurchasePayable) => item.purchase_order_number || item.purchase_order_number_snapshot || '—'
const inboundNumber = (item: PurchasePayable) => item.inbound_number || item.inbound_number_snapshot || '—'
const currencyCode = (item: PurchasePayable) => item.currency_code || item.currency_code_snapshot
const lineMaterial = (line: PurchasePayable['lines'][number]) => line.part_name || line.part_name_snapshot || line.material || line.material_snapshot || '—'
const lineSpecification = (line: PurchasePayable['lines'][number]) => line.specification || line.specification_snapshot || '—'
const lineUnit = (line: PurchasePayable['lines'][number]) => line.accepted_unit || line.source_unit_text_snapshot || line.price_unit_text || '—'
const lineCurrency = (line: PurchasePayable['lines'][number]) => line.currency_code || line.currency_code_snapshot
const unitText = (value: string | null | undefined) => ['KG', '千克'].includes((value || '').toUpperCase()) ? 'KG' : value || '待确认'
const quantityText = (value: string | null | undefined, unit: string | null | undefined) => value == null ? '待确认' : `${value.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')} ${unitText(unit)}`
const priceText = (value: string | null | undefined, line: PurchasePayable['lines'][number], unit: string | null | undefined) => value == null ? '待确认' : `${formatAmount(value, lineCurrency(line))} / ${unitText(unit)}`

function message(error: unknown) {
  if (axios.isAxiosError(error)) return error.response?.data?.error?.message || '请求未完成，请重试。'
  return error instanceof Error ? error.message : '请求失败，请重试。'
}

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function formatAmount(value: string | null | undefined, currency: string | null | undefined) {
  if (value === null || value === undefined || value === '') return '待确认'
  return `${value}${currency ? ` ${currency}` : ''}`
}

function applyFilter(reset = false) {
  if (reset) {
    search.value = ''
    status.value = ''
    supplier.value = ''
    dates.value = null
  }
  applied.q = search.value.trim()
  applied.status = status.value || undefined
  applied.supplier_id = supplier.value || undefined
  applied.inbound_date_from = dates.value?.[0]
  applied.inbound_date_to = dates.value?.[1]
  page.value = 1
  void loadList()
}

async function loadList() {
  if (!can('view')) return
  loading.value = true
  listError.value = ''
  const query: PurchasePayableQuery = {
    ...applied,
    page: page.value,
    page_size: 20,
  }
  try {
    const result = await fetchPurchasePayableLines(query)
    rows.value = result.data
    total.value = result.meta.total
    page.value = result.meta.page
    loaded.value = true
  } catch (error) {
    listError.value = message(error)
    rows.value = []
    loaded.value = false
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  if (!can('view')) return
  optionsError.value = ''
  try {
    suppliers.value = (await fetchPurchasePayableFilterOptions()).suppliers
  } catch (error) {
    optionsError.value = message(error)
  }
}

async function openDetail(id: string) {
  dialog.value = true
  detailLoading.value = true
  detailError.value = ''
  record.value = undefined
  form.tax_mode = ''
  form.freight_mode = ''
  form.lines = []
  try {
    const result = await fetchPurchasePayable(id)
    record.value = result
    form.tax_mode = result.tax_mode || ''
    form.freight_mode = result.freight_mode || ''
    form.lines = result.lines.map(line => ({
      line_id: line.line_id,
      unit_price: line.unit_price ?? '',
      price_unit_text: line.price_unit_text || line.price_unit || line.accepted_unit || line.source_unit_text_snapshot || '',
      price_source: line.price_source || '',
      price_remark: line.price_remark || line.price_confirmation_remark || '',
    }))
  } catch (error) {
    detailError.value = message(error)
  } finally {
    detailLoading.value = false
  }
}

async function savePricing() {
  if (!record.value || !canEditPrice.value || saving.value) return
  if (form.lines.some(line => !line.unit_price || Number(line.unit_price) <= 0 || !line.price_unit_text)) {
    ElMessage.warning('请填写大于零的单价和计价单位。')
    return
  }
  saving.value = true
  try {
    record.value = await updatePurchasePayablePricing(record.value.id, form, record.value.etag)
    ElMessage.success('价格已保存，等待财务确认。')
    await loadList()
  } catch (error) {
    ElMessage.error(message(error))
  } finally {
    saving.value = false
  }
}

async function confirmPayable() {
  if (!record.value || !canConfirm.value || saving.value) return
  if (!record.value.tax_mode?.trim() || !record.value.freight_mode?.trim()) {
    ElMessage.warning('含税和运费口径尚未确认，暂不能确认正式应付。')
    return
  }
  try {
    await ElMessageBox.confirm('确认后将进入待付款状态，是否继续？', '确认采购应付', { type: 'warning' })
  } catch {
    return
  }
  saving.value = true
  try {
    record.value = await confirmPurchasePayable(record.value.id, record.value.etag)
    ElMessage.success('采购应付已确认。')
    await loadList()
  } catch (error) {
    ElMessage.error(message(error))
  } finally {
    saving.value = false
  }
}

async function voidPayable() {
  if (!record.value || !canVoid.value || voiding.value) return
  let reason = ''
  try {
    const result = await ElMessageBox.prompt('请输入作废原因', '作废采购应付', { inputValue: voidReason.value, inputValidator: value => !!value?.trim() || '请填写作废原因' })
    reason = result.value.trim()
  } catch {
    return
  }
  if (!reason) return
  voiding.value = true
  try {
    record.value = await voidPurchasePayable(record.value.id, reason, record.value.etag)
    ElMessage.success('采购应付已作废。')
    await loadList()
  } catch (error) {
    ElMessage.error(message(error))
  } finally {
    voiding.value = false
  }
}

watch(() => route.query.payable_id, id => {
  if (route.name === 'finance-purchase-payables' && typeof id === 'string' && can('view')) void openDetail(id)
}, { immediate: true })
watch(dialog, visible => {
  if (!visible && route.name === 'finance-purchase-payables' && route.query.payable_id) {
    void router.replace({ query: { ...route.query, payable_id: undefined } })
  }
})
onMounted(() => { void loadList(); void loadOptions() })
</script>

<template>
  <section class="finance-purchase-payables erp-glass-list">
    <el-alert v-if="!can('view')" title="没有采购应付查看权限，请联系授权管理员。" type="warning" :closable="false" />
    <template v-else>
      <div class="erp-list-filter">
        <div class="erp-list-heading">
          <div class="erp-list-title-row"><h1>采购应付</h1><span class="erp-list-count">{{ loaded ? `${total} 条明细` : '尚未加载' }}</span></div>
        </div>
        <div class="erp-list-filters">
          <label>搜索<el-input v-model="search" aria-label="搜索采购应付" placeholder="物料 / 规格 / 单号" clearable :disabled="loading" @keyup.enter="applyFilter()" /></label>
          <label>供应商<el-select v-model="supplier" aria-label="供应商" placeholder="全部供应商" clearable filterable :disabled="loading || !!optionsError"><el-option v-for="item in suppliers" :key="item.id" :value="item.id" :label="item.name || item.number" /></el-select></label>
          <label class="date-filter">入库日期<el-date-picker v-model="dates" aria-label="入库日期范围" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" range-separator="至" :disabled="loading" /></label>
          <label>状态<el-select v-model="status" aria-label="应付状态" placeholder="全部状态" clearable :disabled="loading"><el-option v-for="(label, key) in statusLabel" :key="key" :label="label" :value="key" /></el-select></label>
          <div class="erp-list-filter-actions"><el-button :disabled="loading" @click="applyFilter(true)">重置</el-button><el-button :disabled="loading" @click="applyFilter()">应用筛选</el-button></div>
        </div>
        <el-alert v-if="optionsError" :title="`供应商选项加载失败：${optionsError}`" type="error" :closable="false"><el-button link @click="loadOptions">重试</el-button></el-alert>
      </div>
      <div class="erp-list-data">
        <div class="erp-list-toolbar"><span class="list-caption">入库物料明细</span><el-button :loading="loading" @click="loadList">刷新</el-button></div>
        <el-alert v-if="listError" type="error" :closable="false" :title="listError"><el-button link @click="loadList">重试</el-button></el-alert>
        <div v-loading="loading" class="erp-list-table-frame" :aria-busy="loading">
          <el-table :data="rows" row-key="line_id" border height="100%">
            <el-table-column prop="inbound_date" label="入库日期" width="110" />
            <el-table-column prop="supplier_name" label="供应商" min-width="150" show-overflow-tooltip />
            <el-table-column label="物料名称" min-width="150" show-overflow-tooltip><template #default="{ row }">{{ lineMaterial(row) }}</template></el-table-column>
            <el-table-column prop="material" label="材质" min-width="90" show-overflow-tooltip />
            <el-table-column prop="specification" label="规格" min-width="150" show-overflow-tooltip />
            <el-table-column label="结算数量" min-width="125" align="right"><template #default="{ row }">{{ quantityText(row.settlement_quantity, row.source_unit_text_snapshot) }}</template></el-table-column>
            <el-table-column label="采购参考单价" min-width="155" align="right" show-overflow-tooltip><template #default="{ row }">{{ priceText(row.reference_unit_price, row, row.source_unit_text_snapshot) }}</template></el-table-column>
            <el-table-column label="核定单价" min-width="155" align="right" show-overflow-tooltip><template #default="{ row }">{{ priceText(row.unit_price, row, row.price_unit_text) }}</template></el-table-column>
            <el-table-column label="应付金额" min-width="130" align="right"><template #default="{ row }">{{ formatAmount(row.amount, lineCurrency(row)) }}</template></el-table-column>
            <el-table-column label="应付状态" width="132"><template #default="{ row }"><el-tag :type="row.status === 'VOID' ? 'info' : row.status === 'WAITING_PAYMENT' ? 'success' : 'warning'">{{ row.status_display }}</el-tag></template></el-table-column>
            <el-table-column prop="inbound_number" label="来源入库单" min-width="170" show-overflow-tooltip />
            <el-table-column label="操作" width="96" fixed="right" align="center"><template #default="{ row }"><el-button link type="primary" @click="openDetail(row.payable_id)">{{ can('change') && ['WAITING_PRICE', 'WAITING_FINANCE_CONFIRM'].includes(row.status) ? '核价详情' : '详情' }}</el-button></template></el-table-column>
            <template #empty><span v-if="loading">正在加载采购应付…</span><span v-else-if="listError">采购应付尚未成功加载</span><div v-else-if="filtered">没有匹配的采购应付明细 <el-button link @click="applyFilter(true)">清除筛选</el-button></div><span v-else>暂无采购应付明细</span></template>
          </el-table>
        </div>
        <div class="erp-list-footer"><span>数量按行列示单位，金额按行列示币种</span><el-pagination v-if="loaded" v-model:current-page="page" :page-size="20" :total="total" :disabled="loading" layout="prev, pager, next" @current-change="loadList" /></div>
      </div>
    </template>
  </section>
  <AppWindowDialog v-model="dialog" :title="detailTitle" :width="1440" :min-width="280" :minimizable="false">
    <div v-loading="detailLoading" class="payable-detail">
      <el-alert v-if="detailError" type="error" :closable="false" :title="detailError" />
      <template v-if="record">
        <dl class="document-facts">
          <div><dt>供应商</dt><dd>{{ supplierName(record) }}</dd></div>
          <div><dt>采购单</dt><dd>{{ purchaseOrderNumber(record) }}</dd></div>
          <div><dt>入库单</dt><dd>{{ inboundNumber(record) }}</dd></div>
          <div><dt>入库日期</dt><dd>{{ formatDate(record.inbound_date) }}</dd></div>
          <div><dt>账期月数</dt><dd>{{ record.payment_term_months ? record.payment_term_months + ' 个月' : '待确认' }}</dd></div>
          <div><dt>到期月份</dt><dd>{{ record.due_month ?? '—' }}</dd></div>
          <div><dt>应付状态</dt><dd>{{ record.status_display || statusLabel[record.status] }}</dd></div>
          <div><dt>整单应付金额</dt><dd>{{ formatAmount(record.amount, currencyCode(record)) }}</dd></div>
          <div><dt>财务确认人</dt><dd>{{ record.confirmed_by?.name || '待确认' }}</dd></div>
          <div><dt>财务确认时间</dt><dd>{{ formatDate(record.confirmed_at) }}</dd></div>
        </dl>
        <el-alert v-if="record.status === 'VOID'" :title="`作废原因：${record.void_reason}`" type="warning" :closable="false" />
        <el-alert v-else-if="record.blocked_reason" :title="record.blocked_reason" type="info" :closable="false" />
        <div class="detail-section"><h2>核价明细</h2><span>展开明细查看收货、退货及核价记录</span></div>
        <el-table :data="record.lines" row-key="line_id" border class="pricing-table">
          <el-table-column type="expand" width="48">
            <template #default="{ row, $index }">
              <dl class="document-facts line-facts">
                <div><dt>收货数量</dt><dd>{{ row.receipt_bar_counts ? row.receipt_bar_counts.received + ' 根' : quantityText(row.received_quantity, lineUnit(row)) }}</dd></div>
                <div><dt>退货数量</dt><dd>{{ row.receipt_bar_counts ? row.receipt_bar_counts.returned + ' 根' : quantityText(row.return_quantity, lineUnit(row)) }}</dd></div>
                <div><dt>合格结算数量</dt><dd>{{ quantityText(row.settlement_quantity, lineUnit(row)) }}</dd></div>
                <template v-if="!row.receipt_bar_counts">
                  <div><dt>收货重量</dt><dd>{{ quantityText(row.received_weight_kg, 'KG') }}</dd></div>
                  <div><dt>退货重量</dt><dd>{{ quantityText(row.return_weight_kg, 'KG') }}</dd></div>
                  <div><dt>合格重量</dt><dd>{{ quantityText(row.accepted_weight_kg, 'KG') }}</dd></div>
                </template>
                <div><dt>核价人</dt><dd>{{ row.price_confirmed_by_name || '待确认' }}</dd></div>
                <div><dt>核价时间</dt><dd>{{ formatDate(row.price_confirmed_at) }}</dd></div>
                <div><dt>价格来源</dt><dd><el-input v-if="canEditPrice" v-model="form.lines[$index].price_source" aria-label="价格来源" maxlength="100" :disabled="saving" /><span v-else>{{ row.price_source || '—' }}</span></dd></div>
                <div class="price-remark"><dt>核价备注</dt><dd><el-input v-if="canEditPrice" v-model="form.lines[$index].price_remark" aria-label="核价备注" maxlength="2000" :disabled="saving" /><span v-else>{{ row.price_remark || '—' }}</span></dd></div>
              </dl>
            </template>
          </el-table-column>
          <el-table-column label="物料名称" min-width="150" show-overflow-tooltip><template #default="{ row }">{{ lineMaterial(row) }}</template></el-table-column>
          <el-table-column label="材质" min-width="90" show-overflow-tooltip><template #default="{ row }">{{ row.material || row.material_snapshot || '—' }}</template></el-table-column>
          <el-table-column label="规格" min-width="150" show-overflow-tooltip><template #default="{ row }">{{ lineSpecification(row) }}</template></el-table-column>
          <el-table-column label="结算数量" min-width="125" align="right"><template #default="{ row }">{{ quantityText(row.settlement_quantity, lineUnit(row)) }}</template></el-table-column>
          <el-table-column label="采购参考单价" min-width="160" align="right"><template #default="{ row }">{{ priceText(row.reference_unit_price, row, lineUnit(row)) }}</template></el-table-column>
          <el-table-column label="核定单价" min-width="145" align="right"><template #default="{ row, $index }"><el-input v-if="canEditPrice" v-model="form.lines[$index].unit_price" class="erp-table-editor" :aria-label="`第${$index + 1}行核定单价`" inputmode="decimal" placeholder="待确认" :disabled="saving" /><span v-else>{{ row.unit_price ?? '待确认' }}</span></template></el-table-column>
          <el-table-column label="计价单位" width="105"><template #default="{ row, $index }"><el-input v-if="canEditPrice" v-model="form.lines[$index].price_unit_text" class="erp-table-editor" :aria-label="`第${$index + 1}行计价单位`" placeholder="待确认" :disabled="saving" /><span v-else>{{ unitText(row.price_unit_text) }}</span></template></el-table-column>
          <el-table-column label="应付金额" min-width="145" align="right"><template #default="{ row }">{{ formatAmount(row.amount, lineCurrency(row)) }}</template></el-table-column>
        </el-table>
        <el-form label-position="top" class="settlement-terms">
          <el-form-item label="含税口径"><el-input v-if="canEditPrice" v-model="form.tax_mode" aria-label="含税口径" placeholder="待确认" maxlength="50" :disabled="saving" /><span v-else>{{ record.tax_mode || '待确认' }}</span></el-form-item>
          <el-form-item label="运费口径"><el-input v-if="canEditPrice" v-model="form.freight_mode" aria-label="运费口径" placeholder="待确认" maxlength="50" :disabled="saving" /><span v-else>{{ record.freight_mode || '待确认' }}</span></el-form-item>
        </el-form>
      </template>
    </div>
    <template #footer>
      <el-button :disabled="saving || voiding" @click="dialog = false">关闭</el-button>
      <el-button v-if="canVoid" type="danger" plain :loading="voiding" :disabled="saving" @click="voidPayable">作废</el-button>
      <el-button v-if="canEditPrice" type="primary" :loading="saving" :disabled="voiding" @click="savePricing">保存价格</el-button>
      <el-button v-if="canConfirm" type="success" :loading="saving" :disabled="voiding" @click="confirmPayable">确认应付</el-button>
    </template>
  </AppWindowDialog>
</template>

<style scoped>
.finance-purchase-payables { --erp-list-row-height: 34px; }
.finance-purchase-payables .erp-list-heading h1 { font: 700 34px/44px 'Noto Serif SC Variable', 'Noto Serif SC', serif !important; }
.finance-purchase-payables .erp-list-table-frame :deep(th.el-table__cell) { height: 44px !important; }
.finance-purchase-payables .erp-list-table-frame :deep(th.el-table__cell),
.finance-purchase-payables .erp-list-table-frame :deep(td.el-table__cell) { border-right: 0; }
.finance-purchase-payables .erp-list-filters .el-input { width: 250px; max-width: 100%; }
.finance-purchase-payables .erp-list-filters .el-select { width: 160px; }
.finance-purchase-payables .date-filter :deep(.el-date-editor) { width: 260px; flex: none; }
.finance-purchase-payables .erp-list-toolbar { justify-content: space-between; }
.list-caption { color: var(--erp-color-text-secondary); font-size: 13px; }
.payable-detail { display: grid; gap: 16px; min-width: 0; color: var(--erp-color-text-primary); }
.document-facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin: 0; }
.document-facts dt { margin-bottom: 4px; font-size: 12px; color: var(--erp-color-text-secondary); }
.document-facts dd { margin: 0; font-size: 13px; overflow-wrap: anywhere; }
.line-facts { padding: 16px; grid-template-columns: repeat(3, minmax(0, 1fr)); }
.price-remark { grid-column: 1 / -1; }
.detail-section { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.detail-section h2 { margin: 0; font-size: 15px; }
.detail-section span { font-size: 12px; color: var(--erp-color-text-secondary); }
.pricing-table { min-width: 0; width: 100%; }
.settlement-terms { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.settlement-terms .el-form-item { margin-bottom: 0; }
@media (max-width: 760px) {
  .document-facts, .line-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .finance-purchase-payables .erp-list-filters > label { max-width: 100%; }
}
</style>
