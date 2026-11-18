<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { fetchMaterialTransfers } from '@/api/inventory'
import { canOpenPage } from '@/router/pageAccess'
import { useAuthStore } from '@/stores/auth'
import type { MaterialTransferLineRecord, MaterialTransferRecord } from '@/types/inventory'
import { formatQuantity } from '@/views/procurement/purchaseOrderDetailDisplay'

const auth = useAuthStore()
const canView = computed(() => canOpenPage('material-inbound-records', auth))
const rows = ref<MaterialTransferRecord[]>([])
const loading = ref(false)
const error = ref('')
const attributeLabels: Record<string, string> = {
  material: '材质', color: '颜色', shape: '截面形状', section_size: '规格', thickness: '厚度',
  length: '长度', fabric_spec: '面料规格', width: '门幅/宽度', gram_weight: '克重',
  finish: '涂层/后处理', surface_finish: '表面处理', specification: '规格描述',
  size: '尺寸', thread: '螺纹规格', flow_unit: '流转单位', model: '型号/图号',
  tube_size: '适配管材尺寸', layers: '层数', box_type: '箱子形状', bag_type: '袋型/封口方式',
  printing: '印刷版本', process: '加工做法/工艺版本',
}
const lineRows = computed(() => rows.value.flatMap(record => record.lines.map((line, index) => ({
  record, line, key: `${record.id}:${line.line_key || index}`,
}))))
// 历史属性只读保存快照，目录重命名或维护权限不影响记录的展示。
const attributeKeys = computed(() => {
  const keys = new Set<string>()
  lineRows.value.forEach(({ line }) => {
    Object.keys(line.material_selection_snapshot?.attributes || {}).forEach(key => keys.add(key))
    if (line.material_selection_snapshot?.color_name) keys.add('color')
  })
  const order = Object.keys(attributeLabels)
  return [...keys].sort((left, right) => {
    const a = order.indexOf(left)
    const b = order.indexOf(right)
    return (a < 0 ? 999 : a) - (b < 0 ? 999 : b)
  })
})
const hasColorIdentity = computed(() => lineRows.value.some(({ line }) => {
  const snapshot = line.material_selection_snapshot
  return snapshot?.category_key === 'FABRIC' || snapshot?.color_card || snapshot?.color_code
}))
function isTube(line: MaterialTransferLineRecord) {
  return line.material_selection_snapshot?.category_key === 'TUBE' || !!line.raw_bar_length_m
}
const hasTube = computed(() => lineRows.value.some(({ line }) => isTube(line)))
const columnCount = computed(() => 10 + attributeKeys.value.length + (hasColorIdentity.value ? 2 : 0) + (hasTube.value ? 2 : 0))
const tableWidth = computed(() => 1590 + attributeKeys.value.length * 150 + (hasColorIdentity.value ? 260 : 0) + (hasTube.value ? 300 : 0))
function attributeValue(line: MaterialTransferLineRecord, key: string) {
  const snapshot = line.material_selection_snapshot
  return (key === 'color' ? snapshot?.color_name || snapshot?.attributes?.color : snapshot?.attributes?.[key]) || '—'
}
function weightValue(line: MaterialTransferLineRecord) {
  if (!isTube(line)) return '—'
  const value = formatQuantity(line.weight_quantity)
  return value === '—' ? '重量待核对' : value
}
async function refresh() {
  if (!canView.value || loading.value) return
  loading.value = true
  error.value = ''
  try { rows.value = await fetchMaterialTransfers() }
  catch { rows.value = []; error.value = '收发记录加载失败，请刷新重试。' }
  finally { loading.value = false }
}
onMounted(() => { void refresh() })
</script>

