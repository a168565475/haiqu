<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'

import { fetchSewingTracking } from '@/api/sewingTracking'
import DeliveryStatusTag from '@/components/common/DeliveryStatusTag.vue'
import DeliveryReminderFilters from '@/components/common/DeliveryReminderFilters.vue'
import ProductImage from '@/components/products/ProductImage.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import type { DeliveryFollowUp, ReminderFilters } from '@/types/deliveryReminders'
import type { SewingTrackingQuantity, SewingTrackingRow, SewingTrackingUnitPrice } from '@/types/sewingTracking'
import { compactDecimal } from '@/utils/compactDecimal'
import { workbenchErrorMessage } from '@/utils/workbench'

const search = ref('')
const taskNumber = ref('')
const followUp = ref<DeliveryFollowUp>('ALL')
const owner = ref('')
let filters: ReminderFilters = { follow_up: followUp.value, owner: '' }
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const rows = ref<SewingTrackingRow[]>([])
const loading = ref(false)
const errorMessage = ref('')
let request: AbortController | undefined

async function load() {
  request?.abort()
  const { signal } = request = new AbortController()
  loading.value = true
  errorMessage.value = ''
  rows.value = []
  try {
    const data = await fetchSewingTracking({
      task_number: taskNumber.value, ...filters, page: page.value, page_size: pageSize.value,
    }, signal)
    if (signal.aborted) return
    rows.value = data.data
    total.value = data.meta.total
  } catch (error) {
    if (signal.aborted) return
    total.value = 0
    errorMessage.value = workbenchErrorMessage(error, '加载布面跟踪单')
  } finally {
    if (!signal.aborted) loading.value = false
  }
}

function applySearch() {
  taskNumber.value = search.value.trim()
  filters = { follow_up: followUp.value, owner: owner.value.trim() }
  page.value = 1
  void load()
}

function resizePage() {
  page.value = 1
  void load()
}

function quantityText(items: SewingTrackingQuantity[]) {
  return items.map(({ quantity, unit }) => {
    if (quantity === null) return unit ? `待核（${unit}）` : '待核'
    return unit ? `${quantity} ${unit}` : quantity
  }).join(' / ')
}

function unitPriceText(prices: SewingTrackingUnitPrice[]) {
  return prices.map(({ amount, unit }) => `${amount} 元${unit ? `/${unit}` : ''}`).join(' / ')
}

function showDates(dates: string[], first: string | null) {
  return (first ? [first, ...dates.filter(day => day !== first)] : dates).join(' / ')
}

onMounted(load)
onBeforeUnmount(() => request?.abort())
</script>

