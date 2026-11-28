<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { fetchPowderCoatingMovements } from '@/api/powderCoating'
import DeliveryStatusTag from '@/components/common/DeliveryStatusTag.vue'
import DeliveryReminderFilters from '@/components/common/DeliveryReminderFilters.vue'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import type { DeliveryFollowUp, ReminderFilters } from '@/types/deliveryReminders'
import type { PowderCoatingDirection, PowderCoatingRow } from '@/types/powderCoating'
import { compactDecimal } from '@/utils/compactDecimal'
import { workbenchErrorMessage } from '@/utils/workbench'

const tabs = {
  dispatch: { label: '喷塑发出', date: '发出日期', quantity: '本次实发数量' },
  receipt: { label: '喷塑收入', date: '入库日期', quantity: '本次实收数量' },
}
const direction = ref<PowderCoatingDirection>('dispatch')
const activeTab = computed(() => tabs[direction.value])
const task = ref('')
const factory = ref('')
const followUp = ref<DeliveryFollowUp>('ALL')
const filters = ref<ReminderFilters & { task_number: string }>({ task_number: '', follow_up: 'ALL', owner: '' })
const page = ref(1)
const pageSize = 20
const total = ref(0)
const rows = ref<PowderCoatingRow[]>([])
const loading = ref(false)
const errorMessage = ref('')
const emptyText = computed(() => {
  if (loading.value) return '加载中…'
  const { task_number, owner, follow_up } = filters.value
  const description = task_number || owner || follow_up !== 'ALL' ? '符合条件的' : ''
  return '暂无' + description + activeTab.value.label + '记录'
})
let request: AbortController | undefined

async function load() {
  request?.abort()
  const { signal } = request = new AbortController()
  loading.value = true
  errorMessage.value = ''
  rows.value = []
  try {
    const data = await fetchPowderCoatingMovements({
      ...filters.value, direction: direction.value, page: page.value, page_size: pageSize,
    }, signal)
    if (signal.aborted) return
    rows.value = data.data
    total.value = data.meta.total
  } catch (error) {
    if (signal.aborted) return
    total.value = 0
    errorMessage.value = workbenchErrorMessage(error, '查询喷塑收发')
  } finally {
    if (!signal.aborted) loading.value = false
  }
}

function applySearch() {
  filters.value = { task_number: task.value.trim(), follow_up: followUp.value, owner: factory.value.trim() }
  page.value = 1
  void load()
}

function selectTab(tab: PowderCoatingDirection) {
  if (tab === direction.value) return
  direction.value = tab
  page.value = 1
  void load()
}

function selectPage(value: number) {
  page.value = value
  void load()
}

function originalOrder(row: PowderCoatingRow) {
  if (row.source === 'TUBE') return { name: 'workshop-outsourcing-tube-detail', params: { id: row.order_id } }
  if (row.source === 'REWORK') return { name: 'workshop-outsourcing-rework-detail', params: { orderId: row.order_id } }
  return {
    name: 'workshop-outsourcing-detail',
    params: { orderId: row.order_id },
    query: row.source === 'METAL' ? { view: 'metal' } : undefined,
  }
}

onMounted(load)
onBeforeUnmount(() => request?.abort())
</script>

<template>
  <section class="erp-glass-list powder-coating-movements">
    <section v-glass-spotlight class="erp-list-filter">
      <header class="erp-list-heading"><h1>喷塑收发</h1></header>
      <form class="erp-list-filters" @submit.prevent="applySearch">
        <ElInput v-model="task" class="powder-coating-task" clearable maxlength="50" aria-label="生产任务单号"
          placeholder="输入生产任务单号" :prefix-icon="Search" @clear="applySearch" />
        <DeliveryReminderFilters v-model:follow-up="followUp" v-model:owner="factory"
          owner-label="喷塑厂" @apply="applySearch" />
        <ElButton type="primary" native-type="submit" class="erp-button-motion">查询</ElButton>
      </form>
    </section>

    <section class="erp-list-data">
      <nav class="erp-list-toolbar erp-list-tabs" aria-label="喷塑收发类型">
        <button v-for="(tab, key) in tabs" :key="key" type="button" :class="{ active: direction === key }"
          :aria-pressed="direction === key" @click="selectTab(key)">{{ tab.label }}</button>
      </nav>
      <div class="erp-list-table-frame">
        <ElTable v-loading="loading" :data="rows" row-key="id" height="100%" :empty-text="emptyText">
          <template v-if="errorMessage" #empty>
            <div role="alert">{{ errorMessage }} <ElButton link type="primary" @click="load">重试</ElButton></div>
          </template>
          <ElTableColumn prop="task_number" label="生产任务单号" width="145" fixed="left" show-overflow-tooltip />
          <ElTableColumn prop="business_date" :label="activeTab.date" width="112" class-name="movement-date-column" />
          <ElTableColumn label="收发凭证号" width="150" class-name="movement-voucher-column" show-overflow-tooltip>
            <template #default="{ row }">
              <RouterLink class="powder-coating-voucher" :to="originalOrder(row)" target="_blank" rel="noopener">
                {{ row.voucher_number }}
              </RouterLink>
            </template>
          </ElTableColumn>
          <ElTableColumn label="交期状态" width="108" class-name="delivery-status-column">
            <template #default="{ row }"><DeliveryStatusTag :reminder="row.reminder" /></template>
          </ElTableColumn>
          <ElTableColumn label="约定回厂日" width="114" class-name="movement-deadline-column">
            <template #default="{ row }">{{ row.expected_return_date || '—' }}</template>
          </ElTableColumn>
          <ElTableColumn prop="factory_name" label="喷塑厂" min-width="128" show-overflow-tooltip />
          <ElTableColumn prop="part_name" label="管件名称" min-width="128" show-overflow-tooltip />
          <ElTableColumn prop="specification" label="规格" min-width="128" show-overflow-tooltip>
            <template #default="{ row }">{{ row.specification || '—' }}</template>
          </ElTableColumn>
          <ElTableColumn prop="spray_color" label="喷塑颜色" min-width="104" show-overflow-tooltip>
            <template #default="{ row }">{{ row.spray_color || '—' }}</template>
          </ElTableColumn>
          <ElTableColumn :label="activeTab.quantity" width="126" align="right">
            <template #default="{ row }">{{ compactDecimal(row.quantity) }}</template>
          </ElTableColumn>
          <ElTableColumn prop="unit" label="单位" width="62" />
        </ElTable>
      </div>
      <footer v-if="total > 0" class="erp-list-footer">
        <span>共 {{ total }} 条</span>
        <ElPagination :current-page="page" :page-size="pageSize" :total="total"
          layout="prev, pager, next" @update:current-page="selectPage" />
      </footer>
    </section>
  </section>
</template>

<style scoped>
.powder-coating-task { width: min(100%, 250px); }
.powder-coating-voucher { color: var(--erp-color-brand); }
</style>