<template>
  <section class="transfer-records-page erp-glass-list" data-testid="material-transfer-records-page">
    <div v-if="!canView" class="empty-state"><h1>无权查看收发记录</h1><p>请联系管理员开通材料收发记录查看权限。</p></div>
    <template v-else>
      <section class="erp-list-filter">
        <header class="erp-list-heading"><h1>收发记录</h1></header>
      </section>
      <section class="erp-list-data">
        <div class="erp-list-toolbar records-toolbar"><ElButton :icon="Refresh" :loading="loading" @click="refresh">刷新</ElButton></div>
        <div v-loading="loading" class="erp-list-table-frame">
          <div class="erp-list-table-scroll">
          <table class="erp-list-native-table records-table" :style="{ minWidth: `${tableWidth}px` }">
            <colgroup>
              <col class="number-column"><col class="direction-column"><col class="date-column"><col class="operator-column"><col class="name-column">
              <col v-for="key in attributeKeys" :key="key" class="attribute-column">
              <template v-if="hasColorIdentity"><col class="color-column"><col class="color-column"></template>
              <col class="quantity-column"><col class="unit-column">
              <template v-if="hasTube"><col class="attribute-column"><col class="attribute-column"></template>
              <col class="warehouse-column"><col class="zone-column"><col class="remark-column">
            </colgroup>
            <thead><tr>
              <th>单号</th><th>方向</th><th>日期</th><th>操作人</th><th>品名</th>
              <th v-for="key in attributeKeys" :key="key">{{ attributeLabels[key] || key }}</th>
              <template v-if="hasColorIdentity"><th>色卡</th><th>色号</th></template>
              <th class="num">数量</th><th>单位</th>
              <template v-if="hasTube"><th class="num">单根原长（m）</th><th class="num">实际重量（kg）</th></template>
              <th>仓库</th><th>库区</th><th>备注</th>
            </tr></thead>
            <tbody>
              <tr v-for="row in lineRows" :key="row.key">
                <td :title="row.record.transfer_number">{{ row.record.transfer_number }}</td>
                <td><ElTag :type="row.record.direction === 'IN' ? 'success' : 'warning'" effect="light">{{ row.record.direction_display }}</ElTag></td>
                <td>{{ row.record.transfer_date }}</td><td :title="row.record.operated_by_name">{{ row.record.operated_by_name }}</td>
                <td :title="row.line.material_selection_snapshot?.name || row.line.catalog_name">{{ row.line.material_selection_snapshot?.name || row.line.catalog_name || '—' }}</td>
                <td v-for="key in attributeKeys" :key="key" :title="attributeValue(row.line, key)">{{ attributeValue(row.line, key) }}</td>
                <template v-if="hasColorIdentity"><td :title="row.line.material_selection_snapshot?.color_card">{{ row.line.material_selection_snapshot?.color_card || '—' }}</td><td :title="row.line.material_selection_snapshot?.color_code">{{ row.line.material_selection_snapshot?.color_code || '—' }}</td></template>
                <td class="num">{{ formatQuantity(row.line.quantity) }}</td><td>{{ row.line.material_selection_snapshot?.unit_name || row.line.unit_name || '—' }}</td>
                <template v-if="hasTube"><td class="num">{{ isTube(row.line) ? formatQuantity(row.line.raw_bar_length_m) : '—' }}</td><td class="num">{{ weightValue(row.line) }}</td></template>
                <td :title="row.line.warehouse_name">{{ row.line.warehouse_name || '—' }}</td><td :title="row.line.zone_name">{{ row.line.zone_name || '—' }}</td>
                <td :title="row.record.remark">{{ row.record.remark || '—' }}</td>
              </tr>
              <tr v-if="!lineRows.length"><td :colspan="columnCount" class="empty-cell">{{ error || (loading ? '正在加载…' : '暂无材料收发记录') }}</td></tr>
            </tbody>
          </table>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped lang="scss">
.records-toolbar { justify-content: flex-end; }
.records-table th, .records-table td { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.number-column { width: 210px; }
.direction-column { width: 100px; }
.date-column { width: 130px; }
.operator-column { width: 130px; }
.name-column { width: 180px; }
.attribute-column { width: 150px; }
.color-column { width: 130px; }
.quantity-column { width: 120px; }
.unit-column { width: 80px; }
.warehouse-column { width: 160px; }
.zone-column { width: 140px; }
.remark-column { width: 240px; }
.empty-state { padding: 60px; text-align: center; color: var(--erp-color-text-secondary); }
</style>