<template>
  <section class="erp-glass-list sewing-tracking" data-testid="sewing-tracking">
    <section v-glass-spotlight class="erp-list-filter">
      <header class="erp-list-heading"><h1>布面跟踪单</h1></header>
      <form class="erp-list-filters sewing-tracking__search" @submit.prevent="applySearch">
        <ElInput
          v-model="search" class="sewing-tracking__task" clearable maxlength="50" aria-label="生产任务单号"
          placeholder="搜索生产任务单号" :prefix-icon="Search" @clear="applySearch"
        />
        <DeliveryReminderFilters v-model:follow-up="followUp" v-model:owner="owner" @apply="applySearch" />
        <ElButton type="primary" native-type="submit" class="erp-button-motion">查询</ElButton>
      </form>
    </section>

    <section class="erp-list-data">
      <section class="erp-list-table-frame sewing-tracking__grid">
        <ElTable v-loading="loading" :data="rows" row-key="id" height="100%"
          :empty-text="loading ? '加载中…' : '暂无符合条件的布面跟踪记录'">
          <template v-if="errorMessage" #empty>
            <div role="alert">{{ errorMessage }} <ElButton link type="primary" @click="load">重试</ElButton></div>
          </template>
          <ElTableColumn prop="task_number" label="生产任务单号" width="146" fixed="left" show-overflow-tooltip />
          <ElTableColumn label="交期状态" width="108" class-name="delivery-status-column">
            <template #default="{ row }"><DeliveryStatusTag :reminder="row.reminder" /></template>
          </ElTableColumn>
          <ElTableColumn prop="product_name" label="产品名称" min-width="148" show-overflow-tooltip />
          <ElTableColumn prop="part_name" label="部件名称" min-width="136" show-overflow-tooltip />
          <ElTableColumn label="工序" min-width="76">
            <template #default="{ row }">{{ row.process === 'SCREEN_PRINTING' ? '丝印' : '车缝' }}</template>
          </ElTableColumn>
          <ElTableColumn label="产品图片" width="96" align="center">
            <template #default="{ row }">
              <ProductImage v-if="row.product_image_url" :src="row.product_image_url" :name="`${row.product_name}图片`" />
            </template>
          </ElTableColumn>
          <ElTableColumn label="已发" min-width="100" align="right" show-overflow-tooltip>
            <template #default="{ row }">{{ quantityText(row.sent) }}</template>
          </ElTableColumn>
          <ElTableColumn prop="color" label="颜色" min-width="96" show-overflow-tooltip />
          <ElTableColumn prop="factory_name" label="布面加工点" min-width="128" show-overflow-tooltip />
          <ElTableColumn prop="factory_phone" label="联系电话" min-width="128" show-overflow-tooltip />
          <ElTableColumn label="单价" min-width="122" align="right" show-overflow-tooltip>
            <template #default="{ row }">{{ unitPriceText(row.unit_prices) }}</template>
          </ElTableColumn>
          <ElTableColumn label="计划外发日期" min-width="118" show-overflow-tooltip>
            <template #default="{ row }">{{ showDates(row.planned_dispatch_dates, row.reminder?.action === '我方待发' ? row.reminder.due : null) }}</template>
          </ElTableColumn>
          <ElTableColumn label="发加工点日期" min-width="118" show-overflow-tooltip>
            <template #default="{ row }">{{ row.dispatch_dates.join(' / ') }}</template>
          </ElTableColumn>
          <ElTableColumn label="预计回厂日期" min-width="118" show-overflow-tooltip>
            <template #default="{ row }">{{ showDates(row.expected_return_dates, row.reminder?.action === '催回厂' ? row.reminder.due : null) }}</template>
          </ElTableColumn>
          <ElTableColumn prop="last_receipt_date" label="实际入库日期" min-width="118" />
          <ElTableColumn label="已回" min-width="160" align="right" show-overflow-tooltip>
            <template #default="{ row }">
              {{ quantityText(row.received) }}<template v-if="row.transferred.length"> / 直送 {{ quantityText(row.transferred) }}</template>
            </template>
          </ElTableColumn>
          <ElTableColumn label="加工点还欠" min-width="116" align="right" show-overflow-tooltip>
            <template #default="{ row }">{{ quantityText(row.factory_remaining) }}</template>
          </ElTableColumn>
          <ElTableColumn label="我方还没发" min-width="116" align="right" show-overflow-tooltip>
            <template #default="{ row }">{{ quantityText(row.not_sent) }}</template>
          </ElTableColumn>
          <ElTableColumn label="跟进欠量" min-width="88" align="right" show-overflow-tooltip>
            <template #default="{ row }">
              <template v-if="row.reminder && row.reminder.quantity !== null">
                {{ compactDecimal(row.reminder.quantity) }} {{ row.reminder.unit }}
              </template>
            </template>
          </ElTableColumn>
        </ElTable>
      </section>
      <footer class="erp-list-footer">
        <span>共 {{ total }} 条</span>
        <ElPagination v-model:current-page="page" v-model:page-size="pageSize" background
          :page-sizes="[20, 50, 100]" :total="total" layout="sizes, prev, pager, next"
          @current-change="load" @size-change="resizePage" />
      </footer>
    </section>
  </section>
</template>

<style scoped lang="scss">
.sewing-tracking__task { width: min(100%, 250px); }
</style>
