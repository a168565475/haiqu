<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { fetchOutsourcingMovements } from '@/api/outsourcingMovements'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import type { OutsourcingMovementDirection, OutsourcingMovementProcess, OutsourcingMovementRow } from '@/types/outsourcingMovements'
import { compactDecimal } from '@/utils/compactDecimal'
import { workbenchErrorMessage } from '@/utils/workbench'

const tabs = [
  { key: 'dispatch', label: '外协发出', date: '发出日期' },
  { key: 'receipt', label: '外协入库', date: '入库日期' },
] as const
const processLabels: Record<OutsourcingMovementProcess, string> = { SEWING: '车缝', SCREEN_PRINTING: '丝印' }
const direction = ref<OutsourcingMovementDirection>('dispatch')
const process = ref<OutsourcingMovementProcess | ''>('')
const search = ref('')
const taskNumber = ref('')
const page = ref(1)
const pageSize = 20
const total = ref(0)
const rows = ref<OutsourcingMovementRow[]>([])
const loading = ref(false)
const errorMessage = ref('')
let request: AbortController | undefined

async function load() {
  request?.abort()
  const { signal } = request = new AbortController()
  rows.value = []
  errorMessage.value = ''
  loading.value = true
  try {
    const result = await fetchOutsourcingMovements({
      task_number: taskNumber.value, direction: direction.value, process: process.value, page: page.value,
    }, signal)
    if (signal.aborted) return
    rows.value = result.data
    total.value = result.meta.total
  } catch (error) {
    if (!signal.aborted) errorMessage.value = workbenchErrorMessage(error, '查询外协收发')
  } finally {
    if (!signal.aborted) loading.value = false
  }
}

function refresh() {
  page.value = 1
  total.value = 0
  void load()
}

function applySearch() {
  taskNumber.value = search.value.trim()
  refresh()
}

function selectPage(value: number) {
  page.value = value
  void load()
}

watch([direction, process], refresh, { immediate: true })
onBeforeUnmount(() => request?.abort())
</script>

<template>
  <section class="erp-glass-list">
    <section v-glass-spotlight class="erp-list-filter">
      <header class="erp-list-heading"><h1>外协收发</h1></header>
      <form class="erp-list-filters" @submit.prevent="applySearch">
        <ElInput v-model="search" class="movement-task-search" clearable maxlength="50" aria-label="生产任务单号"
          placeholder="输入生产任务单号" :prefix-icon="Search" @clear="applySearch" />
        <ElSelect v-model="process" class="movement-process" aria-label="工序" :empty-values="[null, undefined]">
          <ElOption label="全部工序" value="" />
          <ElOption v-for="(label, value) in processLabels" :key="value" :label="label" :value="value" />
        </ElSelect>
        <ElButton type="primary" native-type="submit" class="erp-button-motion">查询</ElButton>
      </form>
    </section>

    <section class="erp-list-data">
      <ElTabs v-model="direction" class="movement-tabs">
        <ElTabPane v-for="tab in tabs" :key="tab.key" :name="tab.key" :label="tab.label">
          <section v-if="direction === tab.key" class="erp-list-table-frame">
            <ElTable v-loading="loading" :data="rows" row-key="id" height="100%"
              :empty-text="loading ? '加载中…' : '暂无符合条件的记录'">
              <template v-if="errorMessage" #empty>
                <div role="alert">{{ errorMessage }} <ElButton link type="primary" @click="load">重试</ElButton></div>
              </template>
              <ElTableColumn prop="task_number" label="生产任务单号" width="145" show-overflow-tooltip />
              <ElTableColumn :label="tab.date" width="140">
                <template #default="{ row }"><span :title="row.voucher_number">{{ row.business_date }}</span></template>
              </ElTableColumn>
              <ElTableColumn label="工序" width="100">
                <template #default="{ row }">{{ processLabels[(row as OutsourcingMovementRow).process] }}</template>
              </ElTableColumn>
              <ElTableColumn prop="factory_name" label="加工点" min-width="140" show-overflow-tooltip />
              <ElTableColumn prop="item_name" label="物品名称" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">
                  {{ row.item_name || '—' }}
                  <span v-if="row.direct_transfer" class="movement-direct-transfer">丝印点直送</span>
                </template>
              </ElTableColumn>
              <ElTableColumn label="本次数量" width="120" align="right">
                <template #default="{ row }">{{ compactDecimal(row.quantity) }}</template>
              </ElTableColumn>
              <ElTableColumn prop="unit" label="单位" width="80" />
            </ElTable>
          </section>
        </ElTabPane>
      </ElTabs>
      <footer v-if="total > pageSize" class="erp-list-footer">
        <ElPagination :current-page="page" :page-size="pageSize" :total="total" background
          layout="prev, pager, next" @update:current-page="selectPage" />
      </footer>
    </section>
  </section>
</template>

<style scoped>
.movement-task-search { width: min(100%, 250px); }
.movement-process { width: 122px; }
.movement-tabs { display: flex; flex: 1; flex-direction: column; min-height: 0; }
.movement-tabs :deep(.el-tabs__content) { flex: 1; min-height: 0; }
.movement-tabs :deep(.el-tab-pane) { display: flex; height: 100%; flex-direction: column; }
.movement-direct-transfer { margin-inline-start: 8px; color: var(--erp-color-brand); }
</style>
