<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { MoreFilled } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { fetchPurchaseReceiptRecord, fetchPurchaseReceiptRecords } from '@/api/inventory'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import ReceiptRecordMaterialTables from '@/components/inventory/ReceiptRecordMaterialTables.vue'
import PurchaseInboundHistory from '@/components/procurement/PurchaseInboundHistory.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { formatInboundProductField, formatTime } from '@/views/procurement/purchaseOrderDetailDisplay'
import type { PurchaseReceiptRecord, PurchaseReceiptRecordsPage, PurchaseReceiptStatus } from '@/types/inventory'

const router = useRouter()
const states: Record<PurchaseReceiptStatus, { label: string; tag: string }> = {
  PENDING_QUALITY: { label: '待检', tag: 'warning' },
  CONFIRMED: { label: '已检验', tag: 'success' },
  RETURNED: { label: '全部退货', tag: 'danger' },
}
const result = ref<PurchaseReceiptRecordsPage>({ data: [], total: 0 })
const loading = ref(false)
const loadError = ref('')
const keyword = ref('')
const appliedKeyword = ref('')
const quality = ref<'PENDING' | 'CHECKED'>('PENDING')
const page = ref(1)
let requestId = 0

const detailOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const detail = ref<Awaited<ReturnType<typeof fetchPurchaseReceiptRecord>>>()
const detailRecord = ref<PurchaseReceiptRecord>()
const receiptReference = computed(() => {
  if (detail.value?.source !== 'PURCHASE' || !detailRecord.value) return
  const sampleNumber = detail.value.data.sample_number
  return {
    label: sampleNumber ? '打样单号' : '生产任务单号',
    number: sampleNumber || detailRecord.value.production_task_number,
    purchaseOrderNumber: detailRecord.value.purchase_order_number,
  }
})
let detailRequestId = 0

async function load() {
  const current = ++requestId
  loading.value = true
  loadError.value = ''
  try {
    const response = await fetchPurchaseReceiptRecords({ quality: quality.value, q: appliedKeyword.value, page: page.value })
    if (current === requestId) result.value = response
  } catch {
    if (current !== requestId) return
    result.value = { data: [], total: 0 }
    loadError.value = '品质检验记录加载失败，请重试。'
  } finally {
    if (current === requestId) loading.value = false
  }
}
function search() {
  appliedKeyword.value = keyword.value.trim()
  page.value = 1
  void load()
}
function reset() {
  keyword.value = ''
  search()
}
function changeTab(value: 'PENDING' | 'CHECKED') {
  quality.value = value
  page.value = 1
  void load()
}
async function openDetail(row: PurchaseReceiptRecord) {
  const current = ++detailRequestId
  detailRecord.value = row
  detail.value = undefined
  detailError.value = ''
  detailOpen.value = true
  detailLoading.value = true
  try {
    const record = await fetchPurchaseReceiptRecord(row.id, row.source)
    if (current === detailRequestId) detail.value = record
  } catch {
    if (current === detailRequestId) detailError.value = '入库记录详情加载失败，请关闭后重试。'
  } finally {
    if (current === detailRequestId) detailLoading.value = false
  }
}
function confirmQuality(row: PurchaseReceiptRecord) {
  void router.push({ name: 'material-quality-confirmation', query: { receipt: row.id } })
}
onMounted(load)
</script>

