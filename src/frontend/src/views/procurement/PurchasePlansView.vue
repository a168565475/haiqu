<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { fetchPurchasePlanDetail, fetchPurchasePlans } from '@/api/purchasePlans'
import DeliveryStatusTag from '@/components/common/DeliveryStatusTag.vue'
import DeliveryReminderFilters from '@/components/common/DeliveryReminderFilters.vue'
import PurchasePlanBatchDetails from '@/components/procurement/PurchasePlanBatchDetails.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import type { DeliveryFollowUp, ReminderFilters } from '@/types/deliveryReminders'
import type { PurchasePlanAmount, PurchasePlanCategory, PurchasePlanDetail, PurchasePlanRow } from '@/types/purchasePlans'
import { compactDecimal } from '@/utils/compactDecimal'
import { workbenchErrorMessage } from '@/utils/workbench'

const route = useRoute()
const tabs: { id: PurchasePlanCategory; label: string }[] = [
  { id: 'TUBE', label: '管材采购计划表' },
  { id: 'FABRIC', label: '布面采购计划表' },
]
const category = ref<PurchasePlanCategory>(route.query.category === 'FABRIC' ? 'FABRIC' : 'TUBE')
const taskInput = ref(typeof route.query.task_number === 'string' ? route.query.task_number : '')
const keywordInput = ref('')
const followUp = ref<DeliveryFollowUp>('ALL')
const owner = ref('')
const filters = ref<ReminderFilters & { task_number: string; q: string }>({
  task_number: taskInput.value, q: '', follow_up: followUp.value, owner: '',
})
const page = ref(1)
const pageSize = 20
const total = ref(0)
const rows = ref<PurchasePlanRow[]>([])
const loading = ref(false)
const errorMessage = ref('')
let listRequest: AbortController | undefined

const expanded = ref<string | null>(null)
const expandedKeys = computed(() => expanded.value ? [expanded.value] : [])
const detail = ref<PurchasePlanDetail | null>(null)
const detailError = ref('')
let detailRequest: AbortController | undefined

function formatAmount(value: PurchasePlanAmount | null) {
  return value ? `${compactDecimal(value.quantity)} ${value.unit}` : ''
}

function closeDetail() {
  detailRequest?.abort()
  expanded.value = null
  detail.value = null
  detailError.value = ''
}

async function load() {
  closeDetail()
  listRequest?.abort()
  const { signal } = listRequest = new AbortController()
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await fetchPurchasePlans({ category: category.value, ...filters.value, page: page.value, page_size: pageSize }, signal)
    if (signal.aborted) return
    rows.value = result.data
    total.value = result.total
  } catch (error) {
    if (signal.aborted) return
    rows.value = []
    total.value = 0
    errorMessage.value = workbenchErrorMessage(error, '读取采购计划表')
  } finally {
    if (!signal.aborted) loading.value = false
  }
}

function search() {
  filters.value = {
    task_number: taskInput.value.trim(), q: keywordInput.value.trim(), follow_up: followUp.value, owner: owner.value.trim(),
  }
  page.value = 1
  void load()
}

function reset() {
  taskInput.value = ''
  keywordInput.value = ''
  followUp.value = 'ALL'
  owner.value = ''
  search()
}

function selectTab(next: PurchasePlanCategory) {
  if (next === category.value) return
  category.value = next
  rows.value = []
  total.value = 0
  page.value = 1
  void load()
}

function changePage(next: number) {
  if (next === page.value) return
  page.value = next
  void load()
}

async function expandRow(row: PurchasePlanRow, openRows: PurchasePlanRow[]) {
  const isOpen = openRows.some(item => item.id === row.id)
  closeDetail()
  if (!isOpen) return
  expanded.value = row.id
  const { signal } = detailRequest = new AbortController()
  try {
    const result = await fetchPurchasePlanDetail(row.id, row.task_id, category.value, signal)
    if (!signal.aborted) detail.value = result
  } catch (error) {
    if (!signal.aborted) detailError.value = workbenchErrorMessage(error, '读取采购批次')
  }
}

onMounted(load)
onBeforeUnmount(() => { listRequest?.abort(); detailRequest?.abort() })
</script>

