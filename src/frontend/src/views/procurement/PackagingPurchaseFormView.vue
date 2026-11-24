<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import backIcon from '@/assets/procurement/create-back.svg'
import refreshIcon from '@/assets/procurement/create-refresh.svg'
import rightIcon from '@/assets/procurement/create-right.svg'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import {
  fetchPackagingPurchaseOptions, fetchPackagingPurchasePage, fetchPackagingPurchaseSources,
  preparePackagingPurchasePage, writePackagingPurchasePage,
} from '@/api/purchaseGroups'
import { useAuthStore } from '@/stores/auth'
import type { PackagingPurchaseSource, PurchaseBatchInput, PurchaseGroup, PurchaseGroupProgressLine } from '@/types/purchaseGroup'
import type { PurchaseBatchType, PurchaseOrderOptions } from '@/types/purchaseOrder'
import { compactDecimal } from '@/utils/compactDecimal'
import { createClientUuid } from '@/utils/clientUuid'
import { materialAttributeTable } from '@/utils/materialAttributes'
import PurchaseQuantitySources from './PurchaseQuantitySources.vue'
import { decimalParts, formatScaled, scaledProduct } from './purchaseAmounts'

interface PackagingLine {
  purchase_group_line_id: string
  group_id: string
  task_number: string
  source: PurchaseGroupProgressLine
  material_name: string
  supplier_id: string | null
  delivery_date: string
  actual_purchase_quantity: string
  unit_price: string
}

