<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { fetchMaterialStockRecords } from '@/api/materialStockRecords'
import { fetchPurchaseReceiptRecord } from '@/api/inventory'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import ReceiptRecordMaterialTables from '@/components/inventory/ReceiptRecordMaterialTables.vue'
import PurchaseInboundHistory from '@/components/procurement/PurchaseInboundHistory.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { compactDecimal } from '@/utils/compactDecimal'
import { workbenchErrorMessage } from '@/utils/workbench'
import type { ReceiptRecordDetail } from '@/types/inventory'
import type { MaterialStockRecord, MaterialStockRecordDirection, MaterialStockRecordSection } from '@/types/materialStockRecords'

const props = defineProps<{ direction: MaterialStockRecordDirection }>()
const sections: { id: MaterialStockRecordSection; name: string }[] = [
  { id: 'TUBE', name: '管材' }, { id: 'FABRIC', name: '布面' }, { id: 'HARDWARE', name: '五金' },
  { id: 'PLASTIC', name: '塑料件' }, { id: 'AUXILIARY', name: '辅料' }, { id: 'PACKAGING', name: '包材' },
]
const outgoing = computed(() => props.direction === 'OUT')
const title = computed(() => outgoing.value ? '材料出库记录' : '材料入库记录')
const showOther = ref(false)
const section = ref<MaterialStockRecordSection>('TUBE')
const visibleSections = computed(() => showOther.value || section.value === 'OTHER'
  ? [...sections, { id: 'OTHER' as const, name: '其他材料' }] : sections)
const task = ref('')
const name = ref('')
const dates = ref<[string, string] | null>(null)
const applied = ref<{ task_number: string; q: string; start_date?: string; end_date?: string }>({ task_number: '', q: '' })
const page = ref(1)
const rows = ref<MaterialStockRecord[]>([])
const total = ref(0)
const loading = ref(false)
const errorMessage = ref('')
let request: AbortController | undefined

async function load() {
  request?.abort()
  const { signal } = request = new AbortController()
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchMaterialStockRecords({ direction: props.direction, section: section.value,
      ...applied.value, page: page.value }, signal)
    if (signal.aborted) return
    rows.value = result.data
    total.value = result.total
    showOther.value = result.show_other
  } catch (error) {
    if (!signal.aborted) {
      rows.value = []
      total.value = 0
      errorMessage.value = workbenchErrorMessage(error, `查询${title.value}`)
    }
  } finally {
    if (!signal.aborted) loading.value = false
  }
}

function search() {
  applied.value = { task_number: task.value.trim(), q: name.value.trim(), start_date: dates.value?.[0], end_date: dates.value?.[1] }
  page.value = 1
  void load()
}

function reset() {
  task.value = ''
  name.value = ''
  dates.value = null
  search()
}

function selectSection(value: MaterialStockRecordSection) {
  if (section.value === value) return
  rows.value = []
  section.value = value
  page.value = 1
  void load()
}

const detail = ref<MaterialStockRecord>()
const detailOpen = ref(false)
const purchaseDocument = ref<ReceiptRecordDetail>()
const detailLoading = ref(false)
const detailError = ref('')
let detailRequest = 0
async function show(row: MaterialStockRecord) {
  const current = ++detailRequest
  detail.value = row
  detailOpen.value = true
  detailError.value = ''
  detailLoading.value = false
  purchaseDocument.value = undefined
  if (row.movement_label !== '采购入库') return
  detailLoading.value = true
  try {
    const record = await fetchPurchaseReceiptRecord(row.origin_id, 'PURCHASE')
    if (current === detailRequest) purchaseDocument.value = record
  } catch (error) {
    if (current === detailRequest) detailError.value = workbenchErrorMessage(error, '读取原采购收货单')
  } finally {
    if (current === detailRequest) detailLoading.value = false
  }
}
watch(() => props.direction, () => { rows.value = []; section.value = 'TUBE'; page.value = 1; void load() }, { immediate: true })
onBeforeUnmount(() => request?.abort())
</script>

