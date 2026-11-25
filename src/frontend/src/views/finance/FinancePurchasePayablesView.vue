<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import {
  confirmPurchasePayable,
  fetchPurchasePayable,
  fetchPurchasePayables,
  updatePurchasePayablePricing,
  voidPurchasePayable,
} from '@/api/financePurchasePayables'
import type {
  PurchasePayable,
  PurchasePayablePricingInput,
  PurchasePayableQuery,
  PurchasePayableStatus,
} from '@/types/financePurchasePayables'

const auth = useAuthStore()
const can = (action: 'view' | 'change' | 'confirm' | 'void') => auth.user?.is_superuser === true || auth.hasPermission(`finance.${action}_purchasepayable`)
const rows = ref<PurchasePayable[]>([])
const total = ref(0)
const page = ref(1)
const loading = ref(false)
const listError = ref('')
const search = ref('')
const status = ref<PurchasePayableStatus | ''>('')
const applied = reactive<{ q: string; status?: PurchasePayableStatus }>({ q: '' })
const dialog = ref(false)
const detailLoading = ref(false)
const record = ref<PurchasePayable>()
const detailError = ref('')
const saving = ref(false)
const voidReason = ref('')
const voiding = ref(false)
const form = reactive<PurchasePayablePricingInput>({ tax_mode: '', freight_mode: '', lines: [] })

const statusLabel: Record<PurchasePayableStatus, string> = {
  WAITING_PRICE: '待确认价格',
  WAITING_FINANCE_CONFIRM: '待财务确认',
  WAITING_PAYMENT: '待付款',
  VOID: '已作废',
}
function statusText(value: unknown) {
  return typeof value === 'string' && value in statusLabel ? statusLabel[value as PurchasePayableStatus] : '未知状态'
}

const detailTitle = computed(() => record.value ? `采购应付 ${record.value.number}` : '采购应付详情')
const canEditPrice = computed(() => !!record.value?.can_price && can('change'))
const canConfirm = computed(() => !!record.value?.can_confirm && can('confirm'))
const canVoid = computed(() => !!record.value && !['WAITING_PAYMENT', 'VOID'].includes(record.value.status) && can('void'))
const supplierName = (item: PurchasePayable) => item.supplier_name || item.supplier_name_snapshot || item.supplier?.name || item.supplier_number || item.supplier_number_snapshot || '—'
const purchaseOrderNumber = (item: PurchasePayable) => item.purchase_order_number || item.purchase_order_number_snapshot || '—'
const inboundNumber = (item: PurchasePayable) => item.inbound_number || item.inbound_number_snapshot || '—'
const currencyCode = (item: PurchasePayable) => item.currency_code || item.currency_code_snapshot
const lineMaterial = (line: PurchasePayable['lines'][number]) => line.material || line.material_snapshot || '—'
const lineSpecification = (line: PurchasePayable['lines'][number]) => line.specification || line.specification_snapshot || '—'
const lineUnit = (line: PurchasePayable['lines'][number]) => line.accepted_unit || line.source_unit_text_snapshot || line.price_unit_text || '—'
const hasSettlementQuantity = (line: PurchasePayable['lines'][number]) =>
  Number(line.settlement_quantity ?? line.accepted_quantity) > 0
const lineCurrency = (line: PurchasePayable['lines'][number]) => line.currency_code || line.currency_code_snapshot

function message(error: unknown) {
  if (axios.isAxiosError(error)) return error.response?.data?.error?.message || '请求未完成，请重试。'
  return error instanceof Error ? error.message : '请求失败，请重试。'
}

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
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
  }
  applied.q = search.value.trim()
  applied.status = status.value || undefined
  page.value = 1
  void loadList()
}

async function loadList() {
  if (!can('view')) return
  loading.value = true
  listError.value = ''
  const query: PurchasePayableQuery = {
    page: page.value,
    page_size: 20,
    ...(applied.q ? { q: applied.q } : {}),
    ...(applied.status ? { status: applied.status } : {}),
  }
  try {
    const result = await fetchPurchasePayables(query)
    rows.value = result.data
    total.value = result.meta.total
    page.value = result.meta.page
  } catch (error) {
    listError.value = message(error)
  } finally {
    loading.value = false
  }
}