interface PurchaseReview {
  action: 'save' | 'confirm'
  rows: PackagingLine[]
  batch?: PurchaseBatchInput
  etag: string
  error: string
  uncertain: boolean
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const canPurchase = computed(() => auth.user?.is_superuser || auth.hasPermission('procurement.manage_packagingpurchase'))
const groups = ref<PurchaseGroup[]>([])
const sources = ref<PackagingPurchaseSource[]>([])
const options = ref<PurchaseOrderOptions | null>(null)
const inputs = reactive(new Map<string, PackagingLine>())
const sessionId = ref('')
const etag = ref('')
const batchType = ref<PurchaseBatchType>('NORMAL')
const busy = ref(false)
const pendingTaskIds = ref<string[] | null>(null)
const error = ref('')
const review = ref<PurchaseReview | null>(null)
let requestVersion = 0

const sourcesByTask = computed(() => {
  const tasks = new Map<string, PackagingPurchaseSource[]>()
  for (const source of sources.value) {
    const list = tasks.get(source.production_task_id)
    if (list) list.push(source)
    else tasks.set(source.production_task_id, [source])
  }
  return tasks
})
const taskOptions = computed(() => {
  const tasks = new Map([...sourcesByTask.value].map(([id, list]) => [id, list[0]!.task_number]))
  for (const group of groups.value) tasks.set(group.production_task_id, group.production_task_number_snapshot)
  return [...tasks].map(([id, number]) => ({ id, number }))
})
const selectedTasks = computed(() => groups.value.map(group => group.production_task_id))
const groupIds = computed(() => groups.value.map(group => group.id))
const supplierChoices = computed(() => options.value?.suppliers ?? [])
const currencyId = computed(() => options.value?.currencies.find(currency => currency.code === 'CNY')?.id)
const supplierNames = computed(() => new Map(supplierChoices.value.map(supplier => [supplier.id, supplier.supplier_name])))
const savedDrafts = computed(() => groups.value.flatMap(group => (group.batch_page?.draft_orders ?? [])
  .map(order => ({ ...order, taskNumber: group.production_task_number_snapshot }))))
const confirmed = computed(() => groups.value.some(group => group.batches.some(batch =>
  batch.batch_session_id === sessionId.value && batch.status !== 'DRAFT')))

function availableLines(group: PurchaseGroup) {
  const external = new Set(group.progress.external_supply_line_ids ?? [])
  return group.progress.lines.filter(line => !external.has(line.id) && compactDecimal(line.remaining_purchase_quantity, '') !== '0')
}

const tableRows = computed(() => groups.value.flatMap(group => availableLines(group).map(line => inputs.get(line.id)!)))
const blockedGroups = computed(() => groups.value.filter(group =>
  group.combined_into_group_id || group.manual_completed_at || group.progress.status === 'UNKNOWN'))
const blockedGroupIds = computed(() => new Set(blockedGroups.value.map(group => group.id)))
const editableRows = computed(() => tableRows.value.filter(row => !blockedGroupIds.value.has(row.group_id)))
const tableAttributes = computed(() => attributesFor(tableRows.value))
const reviewAttributes = computed(() => attributesFor(review.value?.rows ?? []))
const commonSupplier = computed(() => {
  const supplier = editableRows.value[0]?.supplier_id
  return supplier && editableRows.value.every(row => row.supplier_id === supplier) ? supplier : null
})
const commonDelivery = computed(() => {
  const date = editableRows.value[0]?.delivery_date
  return date && editableRows.value.every(row => row.delivery_date === date) ? date : ''
})
const canEdit = computed(() => !!etag.value && !busy.value && !confirmed.value)
const lockedTasks = computed(() => new Set(groups.value.filter(group => group.batch_page?.draft_orders?.length)
  .map(group => group.production_task_id)))
const emptyTableText = computed(() => {
  if (groups.value.length) return '暂无待采购包材'
  if (busy.value) return '正在读取包材采购资料…'
  return taskOptions.value.length ? '选择生产任务单后即可填写包材' : '暂无可采购包材的生产任务单'
})

function canEditRow(row: PackagingLine) {
  return canEdit.value && !blockedGroupIds.value.has(row.group_id)
}

function attributesFor(rows: PackagingLine[]) {
  return materialAttributeTable(rows.map(row => row.source.source_snapshot))
}

function positive(value: string) {
  return (decimalParts(value)?.digits ?? 0n) > 0n
}

const readyRows = computed(() => editableRows.value.filter(row =>
  positive(row.actual_purchase_quantity) && positive(row.unit_price)))
const completeLineCount = computed(() => readyRows.value.filter(row => row.supplier_id && row.delivery_date).length)
const supplierCount = computed(() => new Set(readyRows.value.flatMap(row => row.supplier_id ? [row.supplier_id] : [])).size)
const totalAmount = computed(() => {
  const amounts = [
    ...readyRows.value.map(row => scaledProduct(row.actual_purchase_quantity, row.unit_price)),
    ...savedDrafts.value.map(order => scaledProduct('1', order.total_amount ?? '')),
  ]
  if (!amounts.length || amounts.includes(null)) return '待计算'
  return '¥ ' + formatScaled(amounts.reduce<bigint>((total, amount) => total + (amount ?? 0n), 0n))
})
const draftSuppliers = computed(() => {
  const ids = new Set(readyRows.value.map(row => row.supplier_id))
  return supplierChoices.value.filter(supplier => ids.has(supplier.id))
})
function queryIds() {
  return [...new Set([route.query.group_ids].flat().filter((value): value is string => typeof value === 'string'))]
}

function errorMessage(cause: unknown, fallback: string) {
  const result = (cause as { response?: { data?: { error?: { message?: string }; detail?: string } } })?.response?.data
  return result?.error?.message || result?.detail || fallback
}

function mergePage(page: { groups: PurchaseGroup[]; etag: string }, submitted: string[] = []) {
  for (const group of page.groups) {
    for (const source of availableLines(group)) {
      const previous = inputs.get(source.id)
      if (previous && !submitted.includes(source.id)) {
        previous.source = source
      } else {
        const snapshot = source.source_snapshot
        inputs.set(source.id, {
          purchase_group_line_id: source.id, group_id: group.id, task_number: group.production_task_number_snapshot,
          source, material_name: snapshot.part_name_snapshot || snapshot.material_snapshot || snapshot.raw_material_snapshot,
          supplier_id: previous?.supplier_id ?? null, delivery_date: previous?.delivery_date ?? '',
          actual_purchase_quantity: compactDecimal(source.remaining_purchase_quantity, ''), unit_price: '',
        })
      }
    }
  }
  groups.value = page.groups
  etag.value = page.etag
}

async function loadPage(preserveInputs = false) {
  if (!canPurchase.value) return
  const version = ++requestVersion
  pendingTaskIds.value = null
  const requestedGroups = queryIds()
  const existingSession = typeof route.query.batch_session_id === 'string' ? route.query.batch_session_id : ''
  const fromNotice = typeof route.query.production_task_id === 'string' ? route.query.production_task_id : ''
  sessionId.value = existingSession || createClientUuid()
  if (!preserveInputs) {
    groups.value = []
    inputs.clear()
    etag.value = ''
    batchType.value = 'NORMAL'
    review.value = null
  }
  error.value = ''
  busy.value = true
  try {
    const [nextSources, nextOptions, page] = await Promise.all([
      fetchPackagingPurchaseSources(),
      fetchPackagingPurchaseOptions(),
      requestedGroups.length || (route.name === 'packaging-purchase-batch' && existingSession)
        ? fetchPackagingPurchasePage(requestedGroups, sessionId.value) : null,
    ])
    if (version !== requestVersion) return
    sources.value = nextSources
    options.value = nextOptions
    if (page) {
      mergePage(page)
      if (!preserveInputs) {
        const draft = page.groups.flatMap(group => group.batches).find(batch =>
          batch.batch_session_id === sessionId.value && batch.status === 'DRAFT')
        if (draft) batchType.value = draft.batch_type
      }
    }
    if (fromNotice && !page && sourcesByTask.value.has(fromNotice)) {
      busy.value = false
      await changeTasks([fromNotice])
    }
  } catch (cause) {
    if (version === requestVersion) error.value = errorMessage(cause, '包材采购明细读取失败。')
  } finally {
    if (version === requestVersion) busy.value = false
  }
}

async function changeTasks(next: string[]) {
  if (busy.value || confirmed.value) return
  if ([...lockedTasks.value].some(id => !next.includes(id))) {
    ElMessage.warning('已保存供应商草稿的任务需保留在本批。')
    return
  }
  const keptGroupIds = groups.value.filter(group => next.includes(group.production_task_id)).map(group => group.id)
  const sourcesToPrepare = next.filter(id => !selectedTasks.value.includes(id))
    .flatMap(id => sourcesByTask.value.get(id) ?? [])
  const version = ++requestVersion
  error.value = ''
  busy.value = true
  pendingTaskIds.value = next
  try {
    let page = { groups: [] as PurchaseGroup[], etag: '' }
    if (sourcesToPrepare.length) {
      page = await preparePackagingPurchasePage(sourcesToPrepare, keptGroupIds, sessionId.value)
    } else if (keptGroupIds.length) {
      page = await fetchPackagingPurchasePage(keptGroupIds, sessionId.value)
    }
    if (version !== requestVersion) return
    mergePage(page)
    await router.replace({
      name: page.groups.length ? route.name : 'packaging-purchase-create',
      query: page.groups.length ? { group_ids: groupIds.value, batch_session_id: sessionId.value } : {},
    })
  } catch (cause) {
    if (version === requestVersion) error.value = errorMessage(cause, '加载所选任务的包材明细失败。')
  } finally {
    if (version === requestVersion) {
      pendingTaskIds.value = null
      busy.value = false
    }
  }
}

watch(() => route.fullPath, () => {
  if (route.name !== 'packaging-purchase-create' && route.name !== 'packaging-purchase-batch') return
  const alreadyDisplayed = !!sessionId.value && route.query.batch_session_id === sessionId.value
    && queryIds().join(',') === groupIds.value.join(',')
  if (!alreadyDisplayed) void loadPage()
}, { immediate: true })

function bulkSupplier(supplierId: string | null) {
  for (const row of editableRows.value) row.supplier_id = supplierId
}

function bulkDelivery(deliveryDate: string | null) {
  for (const row of editableRows.value) row.delivery_date = deliveryDate ?? ''
}

function amountText(row: PackagingLine) {
  const amount = scaledProduct(row.actual_purchase_quantity, row.unit_price)
  return amount === null ? '—' : formatScaled(amount)
}

function openReview(action: 'save' | 'confirm', supplierId?: string) {
  if (!canEdit.value) return
  const rows = supplierId ? readyRows.value.filter(row => row.supplier_id === supplierId) : readyRows.value
  const incomplete = rows.find(row => !row.supplier_id || !row.delivery_date)
  if (incomplete) {
    error.value = '任务 ' + incomplete.task_number
      + ' 第 ' + incomplete.source.line_number + ' 行需要填写供应商和采购交期。'
    return
  }
  if (rows.length && !currencyId.value) {
    error.value = '系统未找到人民币（CNY）采购币种。'
    return
  }
  error.value = ''
  review.value = {
    action, rows, etag: etag.value, error: '', uncertain: false,
    ...(rows.length ? { batch: {
      request_id: createClientUuid(), currency_id: currencyId.value!, batch_type: batchType.value,
      lines: rows.map(row => ({
        purchase_group_line_id: row.purchase_group_line_id,
        supplier_id: row.supplier_id,
        delivery_date: row.delivery_date,
        actual_purchase_quantity: row.actual_purchase_quantity.trim(),
        unit_price: row.unit_price.trim(),
      })),
    } } : {}),
  }
}

function showSupplierSheets() {
  void router.push({ name: 'supplier-purchase-sheets', query: { purchase_scope: 'PACKAGING', batch_session_id: sessionId.value } })
}

async function submitReview() {
  const submission = review.value
  if (!submission || busy.value) return
  const version = requestVersion
  busy.value = true
  submission.error = ''
  try {
    const page = await writePackagingPurchasePage(submission.action, groupIds.value, sessionId.value, submission.etag, submission.batch)
    if (review.value !== submission) return
    mergePage(page, submission.rows.map(row => row.purchase_group_line_id))
    review.value = null
    if (submission.action === 'confirm') {
      ElMessage.success('本批包材采购已确认。')
      showSupplierSheets()
    } else {
      ElMessage.success('供应商草稿已保存。')
    }
  } catch (cause) {
    if (review.value !== submission) return
    const status = (cause as { response?: { status?: number } })?.response?.status
    submission.uncertain = !status || status >= 500
    submission.error = submission.uncertain
      ? '提交结果尚未确认。请重试本次提交。'
      : errorMessage(cause, '包材采购提交失败。')
    if (status === 412) error.value = '采购需求已变化。请关闭核对窗口后刷新。'
  } finally {
    if (version === requestVersion) busy.value = false
  }
}
</script>

<template>
  <section v-if="canPurchase" class="purchase-form-page erp-glass-form" data-testid="packaging-purchase-form">
    <header class="page-heading">
      <div><h1>填写包材采购</h1></div>
      <div class="page-actions">
        <ElButton :disabled="busy" @click="router.push({ name: 'packaging-purchases' })">
          <img class="purchase-icon" :src="backIcon" alt="" />返回列表
        </ElButton>
        <ElButton :disabled="busy" @click="loadPage(true)"><img class="purchase-icon" :src="refreshIcon" alt="" />刷新</ElButton>
      </div>
    </header>

