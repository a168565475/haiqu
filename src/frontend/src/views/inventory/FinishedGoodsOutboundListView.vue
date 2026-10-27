<script setup lang="ts">
import { compactDecimal } from '@/utils/compactDecimal'
import { computed, onMounted, ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { useRoute, useRouter } from 'vue-router'
import { fetchFinishedGoodsFilterOptions, fetchFinishedGoodsOutbounds } from '@/api/inventory'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { vHorizontalOverflow } from '@/directives/horizontalOverflow'
import type { FinishedGoodsOutbound, MaterialReceivingOptions } from '@/types/inventory'

const route = useRoute(), router = useRouter()
const emit = defineEmits<{ 'select-stock': [] }>()
const rows = ref<FinishedGoodsOutbound[]>([]), total = ref(0), loading = ref(false), errorMessage = ref(''), optionsError = ref('')
const page = ref(1), pageSize = ref(50), keyword = ref(''), warehouse = ref('')
const applied = ref({ q: '', warehouseId: '' })
const options = ref<MaterialReceivingOptions>({ warehouses: [], zones: [] })
const taskId = computed(() => String(route.query.production_task_id || ''))
const productLineId = computed(() => String(route.query.product_line_id || ''))
const money = (value: string | number | null | undefined) => compactDecimal(Number(value || 0).toFixed(2))
const quantity = (value: number | null | undefined) => value == null ? '—' : Number(value).toLocaleString()
const displayLines = (row: FinishedGoodsOutbound) => row.lines.length ? row.lines : [null]
const message = (error: unknown) => error instanceof AxiosError ? (error.response?.data as { error?: { message?: string } })?.error?.message || '出库记录读取失败，请重试。' : '出库记录读取失败，请重试。'
let sequence = 0
async function load() {
  const current = ++sequence
  loading.value = true; errorMessage.value = ''
  try {
    const result = await fetchFinishedGoodsOutbounds({
      production_task_id: taskId.value || undefined, product_line_id: productLineId.value || undefined,
      q: applied.value.q || undefined, warehouse_id: applied.value.warehouseId || undefined,
      page: page.value, page_size: pageSize.value,
    })
    if (current !== sequence) return
    rows.value = result.items; total.value = result.total
  } catch (error) {
    if (current === sequence) { rows.value = []; total.value = 0; errorMessage.value = message(error) }
  } finally { if (current === sequence) loading.value = false }
}
function search() { applied.value = { q: keyword.value.trim(), warehouseId: warehouse.value }; page.value = 1; void load() }
function reset() { keyword.value = ''; warehouse.value = ''; search() }
function resizePage() { page.value = 1; void load() }
function goDetail(id: string) { void router.push({ name: 'finished-goods-outbound-detail', params: { outboundId: id } }) }
watch(() => [taskId.value, productLineId.value], () => { page.value = 1; void load() }, { immediate: true })
onMounted(async () => {
  try { options.value = await fetchFinishedGoodsFilterOptions() }
  catch (error) { optionsError.value = message(error) }
})
const columns = [
  ['出货单号', 155], ['生产任务单号', 140], ['产品编码', 130], ['产品名称', 160], ['货号', 100],
  ['材质', 100], ['规格', 160], ['颜色', 100], ['订单数量', 110], ['入库数量', 110], ['出库数量', 110],
  ['单位', 65], ['出库仓库', 120], ['库位', 110], ['出货日期', 120], ['出库负责人', 115],
  ['装卸费用', 100], ['其他费用', 100], ['操作', 120],
] as const
</script>

<template>
  <section class="outbound-list-page erp-glass-list">
    <section v-glass-spotlight class="erp-list-filter">
      <header class="erp-list-heading"><h1>成品库存</h1></header>
      <div class="outbound-filters erp-list-filters">
        <ElInput v-model="keyword" clearable placeholder="搜索出货单号、生产任务单号或产品信息" @keyup.enter="search" @clear="search" />
        <ElSelect v-model="warehouse" clearable placeholder="全部仓库" @change="search">
          <ElOption v-for="item in options.warehouses" :key="item.id" :value="item.id" :label="item.warehouse_name" />
        </ElSelect>
        <div class="erp-list-filter-actions">
          <ElButton class="erp-button-motion" @click="reset">重置</ElButton>
          <ElButton class="erp-button-motion" type="primary" @click="search">应用筛选</ElButton>
          <ElButton class="erp-button-motion" type="primary" @click="emit('select-stock')">从库存选择出库</ElButton>
        </div>
      </div>
    </section>
    <section class="erp-list-data">
      <div class="fg-toolbar erp-list-toolbar"><slot /></div>
      <ElAlert v-if="errorMessage || optionsError" :title="errorMessage || optionsError" type="error" :closable="false" show-icon />
      <div v-loading="loading" class="erp-list-table-frame">
        <div v-horizontal-overflow class="erp-list-table-scroll scroll-actions-container">
          <table class="outbound-table erp-list-native-table erp-list-native-table--nowrap">
            <colgroup><col v-for="[name, width] in columns" :key="name" :style="{ width: width + 'px' }" /></colgroup>
            <thead><tr><th v-for="[name] in columns" :key="name" :class="{ 'scroll-actions-cell': name === '操作' }" :title="name === '入库数量' ? '来源入库批次的原始入库数量' : name">{{ name }}</th></tr></thead>
            <tbody>
              <template v-for="(row, rowIndex) in rows" :key="row.id">
                <tr v-for="(line, index) in displayLines(row)" :key="line?.id || row.id" :class="{ 'last-document': rowIndex === rows.length - 1 }">
                  <td v-if="index === 0" class="primary document-cell" :rowspan="displayLines(row).length" :title="row.outbound_number">{{ row.outbound_number }}</td>
                  <td>{{ line?.task_number_snapshot || row.task_number_snapshot || '—' }}</td>
                  <td :title="line?.product_code_snapshot">{{ line?.product_code_snapshot || '—' }}</td>
                  <td :title="line?.product_name_snapshot">{{ line?.product_name_snapshot || '—' }}</td>
                  <td>{{ line?.item_number_snapshot || '—' }}</td><td :title="line?.material_snapshot">{{ line?.material_snapshot || '—' }}</td>
                  <td :title="line?.specification_snapshot">{{ line?.specification_snapshot || '—' }}</td><td>{{ line?.actual_color || '—' }}</td>
                  <td class="num">{{ quantity(line?.order_quantity) }}</td><td class="num">{{ quantity(line?.received_quantity) }}</td><td class="num">{{ quantity(line?.outbound_quantity) }}</td>
                  <td>{{ line?.unit_name || '—' }}</td><td :title="line?.warehouse_name">{{ line?.warehouse_name || '—' }}</td><td>{{ line?.location_number || '—' }}</td>
                  <template v-if="index === 0">
                    <td class="document-cell" :rowspan="displayLines(row).length">{{ row.shipment_date || '—' }}</td>
                    <td class="document-cell" :rowspan="displayLines(row).length">{{ row.responsible_employee_name || row.responsible_name_snapshot || '—' }}</td>
                    <td class="num document-cell" :rowspan="displayLines(row).length">{{ money(row.loading_fee) }}</td><td class="num document-cell" :rowspan="displayLines(row).length">{{ money(row.other_fee) }}</td>
                    <td class="scroll-actions-cell document-cell" :rowspan="displayLines(row).length"><ElButton link type="primary" @click="goDetail(row.id)">查看出货单</ElButton></td>
                  </template>
                </tr>
              </template>
              <tr v-if="!rows.length && !loading"><td :colspan="columns.length" class="empty">暂无出库记录</td></tr>
            </tbody>
          </table>
        </div>
      </div>
      <footer class="erp-list-footer"><span>共 {{ total }} 张</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20,50,100]" :total="total" layout="sizes, prev, pager, next" @current-change="load" @size-change="resizePage" /></footer>
    </section>
  </section>
</template>

<style scoped lang="scss">
.outbound-filters > :deep(.el-input) { width: 300px; min-width: 230px; max-width: 410px; flex: 1 1 260px; }
.outbound-filters > :deep(.el-select) { width: 150px; flex: 0 0 150px; }
.outbound-filters .erp-list-filter-actions { margin-left: 0; flex-wrap: wrap; }
.outbound-table { min-width: 2290px; }
// 合并单元格后的 DOM 末格不一定是表格末列，边界按实际列和单据分组处理。
.outbound-table td:last-child:not(.scroll-actions-cell):not(.empty) { border-right: 1px solid var(--erp-table-border); }
.outbound-table .last-document .document-cell { border-bottom: 0; }
.primary { color: var(--erp-color-brand); font-weight: 600; }
.outbound-list-page .el-alert { flex: none; margin-bottom: 10px; }
</style>