<template>
  <section class="erp-glass-list" data-testid="purchase-receipt-records-page">
    <section v-glass-spotlight class="erp-list-filter">
      <header class="erp-list-heading"><h1>品质检验</h1></header>
      <form class="erp-list-filters" @submit.prevent="search">
        <ElInput v-model="keyword" class="receipt-search" aria-label="搜索检验批次" placeholder="单号 / 品名 / 供应商" title="支持生产任务单号、入库单号、采购单号、品名和供应商" maxlength="200" clearable @clear="search" />
        <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="reset">重置</ElButton><ElButton class="erp-button-motion" type="primary" native-type="submit">应用筛选</ElButton></div>
      </form>
    </section>

    <section class="erp-list-data" aria-label="品质检验记录">
      <nav class="erp-list-toolbar erp-list-tabs" aria-label="品质检验状态">
        <button type="button" :class="{ active: quality === 'PENDING' }" :aria-pressed="quality === 'PENDING'" @click="changeTab('PENDING')">待检</button>
        <button type="button" :class="{ active: quality === 'CHECKED' }" :aria-pressed="quality === 'CHECKED'" @click="changeTab('CHECKED')">已检验</button>
      </nav>
      <ElAlert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon><ElButton link @click="load()">重新加载</ElButton></ElAlert>
      <div class="erp-list-table-frame">
        <ElTable v-loading="loading" :data="result.data" height="100%" row-key="id" :empty-text="loading ? '正在加载…' : quality === 'PENDING' ? '暂无待检批次' : '暂无已检验批次'">
          <ElTableColumn label="生产任务单号" min-width="148" show-overflow-tooltip><template #default="{ row }">{{ row.production_task_number || '—' }}</template></ElTableColumn>
          <ElTableColumn prop="inbound_number" label="入库单号" min-width="166" show-overflow-tooltip />
          <ElTableColumn label="采购单号" min-width="164" show-overflow-tooltip><template #default="{ row }">{{ row.purchase_order_number || '—' }}</template></ElTableColumn>
          <ElTableColumn prop="material_section_display" label="材料分区" min-width="170" show-overflow-tooltip />
          <ElTableColumn label="品名" min-width="160" show-overflow-tooltip><template #default="{ row }">{{ formatInboundProductField(row.product_summary, 'product_name') }}</template></ElTableColumn>
          <ElTableColumn label="货号" min-width="108" show-overflow-tooltip><template #default="{ row }">{{ formatInboundProductField(row.product_summary, 'item_number') }}</template></ElTableColumn>
          <ElTableColumn label="供应商" min-width="185" show-overflow-tooltip><template #default="{ row }">{{ row.supplier_names.join('、') || '—' }}</template></ElTableColumn>
          <ElTableColumn label="采购批次" width="98"><template #default="{ row }">{{ row.batch_number == null ? '—' : `第 ${row.batch_number} 批` }}</template></ElTableColumn>
          <ElTableColumn prop="inbound_date" label="登记日期" min-width="114" />
          <ElTableColumn prop="received_by_name" label="登记人" min-width="106" show-overflow-tooltip />
          <ElTableColumn prop="line_count" label="材料项数" width="92" align="right" />
          <ElTableColumn label="状态" width="104"><template #default="{ row }"><span class="erp-list-tag" :class="`erp-list-tag--${states[row.status as PurchaseReceiptStatus].tag}`">{{ states[row.status as PurchaseReceiptStatus].label }}</span></template></ElTableColumn>
          <ElTableColumn v-if="quality === 'CHECKED'" label="检验人" min-width="104" show-overflow-tooltip><template #default="{ row }">{{ row.quality_confirmed_by_name || '—' }}</template></ElTableColumn>
          <ElTableColumn v-if="quality === 'CHECKED'" label="检验时间" width="156"><template #default="{ row }">{{ formatTime(row.quality_confirmed_at) }}</template></ElTableColumn>
          <ElTableColumn label="操作" width="72" fixed="right" align="center">
            <template #default="{ row }">
              <ElDropdown :persistent="false" trigger="click" placement="bottom-end">
                <ElButton link class="row-more-button" :icon="MoreFilled" :aria-label="`${row.inbound_number}的更多操作`" />
                <template #dropdown><ElDropdownMenu>
                  <ElDropdownItem @click="openDetail(row)">查看详情</ElDropdownItem>
                  <ElDropdownItem v-if="quality === 'PENDING' && row.can_quality_confirm" @click="confirmQuality(row)">品质确认</ElDropdownItem>
                </ElDropdownMenu></template>
              </ElDropdown>
            </template>
          </ElTableColumn>
        </ElTable>
      </div>
      <footer class="erp-list-footer"><span>共 {{ result.total }} 条</span><ElPagination v-model:current-page="page" :page-size="20" :total="result.total" layout="prev, pager, next" @current-change="load()" /></footer>
    </section>

    <AppWindowDialog v-model="detailOpen" title="入库记录详情" width="80vw" :height="600" @closed="detailRequestId++">
      <div v-loading="detailLoading" class="receipt-detail">
        <ElAlert v-if="detailError" :title="detailError" type="error" :closable="false" />
        <template v-if="detail?.source === 'PURCHASE'">
          <PurchaseInboundHistory :purchase-order-id="detail.data.purchase_order_id" :inbounds="[detail.data]" :receipt-reference="receiptReference" embedded expand-single>
            <template #material-details="{ quantity }">
              <ReceiptRecordMaterialTables :receipt="{ ...detail, productionTaskNumber: detailRecord?.production_task_number, formatQuantity: quantity }" />
            </template>
          </PurchaseInboundHistory>
        </template>
      </div>
    </AppWindowDialog>
  </section>
</template>

<style scoped>
.receipt-search { width: min(250px, 100%); }
.row-more-button { width: 36px; height: 32px; margin: 0; color: var(--erp-table-text); }
.receipt-detail { min-height: 120px; }
</style>