<template>
  <section class="erp-glass-list">
    <section v-glass-spotlight class="erp-list-filter">
      <header class="erp-list-heading"><h1>采购计划表</h1></header>
      <form class="erp-list-filters" @submit.prevent="search">
        <ElInput v-model="taskInput" class="plan-filter-input" maxlength="50" clearable
          placeholder="生产任务单号" aria-label="生产任务单号" @clear="search" />
        <ElInput v-model="keywordInput" class="plan-filter-input" maxlength="200" clearable
          placeholder="材料名称或规格" aria-label="材料名称或规格" @clear="search" />
        <DeliveryReminderFilters v-model:follow-up="followUp" v-model:owner="owner" @apply="search" />
        <div class="erp-list-filter-actions">
          <ElButton class="erp-button-motion" @click="reset">重置</ElButton>
          <ElButton class="erp-button-motion" type="primary" native-type="submit">查询</ElButton>
        </div>
      </form>
    </section>
    <section class="erp-list-data">
      <nav class="erp-list-toolbar erp-list-tabs" aria-label="采购计划分类">
        <button v-for="tab in tabs" :key="tab.id" type="button" :class="{ active: category === tab.id }"
          :aria-pressed="category === tab.id" @click="selectTab(tab.id)">{{ tab.label }}</button>
      </nav>
      <ElAlert v-if="errorMessage" :title="errorMessage" type="error" :closable="false">
        <ElButton link @click="load">重试</ElButton>
      </ElAlert>
      <div class="erp-list-table-frame">
        <ElTable v-loading="loading" :data="rows" height="100%" row-key="id" :expand-row-keys="expandedKeys"
          empty-text="暂无符合条件的采购需求" @expand-change="expandRow">
          <ElTableColumn prop="task_number" label="生产任务单号" fixed="left" width="148" show-overflow-tooltip />
          <ElTableColumn label="交期状态" width="108" class-name="delivery-status-column">
            <template #default="{ row }"><DeliveryStatusTag :reminder="row.reminder" /></template>
          </ElTableColumn>
          <ElTableColumn prop="product_name" label="产品名称" min-width="135" show-overflow-tooltip />
          <ElTableColumn prop="task_quantity" label="任务数量" width="95" align="right" />
          <ElTableColumn prop="name" :label="category === 'TUBE' ? '配件名称' : '材料名称'" min-width="125" show-overflow-tooltip />
          <ElTableColumn prop="specification" label="规格" min-width="124" show-overflow-tooltip />
          <template v-if="category === 'TUBE'">
            <ElTableColumn key="thickness" prop="thickness" label="厚度" width="85" show-overflow-tooltip />
            <ElTableColumn key="cutting-length" prop="cutting_length" label="管段长度（mm）" width="122" show-overflow-tooltip />
            <ElTableColumn key="raw-length" label="原料定尺（米）" width="121" show-overflow-tooltip>
              <template #default="{ row }">{{ compactDecimal(row.raw_length, '') }}</template>
            </ElTableColumn>
            <ElTableColumn key="hardness" prop="hardness" label="硬度" width="86" show-overflow-tooltip />
          </template>
          <template v-else>
            <ElTableColumn key="coating" prop="coating" label="涂层" min-width="90" show-overflow-tooltip />
            <ElTableColumn key="fabric-width" prop="fabric_width" label="门幅" min-width="95" show-overflow-tooltip />
            <ElTableColumn key="fabric-color" prop="fabric_color" label="BOM 颜色" min-width="115" show-overflow-tooltip />
          </template>
          <ElTableColumn label="需购数量" min-width="116" align="right">
            <template #default="{ row }">{{ formatAmount(row.required) }}</template>
          </ElTableColumn>
          <ElTableColumn label="实际已采购" min-width="122" align="right">
            <template #default="{ row }">{{ row.ordered.map(formatAmount).join(' / ') }}</template>
          </ElTableColumn>
          <ElTableColumn label="实际已回厂" min-width="122" align="right">
            <template #default="{ row }">{{ row.received.map(formatAmount).join(' / ') }}</template>
          </ElTableColumn>
          <ElTableColumn prop="progress" label="采购到货" min-width="132" show-overflow-tooltip />
          <ElTableColumn label="跟进截止" width="106">
            <template #default="{ row }">
              {{ row.reminder && !row.reminder.shared ? row.reminder.due : '' }}
            </template>
          </ElTableColumn>
          <ElTableColumn label="跟进欠量" min-width="96" align="right" show-overflow-tooltip>
            <template #default="{ row }">
              <template v-if="row.reminder && !row.reminder.shared && row.reminder.quantity !== null">
                {{ compactDecimal(row.reminder.quantity) }} {{ row.reminder.unit }}
              </template>
            </template>
          </ElTableColumn>
          <ElTableColumn type="expand" label="采购批次" width="88">
            <template #default="{ row }">
              <template v-if="detail && detail.id === row.id">
                <div v-if="detail.source_versions.length > 1 || !detail.batches.length || detail.note" class="plan-detail-source">
                  <template v-if="detail.source_versions.length > 1">
                    <span v-for="source in detail.source_versions" :key="source.bom_number">
                      {{ source.bom_number }} <template v-if="source.required">需购 {{ formatAmount(source.required) }}</template>
                    </span>
                  </template>
                  <span v-else-if="!detail.batches.length">{{ detail.bom_number }}</span>
                  <span v-if="detail.note">{{ detail.note }}</span>
                </div>
                <PurchasePlanBatchDetails :batches="detail.batches" :purchase-reminders="detail.purchase_reminders" />
              </template>
              <ElAlert v-else-if="detailError" :title="detailError" type="error" :closable="false">
                <ElButton link @click="expandRow(row, [row])">重试</ElButton>
              </ElAlert>
              <p v-else class="plan-detail-loading" role="status">正在读取采购批次</p>
            </template>
          </ElTableColumn>
        </ElTable>
      </div>
      <footer class="erp-list-footer">
        <span>共 {{ total }} 条</span>
        <ElPagination :current-page="page" :page-size="pageSize" :total="total" layout="prev, pager, next"
          @update:current-page="changePage" />
      </footer>
    </section>
  </section>
</template>

<style scoped>
.plan-filter-input { width: min(100%, 230px); }
.plan-detail-loading, .plan-detail-source { margin: 0; padding: 8px 14px; }
.plan-detail-source { display: flex; flex-wrap: wrap; gap: 4px 22px; font-weight: 600; }
</style>