    <div class="batch-type-field">
      <span>批次类型</span>
      <ElRadioGroup v-model="batchType" aria-label="采购批次类型" :disabled="!canEdit">
        <ElRadio value="NORMAL">正常采购</ElRadio>
        <ElRadio value="SUPPLEMENT">补料</ElRadio>
      </ElRadioGroup>
    </div>
    <ElAlert v-if="error" type="error" :title="error" :closable="false" show-icon />
    <ElAlert v-for="group in blockedGroups" :key="group.id" type="warning" :closable="false" show-icon
      :title="group.production_task_number_snapshot + ' · ' + (group.combined_into_group_id
        ? '采购需求已合并' : group.manual_completed_at ? '包材采购已完成' : '包材采购来源待核对')">
      <RouterLink v-if="group.combined_into_group_id"
        :to="{ name: 'packaging-purchase-detail', params: { id: group.combined_into_group_id } }">查看合并后的需求</RouterLink>
    </ElAlert>

    <section class="detail-card">
      <header>
        <div class="detail-title-context"><h2>采购明细</h2><span>{{ tableRows.length }} 项</span></div>
        <div class="detail-header-actions">
          <label class="bulk-field bulk-field--task">
            <span>生产任务单</span>
            <ElSelect :model-value="pendingTaskIds ?? selectedTasks" multiple filterable collapse-tags :max-collapse-tags="2" collapse-tags-tooltip
              placeholder="选择生产任务单" aria-label="生产任务单" data-testid="packaging-task-select" :loading="busy"
              :disabled="busy || confirmed" @change="changeTasks">
              <ElOption v-for="task in taskOptions" :key="task.id" :label="task.number" :value="task.id"
                :disabled="lockedTasks.has(task.id)" />
            </ElSelect>
          </label>
          <label class="bulk-field bulk-field--supplier">
            <span>统一供应商</span>
            <ElSelect :model-value="commonSupplier" filterable clearable :value-on-clear="null" placeholder="选择包材供应商"
              aria-label="统一供应商" :disabled="!canEdit || !editableRows.length" @change="bulkSupplier">
              <ElOption v-for="supplier in supplierChoices" :key="supplier.id" :label="supplier.supplier_name" :value="supplier.id" />
            </ElSelect>
          </label>
          <label class="bulk-field bulk-field--date">
            <span>统一交期</span>
            <ElDatePicker :model-value="commonDelivery" type="date" value-format="YYYY-MM-DD" aria-label="统一交期"
              placeholder="选择后同步全部" :disabled="!canEdit || !editableRows.length" @update:model-value="bulkDelivery" />
          </label>
        </div>
      </header>
      <ElTable :data="tableRows" row-key="purchase_group_line_id" height="100%" class="erp-table-editor purchase-lines"
        data-testid="packaging-material-table">
        <ElTableColumn label="生产任务单号" width="124" fixed="left" show-overflow-tooltip>
          <template #default="{ row }"><strong class="primary-cell">{{ row.task_number }}</strong></template>
        </ElTableColumn>
        <ElTableColumn prop="source.source_snapshot.product_name_snapshot" label="产品" width="128" show-overflow-tooltip />
        <ElTableColumn prop="source.source_snapshot.bom_number_snapshot" label="BOM" width="123" show-overflow-tooltip />
        <ElTableColumn label="品名" width="136" show-overflow-tooltip>
          <template #default="{ row }"><strong class="primary-cell">{{ row.material_name }}</strong></template>
        </ElTableColumn>
        <ElTableColumn v-for="column in tableAttributes.columns" :key="column" :label="column"
          :width="Math.max(106, column.length * 11 + 34)" show-overflow-tooltip>
          <template #default="{ $index }">{{ tableAttributes.cells[$index]?.get(column) || '—' }}</template>
        </ElTableColumn>
        <ElTableColumn prop="source.source_unit_text" label="单位" width="70" />
        <ElTableColumn label="剩余采购量" width="110" align="right" header-align="left">
          <template #default="{ row }">
            <PurchaseQuantitySources v-if="row.source.source_snapshot.source_contributions?.length > 1"
              :contributions="row.source.source_snapshot.source_contributions">
              {{ compactDecimal(row.source.remaining_purchase_quantity, '待核对') }}
            </PurchaseQuantitySources>
            <span v-else>{{ compactDecimal(row.source.remaining_purchase_quantity, '待核对') }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="供应商" width="178">
          <template #default="{ row }">
            <ElSelect v-model="row.supplier_id" class="line-field" filterable clearable :value-on-clear="null" aria-label="供应商"
              placeholder="选择包材供应商" :disabled="!canEditRow(row)">
              <ElOption v-for="supplier in supplierChoices" :key="supplier.id" :label="supplier.supplier_name" :value="supplier.id" />
            </ElSelect>
          </template>
        </ElTableColumn>
        <ElTableColumn label="采购交期" width="148">
          <template #default="{ row }">
            <ElDatePicker v-model="row.delivery_date" class="line-field" type="date" value-format="YYYY-MM-DD" aria-label="采购交期"
              placeholder="选择交期" :disabled="!canEditRow(row)" />
          </template>
        </ElTableColumn>
        <ElTableColumn label="实际采购数量" width="124">
          <template #default="{ row }">
            <ElInput v-model="row.actual_purchase_quantity" class="line-field" inputmode="decimal" maxlength="24"
              aria-label="实际采购数量" placeholder="本批采购数量" :disabled="!canEditRow(row)" />
          </template>
        </ElTableColumn>
        <ElTableColumn label="采购单价" width="112">
          <template #default="{ row }">
            <ElInput v-model="row.unit_price" class="line-field line-field--price" inputmode="decimal" maxlength="24"
              aria-label="采购单价" placeholder="请输入" :disabled="!canEditRow(row)" />
          </template>
        </ElTableColumn>
        <ElTableColumn label="采购金额（元）" min-width="124">
          <template #default="{ row }"><span class="amount-preview">{{ amountText(row) }}</span></template>
        </ElTableColumn>
        <template #empty><div class="detail-empty"><strong>{{ emptyTableText }}</strong></div></template>
      </ElTable>
      <footer>
        <span>已完整填写 {{ completeLineCount }} 项</span>
        <span v-if="savedDrafts.length">已保存 {{ savedDrafts.length }} 张供应商草稿</span>
      </footer>
    </section>

    <section class="summary-card">
      <div class="summary-counts">
        <span>采购明细 <strong>{{ readyRows.length }}</strong> 项</span>
        <span>·</span>
        <span>已选供应商 <strong>{{ supplierCount }}</strong> 家</span>
      </div>
      <div class="summary-actions">
        <div class="summary-total"><span>采购总金额</span><strong>{{ totalAmount }}</strong></div>
        <ElButton v-if="confirmed" type="primary" @click="showSupplierSheets">查看本批供应商采购表</ElButton>
        <template v-else>
          <ElDropdown trigger="click" placement="top-end" :disabled="!canEdit || !draftSuppliers.length" @command="openReview('save', $event)">
            <ElButton plain type="primary" :disabled="!canEdit || !draftSuppliers.length">
              按供应商保存草稿<ElIcon><ArrowDown /></ElIcon>
            </ElButton>
            <template #dropdown>
              <ElDropdownMenu>
                <ElDropdownItem v-for="supplier in draftSuppliers" :key="supplier.id" :command="supplier.id">{{ supplier.supplier_name }}</ElDropdownItem>
              </ElDropdownMenu>
            </template>
          </ElDropdown>
          <ElButton type="primary" :disabled="!canEdit || (!savedDrafts.length && !readyRows.length)" @click="openReview('confirm')">
            统一确认采购<img class="purchase-icon" :src="rightIcon" alt="" />
          </ElButton>
        </template>
      </div>
    </section>

    <AppWindowDialog v-if="review" :model-value="true" :title="review.action === 'save' ? '保存供应商采购草稿' : '统一确认包材采购'"
      :width="1480" :min-width="288" :auto-max-height-ratio="0.9" :minimizable="false" :show-close="!busy && !review.uncertain"
      :close-on-click-modal="false" :close-on-press-escape="!busy && !review.uncertain"
      @update:model-value="value => { if (!value && !busy && !review?.uncertain) review = null }">
      <div v-if="review.rows.length" class="packaging-form__review-frame">
        <table class="packaging-form__review">
          <thead><tr><th scope="col">生产任务单号</th><th scope="col">品名</th>
            <th v-for="column in reviewAttributes.columns" :key="column" scope="col">{{ column }}</th>
            <th scope="col">单位</th><th scope="col">供应商</th><th scope="col">采购数量</th>
            <th scope="col">采购单价</th><th scope="col">采购交期</th>
          </tr></thead>
          <tbody>
            <tr v-for="(row, index) in review.rows" :key="row.purchase_group_line_id">
              <td class="packaging-form__review-value">{{ row.task_number }}</td><td>{{ row.material_name }}</td>
              <td v-for="column in reviewAttributes.columns" :key="column">{{ reviewAttributes.cells[index]?.get(column) || '—' }}</td>
              <td class="packaging-form__review-value">{{ row.source.source_unit_text }}</td><td>{{ supplierNames.get(row.supplier_id!) }}</td>
              <td class="packaging-form__review-value">{{ row.actual_purchase_quantity }}</td>
              <td class="packaging-form__review-value">{{ row.unit_price }}</td>
              <td class="packaging-form__review-value">{{ row.delivery_date }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <ul v-if="review.action === 'confirm' && savedDrafts.length" class="packaging-form__drafts">
        <li v-for="order in savedDrafts" :key="order.id">{{ order.taskNumber }} · {{ order.order_number }} · {{ order.suppliers.join('、') }} · {{ order.line_count }} 项</li>
      </ul>
      <p v-if="review.error" class="packaging-form__error" role="alert">{{ review.error }}</p>
      <template #footer>
        <ElButton :disabled="busy || review.uncertain" @click="review = null">返回修改</ElButton>
        <ElButton type="primary" :loading="busy" @click="submitReview">{{ review.action === 'save' ? '保存草稿' : '确认采购' }}</ElButton>
      </template>
    </AppWindowDialog>
  </section>
  <ElEmpty v-else description="当前账号没有办理包材采购权限" />
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as crm;
@use '@/styles/theme/detail' as detail;

.purchase-form-page {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  padding: 0;
  color: crm.$crm-text-primary;
  background: transparent;
  font: 14px/1.5 crm.$crm-font-body;
}
.purchase-form-page :deep(.el-button > span) { display: inline-flex; align-items: center; gap: 10px; }
.purchase-form-page > :deep(.el-alert) { flex: none; margin-bottom: 10px; }
.purchase-icon { width: 16px; height: 16px; flex: none; }
.page-heading {
  flex: none; min-height: 50px; display: flex; flex-wrap: wrap; align-items: center;
  justify-content: space-between; gap: 14px; margin-bottom: 14px;
}
.page-heading h1 { margin: 0; font: 700 38px/50px crm.$crm-font-display; letter-spacing: -1px; }
.page-actions { display: flex; gap: 18px; }
.page-actions :deep(.el-button) { width: 128px; margin: 0; }
.batch-type-field { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; margin-bottom: 14px; font-size: 13px; }

.detail-card, .summary-card { @include detail.surface; }
.detail-card { flex: 1; min-height: 220px; display: flex; flex-direction: column; overflow: hidden; margin-bottom: 14px; }
.detail-card > header {
  display: flex; flex: none; min-height: 52px; flex-wrap: wrap; align-items: center;
  justify-content: space-between; padding: 8px 12px; gap: 10px;
}
.detail-title-context, .detail-header-actions { display: flex; align-items: center; gap: 12px; }
.detail-title-context h2 { margin: 0; font-size: 20px; line-height: 28px; white-space: nowrap; }
.detail-title-context > span { color: crm.$crm-text-secondary; font-size: 13px; }
.detail-header-actions { margin-left: auto; flex-wrap: wrap; gap: 10px; }
.bulk-field { display: flex; align-items: center; gap: 8px; white-space: nowrap; font-size: 13px; }
.bulk-field--task :deep(.el-select) { width: min(330px, 66vw); }
.bulk-field--supplier :deep(.el-select) { width: 218px; }
.bulk-field--date :deep(.el-date-editor) { width: 220px; }
.detail-card > footer {
  flex: 0 0 48px; display: flex; align-items: center; justify-content: space-between;
  gap: 20px; padding: 0 18px; color: crm.$crm-text-secondary; font-size: 13px; border-top: 1px solid crm.$crm-border-subtle;
}
.detail-empty { min-height: 200px; display: grid; place-content: center; padding: 24px; }
.detail-empty strong { font-size: 18px; color: crm.$crm-text-primary; }

.purchase-lines { flex: 1 1 0; width: 100%; min-height: 0; }
.purchase-form-page .purchase-lines :deep(.el-table__header th.el-table__cell) { height: 40px !important; }
.purchase-form-page .purchase-lines :deep(.el-table__header th:not(:last-child)),
.purchase-form-page .purchase-lines :deep(.el-table__body td:not(:last-child)) { border-right: 1px solid var(--erp-table-grid); }
.purchase-form-page .purchase-lines :deep(.el-table__body td.el-table__cell) { padding: 0 !important; }
.purchase-lines :deep(.el-table__inner-wrapper::before), .purchase-lines :deep(.el-table__inner-wrapper::after) { display: none; }
.purchase-lines :deep(.el-scrollbar__wrap) { overscroll-behavior-y: contain; }
.purchase-lines :deep(.el-table__body tr:last-child td) { border-bottom: 0; }
.purchase-lines :deep(th:first-child .cell), .purchase-lines :deep(td:first-child .cell) { padding: 0 8px !important; }
.purchase-lines :deep(th .cell) { white-space: nowrap; }
.purchase-lines :deep(.line-field) { display: flex; align-items: center; width: 100%; min-height: 39px; }
.line-field :deep(.el-input__wrapper) { padding: 1px 13px; font-size: 12px; }
.line-field--price :deep(.el-input__wrapper) { padding: 1px 8px; }
.primary-cell { font-size: 13px; font-weight: 500; }
.amount-preview { font-size: 14px; font-variant-numeric: tabular-nums; }

.summary-card { flex: none; min-height: 72px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 16px; }
.summary-counts, .summary-actions { display: flex; align-items: center; gap: 14px; }
.summary-counts { font-size: 16px; font-weight: 500; white-space: nowrap; }
.summary-counts strong { margin: 0 6px; color: crm.$crm-primary; font-weight: 500; }
.summary-actions { flex-wrap: wrap; }
.summary-total { display: flex; align-items: center; gap: 18px; padding-left: 40px; border-left: 1px solid crm.$crm-border-default; white-space: nowrap; }
.summary-total strong { min-width: 170px; color: crm.$crm-primary; font-size: 28px; }
.packaging-form__error { margin: 0; color: var(--el-color-danger); }
.packaging-form__review-frame { min-width: 940px; border: 1px solid crm.$crm-border-subtle; border-radius: 6px; }
.packaging-form__review { width: 100%; border-spacing: 0; font-size: 14px; line-height: 1.5; }
.packaging-form__review :is(th, td) { padding: 9px 12px; text-align: left; border-bottom: 1px solid crm.$crm-border-subtle; }
.packaging-form__review th { position: sticky; top: 0; z-index: 1; background: crm.$crm-color-subtle; white-space: nowrap; }
.packaging-form__review td { overflow-wrap: anywhere; }
.packaging-form__review tr:last-child td { border-bottom: 0; }
.packaging-form__review-value { white-space: nowrap; font-variant-numeric: tabular-nums; }
.packaging-form__drafts { padding-left: 20px; }

@media (max-width: 980px) {
  .detail-header-actions { margin-left: 0; }
  .summary-total { padding-left: 0; border-left: 0; }
}
</style>