<template>
  <section class="erp-glass-list">
    <section v-glass-spotlight class="erp-list-filter">
      <header class="erp-list-heading"><h1>{{ title }}</h1></header>
      <form class="erp-list-filters" @submit.prevent="search">
        <ElInput v-model="task" class="record-filter-text" maxlength="50" clearable placeholder="生产任务单号" aria-label="生产任务单号" @clear="search" />
        <ElInput v-model="name" class="record-filter-text" maxlength="200" clearable placeholder="品名、规格或原单号" aria-label="品名、规格或原单号" @clear="search" />
        <ElDatePicker v-model="dates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" @change="search" />
        <div class="erp-list-filter-actions">
          <ElButton class="erp-button-motion" @click="reset">重置</ElButton>
          <ElButton class="erp-button-motion" type="primary" native-type="submit">查询</ElButton>
        </div>
      </form>
    </section>

    <section class="erp-list-data">
      <nav class="erp-list-toolbar erp-list-tabs" aria-label="材料分区">
        <button v-for="item in visibleSections" :key="item.id" type="button" :class="{ active: section === item.id }"
          :aria-pressed="section === item.id" @click="selectSection(item.id)">{{ item.name }}</button>
      </nav>
      <ElAlert v-if="errorMessage" :title="errorMessage" type="error" :closable="false"><ElButton link @click="load">重试</ElButton></ElAlert>
      <div class="erp-list-table-frame">
        <ElTable v-loading="loading" :data="rows" height="100%" row-key="id" empty-text="暂无符合条件的记录">
          <ElTableColumn prop="task_number" label="生产任务单号" width="148" show-overflow-tooltip />
          <ElTableColumn prop="business_date" :label="outgoing ? '出库日期' : '入库日期'" width="112" />
          <ElTableColumn prop="movement_label" label="类型" width="130" show-overflow-tooltip />
          <ElTableColumn prop="item_name" label="品名" min-width="137" show-overflow-tooltip />
          <ElTableColumn prop="specification" label="规格／箱规" min-width="141" show-overflow-tooltip />
          <ElTableColumn prop="color" label="颜色" min-width="85" show-overflow-tooltip />
          <ElTableColumn :label="outgoing ? '实发数量' : '实收数量'" width="115" align="right">
            <template #default="{ row }">{{ compactDecimal(row.actual_quantity) }}</template>
          </ElTableColumn>
          <ElTableColumn prop="stock_unit" label="单位" width="66" />
          <ElTableColumn prop="warehouse_name" label="仓库" min-width="116" show-overflow-tooltip />
          <ElTableColumn prop="zone_name" label="库区" min-width="104" show-overflow-tooltip />
          <ElTableColumn prop="counterparty" label="供应商／加工点" min-width="130" show-overflow-tooltip />
          <ElTableColumn v-if="outgoing" prop="recipient_name" label="领用人" min-width="92" show-overflow-tooltip />
          <ElTableColumn prop="actor_name" :label="outgoing ? '发料／经手人' : '收料人'" min-width="116" show-overflow-tooltip />
          <ElTableColumn label="原单号" width="163" fixed="right">
            <template #default="{ row }"><ElButton link type="primary" @click="show(row)">{{ row.voucher_number || '查看明细' }}</ElButton></template>
          </ElTableColumn>
        </ElTable>
      </div>
      <footer class="erp-list-footer">
        <span>共 {{ total }} 条</span>
        <ElPagination v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load" />
      </footer>
    </section>
    <AppWindowDialog v-model="detailOpen" title="原单明细" width="80vw" :height="600" @closed="detailRequest++">
      <div v-if="detail" v-loading="detailLoading">
        <dl class="stock-record-facts">
          <div v-for="field in [['原单号', detail.voucher_number], ['原分区', detail.origin_section_display],
            ['类型', detail.movement_label], ['业务日期', detail.business_date], ['生产任务单号', detail.task_number],
            ['品名', detail.item_name], ['规格／箱规', detail.specification], ['颜色', detail.color],
            ['本次数量', `${compactDecimal(detail.actual_quantity)} ${detail.stock_unit}`],
            ['仓库／库区', `${detail.warehouse_name} / ${detail.zone_name}`], ['经手人', detail.actor_name],
            ['领用人', detail.recipient_name], ['供应商／加工点', detail.counterparty], ['备注', detail.note]]"
            v-show="field[1]" :key="field[0]"><dt>{{ field[0] }}</dt><dd>{{ field[1] }}</dd></div>
        </dl>
        <ElAlert v-if="detailError" :title="detailError" type="error" :closable="false" />
        <PurchaseInboundHistory v-if="purchaseDocument?.source === 'PURCHASE'" :purchase-order-id="purchaseDocument.data.purchase_order_id"
          :inbounds="[purchaseDocument.data]" embedded expand-single>
          <template #material-details="{ quantity }">
            <ReceiptRecordMaterialTables :receipt="{ ...purchaseDocument, productionTaskNumber: detail.task_number, formatQuantity: quantity }" />
          </template>
        </PurchaseInboundHistory>
      </div>
    </AppWindowDialog>
  </section>
</template>

<style scoped>
.record-filter-text { width: min(100%, 220px); }
.stock-record-facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px 20px; margin: 0 0 16px; }
.stock-record-facts dt { color: var(--erp-color-text-secondary); }
.stock-record-facts dd { margin: 4px 0 0; overflow-wrap: anywhere; }
</style>
