<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { fetchSampleInventoryCandidates } from '@/api/sampleWarehouse'
import { sampleAllocationTotal, sampleSupplyResult } from '@/utils/sampleWarehouse'
import type { SampleInventoryAllocation, SampleInventoryCandidate, SampleWarehouseInventory, SampleWarehouseLine } from '@/types/sampleWarehouse'

const props = defineProps<{ sampleId: string; lines: SampleWarehouseLine[]; activeLineKey: string; modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [open: boolean]; apply: [lines: SampleWarehouseLine[]] }>()
const selected = ref<Record<string, SampleInventoryAllocation[]>>({})
const changedKeys = new Set<string>()
const candidates = ref<SampleWarehouseInventory['lines']>([])
const filterKey = ref('all'), loading = ref(false), errorMessage = ref(''), validation = ref('')
let requestNumber = 0
const visibleLines = computed(() => props.lines.filter(line => filterKey.value === 'all' || line.key === filterKey.value))
const rowsFor = (key: string) => candidates.value.find(line => line.lineKey === key)?.candidates || []
const selection = (key: string, id: string) => selected.value[key]?.find(row => row.balanceId === id)
const total = (line: SampleWarehouseLine) => sampleAllocationTotal(line.category, selected.value[line.key] || [])
const display = (value: string | null) => value === null ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
const selectedCount = computed(() => Object.values(selected.value).filter(rows => rows.length).length)
const tableRows = computed(() => visibleLines.value.flatMap(line => {
  const stockRows: Array<SampleInventoryCandidate | null> = rowsFor(line.key)
  return (stockRows.length ? stockRows : [null]).map(stock => ({
    rowKey: `${line.key}:${stock?.stockMode || ''}:${stock?.balanceId || 'empty'}`, line, stock,
  }))
}))
const hasTube = computed(() => visibleLines.value.some(line => line.category === 'tube'))
const missingLines = computed(() => visibleLines.value.filter(line =>
  (selected.value[line.key] || []).some(item => !rowsFor(line.key).some(row => row.balanceId === item.balanceId)),
))
function choose(key: string, row: SampleInventoryCandidate, checked: boolean) {
  changedKeys.add(key)
  const rest = (selected.value[key] || []).filter(item => item.balanceId !== row.balanceId)
  selected.value[key] = checked ? [...rest, { ...row, quantity: '' }] : rest
  validation.value = ''
}
function setQuantity(key: string, id: string, value: string) {
  changedKeys.add(key)
  const row = selection(key, id)
  if (row) row.quantity = value
  validation.value = ''
}
async function load() {
  const request = ++requestNumber
  loading.value = true; errorMessage.value = ''; validation.value = ''
  try {
    const result = await fetchSampleInventoryCandidates(props.sampleId)
    if (request === requestNumber) candidates.value = result.lines
  } catch { if (request === requestNumber) errorMessage.value = '需求库存查询失败或没有核对权限，请重试。' }
  finally { if (request === requestNumber) loading.value = false }
}
function apply() {
  if (loading.value || errorMessage.value) return
  const used = new Map<string, SampleInventoryAllocation[]>()
  const result: SampleWarehouseLine[] = []
  for (const line of props.lines) {
    const selections = selected.value[line.key] || []
    const quantity = total(line)
    if (quantity === null) { validation.value = `${line.name}：请填写有效供料数量，管材按整数根填写。`; return }
    if (!sampleSupplyResult(line.quantity, quantity).valid) { validation.value = `${line.name}：供料合计不能超过需求数量。`; return }
    for (const item of selections) {
      const current = rowsFor(line.key).find(row => row.balanceId === item.balanceId && row.stockMode === item.stockMode)
      const id = `${item.stockMode}:${item.balanceId}`
      const shared = [...(used.get(id) || []), item]
      const amount = sampleAllocationTotal('other', shared)
      if (!current || amount === null || !sampleSupplyResult(current.availableQuantity, amount).valid) { validation.value = `${line.name}：所选库存已失效或供料超出可用数量，请重新查询。`; return }
      if (current.rawBarLengthM !== item.rawBarLengthM) { validation.value = `${line.name}：库存单根长度已变化，请重新勾选。`; return }
      used.set(id, shared)
    }
    result.push(filterKey.value === 'all' || filterKey.value === line.key || changedKeys.has(line.key)
      ? { ...line, supplyQuantity: quantity, inventoryAllocations: selections.map(row => ({ ...row })) }
      : line)
  }
  emit('apply', result); emit('update:modelValue', false)
}
watch(() => [props.modelValue, props.sampleId], () => {
  if (props.modelValue) {
    changedKeys.clear()
    filterKey.value = props.activeLineKey || 'all'
    selected.value = Object.fromEntries(props.lines.map(line => [line.key, (line.inventoryAllocations || []).map(row => ({ ...row }))]))
    candidates.value = []; void load()
  } else { requestNumber++; loading.value = false }
}, { immediate: true })
onBeforeUnmount(() => { requestNumber++ })
</script>