async function openDetail(row: PurchasePayable) {
  dialog.value = true
  detailLoading.value = true
  detailError.value = ''
  record.value = undefined
  form.tax_mode = ''
  form.freight_mode = ''
  form.lines = []
  try {
    const result = await fetchPurchasePayable(row.id)
    record.value = result
    form.tax_mode = result.tax_mode || ''
    form.freight_mode = result.freight_mode || ''
    form.lines = result.lines.map(line => ({
      line_id: line.line_id,
      unit_price: line.unit_price || line.reference_unit_price || '',
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
  const payable = record.value
  if (!payable || !canEditPrice.value || saving.value) return
  const positiveLineIds = new Set(payable.lines.filter(hasSettlementQuantity).map(line => line.line_id))
  const lines = form.lines.filter(line => positiveLineIds.has(line.line_id))
  if (lines.some(line => !line.unit_price || Number(line.unit_price) <= 0 || !line.price_unit_text)) {
    ElMessage.warning('请填写大于零的单价和计价单位。')
    return
  }
  saving.value = true
  try {
    record.value = await updatePurchasePayablePricing(payable.id, { ...form, lines }, payable.etag)
    ElMessage.success('价格已保存。')
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

onMounted(() => { void loadList() })
</script>

<template>
  <section class="finance-purchase-payables page-shell">
    <div class="page-toolbar">
      <div>
        <h1>采购应付</h1>
        <p>收货后可先核价，质检完成后由财务确认应付。</p>
      </div>
      <div class="toolbar-actions">
        <el-button @click="applyFilter(true)">重置</el-button>
        <el-button type="primary" :loading="loading" @click="loadList">刷新</el-button>
      </div>
    </div>

    <el-card shadow="never">
      <div class="filter-row">
        <el-input v-model="search" clearable placeholder="编号、供应商、采购单或入库单" @keyup.enter="applyFilter" />
        <el-select v-model="status" clearable placeholder="全部状态" @change="applyFilter">
          <el-option v-for="(label, key) in statusLabel" :key="key" :label="label" :value="key" />
        </el-select>
        <el-button type="primary" @click="applyFilter">查询</el-button>
      </div>
      <el-alert v-if="listError" type="error" :closable="false" :title="listError" class="list-error" />
      <el-table v-loading="loading" :data="rows" row-key="id" empty-text="暂无采购应付">
        <el-table-column prop="number" label="应付单号" min-width="160" />
        <el-table-column label="状态" width="132">
          <template #default="{ row }"><el-tag :type="row.status === 'VOID' ? 'info' : row.status === 'WAITING_PAYMENT' ? 'success' : 'warning'">{{ row.status_display || statusText(row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="供应商" min-width="180"><template #default="{ row }">{{ supplierName(row) }}</template></el-table-column>
        <el-table-column label="采购单 / 入库单" min-width="190"><template #default="{ row }">{{ purchaseOrderNumber(row) }} / {{ inboundNumber(row) }}</template></el-table-column>
        <el-table-column label="入库日期" width="170"><template #default="{ row }">{{ formatDate(row.inbound_date) }}</template></el-table-column>
        <el-table-column label="金额" width="150"><template #default="{ row }">{{ formatAmount(row.amount, currencyCode(row)) }}</template></el-table-column>
        <el-table-column label="操作" width="100" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openDetail(row)">详情</el-button></template></el-table-column>
      </el-table>
      <div class="pagination"><el-pagination v-model:current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="loadList" /></div>
    </el-card>

    <AppWindowDialog v-model="dialog" :title="detailTitle" width="1080px">
      <div v-loading="detailLoading" class="detail-content">
        <el-alert v-if="detailError" type="error" :closable="false" :title="detailError" />
        <template v-if="record">
          <div class="detail-summary">
            <div><span>供应商</span><strong>{{ supplierName(record) }}</strong></div>
            <div><span>采购单</span><strong>{{ purchaseOrderNumber(record) }}</strong></div>
            <div><span>入库单</span><strong>{{ inboundNumber(record) }}</strong></div>
            <div><span>状态</span><el-tag>{{ record.status_display || statusLabel[record.status] }}</el-tag></div>
            <div><span>金额</span><strong>{{ formatAmount(record.amount, currencyCode(record)) }}</strong></div>
          </div>
          <el-alert type="info" :closable="false" title="按根验收的管材使用采购批次的约定公斤数结算。" />
          <el-table :data="record.lines" row-key="line_id" class="line-table">
            <el-table-column label="物料" min-width="160"><template #default="{ row }">{{ lineMaterial(row) }}</template></el-table-column>
            <el-table-column label="规格" min-width="130"><template #default="{ row }">{{ lineSpecification(row) }}</template></el-table-column>
            <el-table-column label="结算数量" width="130"><template #default="{ row }">{{ row.settlement_quantity ?? row.accepted_quantity }} {{ lineUnit(row) }}</template></el-table-column>
            <el-table-column label="合格入库" width="120"><template #default="{ row }">{{ row.receipt_bar_counts ? row.accepted_bar_count + ' 根' : row.accepted_weight_kg ?? '待确认' }}</template></el-table-column>
            <el-table-column label="单价" width="180">
              <template #default="{ row, $index }">
                <template v-if="canEditPrice && hasSettlementQuantity(row)"><el-input v-model="form.lines[$index].unit_price" size="small" /><el-input v-model="form.lines[$index].price_unit_text" size="small" class="unit-input" /></template>
                <template v-else>{{ row.unit_price || '待确认' }} {{ row.price_unit_text || row.price_unit || '' }}</template>
              </template>
            </el-table-column>
            <el-table-column label="金额" width="130"><template #default="{ row }">{{ formatAmount(row.amount, lineCurrency(row)) }}</template></el-table-column>
            <el-table-column label="价格来源" min-width="130"><template #default="{ row, $index }"><el-input v-if="canEditPrice && hasSettlementQuantity(row)" v-model="form.lines[$index].price_source" size="small" placeholder="采购确认" /><span v-else>{{ row.price_source || '—' }}</span></template></el-table-column>
          </el-table>
          <div class="detail-note">
            <span>含税口径：</span>
            <el-input v-if="canEditPrice" v-model="form.tax_mode" size="small" placeholder="待确认时填写说明" />
            <strong v-else>{{ record.tax_mode || '待确认' }}</strong>
            <span>运费口径：</span>
            <el-input v-if="canEditPrice" v-model="form.freight_mode" size="small" placeholder="待确认时填写说明" />
            <strong v-else>{{ record.freight_mode || '待确认' }}</strong>
            <span>{{ record.blocked_reason || '' }}</span>
          </div>
        </template>
      </div>
      <template #footer>
        <el-button @click="dialog = false">关闭</el-button>
        <el-button v-if="canEditPrice" type="primary" :loading="saving" @click="savePricing">保存价格</el-button>
        <el-button v-if="canConfirm" type="success" :loading="saving" @click="confirmPayable">确认应付</el-button>
        <el-button v-if="canVoid" type="danger" plain :loading="voiding" @click="voidPayable">作废</el-button>
      </template>
    </AppWindowDialog>
  </section>
</template>

<style scoped>
.finance-purchase-payables { padding: 24px; }
.page-toolbar, .filter-row, .toolbar-actions, .pagination, .detail-summary { display: flex; align-items: center; gap: 12px; }
.page-toolbar { justify-content: space-between; margin-bottom: 18px; }
h1 { margin: 0; font-size: 24px; }
.page-toolbar p { margin: 6px 0 0; color: var(--el-text-color-secondary); }
.filter-row { margin-bottom: 16px; }
.filter-row .el-input { max-width: 320px; }
.filter-row .el-select { width: 160px; }
.list-error { margin-bottom: 12px; }
.pagination { justify-content: flex-end; margin-top: 16px; }
.detail-content { min-height: 220px; }
.detail-summary { flex-wrap: wrap; margin-bottom: 16px; }
.detail-summary > div { min-width: 150px; }
.detail-summary span { display: block; color: var(--el-text-color-secondary); font-size: 12px; margin-bottom: 4px; }
.line-table { margin-top: 16px; }
.unit-input { margin-top: 4px; }
.detail-note { margin-top: 12px; color: var(--el-text-color-secondary); font-size: 13px; }
</style>