<template>
  <AppWindowDialog :model-value="modelValue" title="查询库存与关联供料" width="1580px" :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <div class="lookup-toolbar">
      <span>共 {{ visibleLines.length }} 项需求 · 已选 {{ selectedCount }} 项</span>
      <ElButton :loading="loading" @click="load">重新查询</ElButton>
    </div>
    <ElAlert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />
    <div v-else v-loading="loading">
      <ElTable class="lookup-table" :data="tableRows" row-key="rowKey" :max-height="480" empty-text="暂无用料需求">
        <ElTableColumn label="选择" width="52" align="center" fixed="left">
          <template #default="{ row }"><ElCheckbox :model-value="!!row.stock && !!selection(row.line.key, row.stock.balanceId)" :disabled="!row.stock" :aria-label="`选择 ${row.line.specification} ${row.stock?.zoneName || '暂无库存'}`" @change="row.stock && choose(row.line.key, row.stock, !!$event)" /></template>
        </ElTableColumn>
        <ElTableColumn prop="line.name" label="材料名称" min-width="96" show-overflow-tooltip />
        <ElTableColumn prop="line.specification" label="规格" min-width="170" show-overflow-tooltip />
        <ElTableColumn prop="line.material" label="材质" min-width="76" show-overflow-tooltip />
        <ElTableColumn prop="line.color" label="颜色" min-width="110" show-overflow-tooltip />
        <ElTableColumn label="需求数量" width="96" align="right"><template #default="{ row }">{{ display(row.line.quantity) }} {{ row.line.unitLabel }}</template></ElTableColumn>
        <ElTableColumn label="可用库存" width="96" align="right"><template #default="{ row }">{{ display(row.stock?.availableQuantity || '0') }} {{ row.stock?.unitLabel || (row.line.category === 'tube' ? '根' : row.line.unitLabel) }}</template></ElTableColumn>
        <ElTableColumn v-if="hasTube" label="单根长度" width="96" align="right"><template #default="{ row }">{{ row.stock?.rawBarLengthM ? `${display(row.stock.rawBarLengthM)} 米` : '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="hasTube" label="库存米数" width="96" align="right"><template #default="{ row }">{{ row.line.category === 'tube' ? `${display(row.stock?.meterQuantity || '0')} 米` : '—' }}</template></ElTableColumn>
        <ElTableColumn prop="stock.warehouseName" label="材料仓" min-width="120" show-overflow-tooltip><template #default="{ row }">{{ row.stock?.warehouseName || '—' }}</template></ElTableColumn>
        <ElTableColumn prop="stock.zoneName" label="库区" min-width="90" show-overflow-tooltip><template #default="{ row }">{{ row.stock?.zoneName || '—' }}</template></ElTableColumn>
        <ElTableColumn prop="stock.materialNumber" label="品号" min-width="120" show-overflow-tooltip><template #default="{ row }">{{ row.stock?.materialNumber || '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="hasTube" label="供料米数" width="96" align="right"><template #default="{ row }">{{ row.line.category === 'tube' && row.stock && selection(row.line.key, row.stock.balanceId) ? display(sampleAllocationTotal('tube', [selection(row.line.key, row.stock.balanceId)!])) : '—' }}</template></ElTableColumn>
        <ElTableColumn label="本次供料" width="144" fixed="right">
          <template #default="{ row }">
            <ElInput v-if="row.stock" :model-value="selection(row.line.key, row.stock.balanceId)?.quantity || ''" :disabled="!selection(row.line.key, row.stock.balanceId)" :aria-label="`供料数量 ${row.line.specification} ${row.stock.zoneName}`" inputmode="decimal" placeholder="勾选后填写" @update:model-value="setQuantity(row.line.key, row.stock.balanceId, $event)"><template #suffix>{{ row.stock.unitLabel }}</template></ElInput>
            <span v-else class="no-stock">暂无库存</span>
          </template>
        </ElTableColumn>
      </ElTable>
      <div v-for="line in missingLines" :key="line.key" class="missing-stock">{{ line.name }} {{ line.specification }}：原关联库存已不可用。<ElButton link type="primary" @click="selected[line.key] = []; changedKeys.add(line.key)">清除该项关联</ElButton></div>
    </div>
    <p v-if="validation" role="alert" class="lookup-error">{{ validation }}</p>
    <template #footer><div class="lookup-footer"><span>应用后回填供料数量，随核对提交保存；领料时复核库存。</span><ElButton @click="emit('update:modelValue', false)">取消</ElButton><ElButton type="primary" :disabled="loading || !!errorMessage" @click="apply">应用关联</ElButton></div></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.lookup-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.lookup-toolbar > span { flex: 1; color: var(--erp-color-text-secondary); font-size: 12px; }
.no-stock { color: var(--erp-color-text-secondary); }
.lookup-table { border: 1px solid var(--erp-table-frame-border); border-radius: 5px; --el-table-border-color: var(--erp-table-border); --el-table-header-bg-color: var(--erp-table-header-background); --el-table-tr-bg-color: var(--erp-table-background); --el-table-row-hover-bg-color: var(--erp-table-hover); --el-table-text-color: var(--erp-table-text); --el-table-header-text-color: var(--erp-table-header-text); font-size: 12px; }
.lookup-table :deep(.el-table__inner-wrapper::before) { display: none; }
.lookup-table :deep(th.el-table__cell) { height: 44px; padding: 0; font-weight: 500; }
.lookup-table :deep(td.el-table__cell) { height: 40px; padding: 0; }
.lookup-table :deep(.cell) { padding: 0 12px; line-height: 18px; white-space: nowrap; }
.lookup-table :deep(.el-table__body tr:last-child td) { border-bottom: 0; }
.lookup-table :deep(.el-table__empty-text) { width: auto; padding: 12px; line-height: 24px; }
.lookup-footer { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; width: 100%; }
.lookup-footer > span { flex: 1; color: var(--erp-color-text-secondary); font-size: 12px; text-align: left; }
.lookup-footer .el-button { margin-left: 0; }
.lookup-error, .missing-stock { color: var(--el-color-danger); font-size: 13px; margin: 10px 0 0; }
</style>
