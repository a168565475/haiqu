<script setup lang="ts">
import { computed, ref } from 'vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import BomAttributesTooltip from '@/components/common/BomAttributesTooltip.vue'
import type { MaterialRequirement, MaterialIssueBatch } from '@/types/materialIssue'
import { decimalUnits } from '@/utils/outsourcingQuantities'
import { issuePipePlan, issueQuantityError, issueQuantityText } from '@/utils/materialIssueQuantities'

const props = withDefaults(defineProps<{
  requirements: MaterialRequirement[]
  selected: Record<string, string>
  allocations: Record<string, MaterialIssueBatch[]>
  showPipeDeductionColumns?: boolean
}>(), {
  showPipeDeductionColumns: true,
})
const picker = ref<'RAW' | 'SEMI'>('RAW')
const visible = ref(false)
const search = ref('')
const draftSelectedIds = ref<Set<string>>(new Set())
const processingStatus = ref('')
const raw = computed(() => chosen('RAW'))
const semi = computed(() => chosen('SEMI'))
const hasPublicSemi = computed(() => props.requirements.some(row => row.line_type === 'SEMI' && row.stock_mode === 'PUBLIC_V2'))
const statusOptions = ['已喷塑', '未喷塑']
const processingStatusLabel = (row: MaterialRequirement) => {
  if (row.processing_status) return row.processing_status
  const snapshot = row.conversion_snapshot as unknown as { public_identity?: { identity_snapshot?: { completed_craft?: { code?: string } } } }
  const code = snapshot?.public_identity && typeof snapshot.public_identity === 'object'
    ? snapshot.public_identity.identity_snapshot?.completed_craft?.code
    : ''
  if (code === 'POWDER_COATING' || row.completed_craft?.includes('喷塑')) return '已喷塑'
  if (code === 'METAL' || row.completed_craft?.includes('金工')) return '未喷塑'
  return row.completed_craft || '—'
}
const candidates = computed(() => props.requirements.filter(r => r.line_type === picker.value
  && (picker.value !== 'SEMI' || (decimalUnits(String(r.available_stock ?? '0')) || 0n) > 0n)
  && (!processingStatus.value || processingStatusLabel(r) === processingStatus.value)
  && `${r.material_name} ${(r.part_names || []).join(' ')} ${r.conversion_snapshot?.part_name || ''} ${r.material || ''} ${r.specification} ${r.color}`.includes(search.value)))
const pipeRows = computed(() => raw.value.filter(isPipe))
const showPipeDeduction = computed(() => props.showPipeDeductionColumns && pipeRows.value.length > 0)
const isPipe = (r: MaterialRequirement) => r.line_type === 'RAW' && r.conversion_snapshot?.kind === 'PIPE'
const name = (r: MaterialRequirement) => r.conversion_snapshot?.part_name || r.material_name
const partNames = (r: MaterialRequirement) => r.part_names?.length ? r.part_names.join('、') : (r.conversion_snapshot?.part_name || '—')
const attributeValue = (r: MaterialRequirement, keys: string[], fallback = '') => {
  const field = (r.bom_attributes || []).find(item => keys.includes(item.key) && String(item.value || '').trim())
  return field?.value || fallback || '—'
}
const materialValue = (r: MaterialRequirement) => attributeValue(r, ['material'], r.material || '')
const specificationValue = (r: MaterialRequirement) => attributeValue(r, ['specification'], r.specification || '')
const colorValue = (r: MaterialRequirement, preferActual = false) => {
  if (preferActual && String(r.color || '').trim()) return r.color
  return attributeValue(r, ['hardware_color', 'plastic_color', 'fabric_color_name', 'accessory_color', 'packaging_color'], r.color || '')
}
const tooltipKeys = ['part_name', 'material', 'specification', 'hardware_color', 'plastic_color', 'fabric_color_name', 'accessory_color', 'packaging_color']
function chosen(type: string) { return props.requirements.filter(r => r.line_type === type && r.requirement_id in props.selected) }
function open(type: 'RAW' | 'SEMI') {
  picker.value = type
  search.value = ''
  processingStatus.value = ''
  draftSelectedIds.value = new Set(chosen(type).map(row => row.requirement_id))
  visible.value = true
}
function setDraftSelected(row: MaterialRequirement, checked: boolean) {
  const next = new Set(draftSelectedIds.value)
  if (checked) next.add(row.requirement_id)
  else next.delete(row.requirement_id)
  draftSelectedIds.value = next
}
function addCandidate(row: MaterialRequirement) { setDraftSelected(row, !draftSelectedIds.value.has(row.requirement_id)) }
function completeSelection() {
  for (const row of props.requirements.filter(item => item.line_type === picker.value)) {
    const id = row.requirement_id
    if (!draftSelectedIds.value.has(id)) {
      if (id in props.selected) remove(row)
      continue
    }
    if (props.selected[id] === undefined || props.selected[id] === '') props.selected[id] = '0'
  }
  visible.value = false
}
function remove(row: MaterialRequirement) { delete props.selected[row.requirement_id]; delete props.allocations[row.requirement_id] }
function plan(row: MaterialRequirement) { return issuePipePlan(props.selected[row.requirement_id] || '', row) }
function quantityRuleError(row: MaterialRequirement) {
  const value = String(props.selected[row.requirement_id] ?? '').trim()
  if (!value) return ''
  const amount = decimalUnits(value)
  if (amount === 0n) return ''
  return issueQuantityError(value, row)
}
function zoneNames(row: MaterialRequirement) {
  return [...new Set(row.warehouse_zones || [])]
}
function remainder(row: MaterialRequirement) {
  const value = (decimalUnits(row.available_stock) || 0n) - (decimalUnits(props.selected[row.requirement_id]) || 0n)
  return value < 0n ? '库存不足' : `${value / 10000n}.${String(value % 10000n).padStart(4, '0')}`.replace(/\.?0+$/, '') || '0'
}
</script>

<template>
  <div class="issue-partitions">
    <section class="mi-surface partition" data-testid="raw-partition">
      <header><div><h2>原材料领料</h2><span v-if="showPipeDeduction">管材按支申请，按整根及米数扣库</span></div><ElButton @click="open('RAW')">＋ 添加原材料</ElButton></header>
      <ElTable class="scroll-actions-table" :data="raw" border empty-text="请选择本产品、本车间的原材料" row-key="requirement_id">
         <ElTableColumn label="品名" min-width="150" show-overflow-tooltip><template #default="{ row }"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys">{{ row.material_name }}</BomAttributesTooltip></template></ElTableColumn>
         <ElTableColumn label="部位" min-width="130" show-overflow-tooltip><template #default="{ row }"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys">{{ partNames(row) }}</BomAttributesTooltip></template></ElTableColumn>
         <ElTableColumn label="材质" min-width="120" show-overflow-tooltip><template #default="{ row }">{{ materialValue(row) }}</template></ElTableColumn>
         <ElTableColumn label="规格" min-width="170" show-overflow-tooltip><template #default="{ row }">{{ specificationValue(row) }}</template></ElTableColumn>
         <ElTableColumn label="颜色" width="100"><template #default="{ row }">{{ colorValue(row) }}</template></ElTableColumn>
        <ElTableColumn prop="unit" label="单位" width="70" align="center" />
        <ElTableColumn label="本订单需求" width="110" align="center"><template #default="{ row }">{{ issueQuantityText(row.required_quantity) }}</template></ElTableColumn>
        <ElTableColumn label="本订单已领取" width="120" align="center"><template #default="{ row }">{{ issueQuantityText(row.internal_issued_quantity) }}</template></ElTableColumn>
        <ElTableColumn label="本订单已外发" width="120" align="center"><template #default="{ row }">{{ issueQuantityText(row.outsourcing_issued_quantity) }}</template></ElTableColumn>
        <ElTableColumn label="本订单待审核" width="120" align="center"><template #default="{ row }">{{ row.pending_issue_quantity || '0' }}</template></ElTableColumn>
        <ElTableColumn label="本次可领" width="110" align="center"><template #default="{ row }">{{ issueQuantityText(row.max_issue_quantity) }}</template></ElTableColumn>
        <ElTableColumn label="库区" min-width="105" show-overflow-tooltip><template #default="{ row }">{{ zoneNames(row).join('、') || '—' }}</template></ElTableColumn>
        <ElTableColumn label="申请数量" width="160" align="center"><template #default="{ row }"><ElTooltip :visible="Boolean(quantityRuleError(row))" placement="bottom" effect="light" popper-class="material-issue-rule-tooltip" :show-after="0" :hide-after="0" :teleported="true"><template #content><span role="alert">{{ quantityRuleError(row) }}</span></template><ElInput v-model="selected[row.requirement_id]" class="quantity-input" :class="{ 'is-rule-error': Boolean(quantityRuleError(row)) }" :aria-invalid="Boolean(quantityRuleError(row))" :aria-label="`${name(row)}申请数量`" /></ElTooltip></template></ElTableColumn>
        <ElTableColumn v-if="showPipeDeduction" label="每根切割" width="110"><template #default="{ row }">{{ isPipe(row) ? `${row.conversion_snapshot?.pieces_per_bar} 支` : '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="showPipeDeduction" label="预计扣根数" width="115"><template #default="{ row }">{{ isPipe(row) ? `${plan(row).bars} 根` : '—' }}</template></ElTableColumn>
        <ElTableColumn v-if="showPipeDeduction" label="预计扣米数" width="130"><template #default="{ row }">{{ isPipe(row) ? `${plan(row).meters} 米` : '—' }}</template></ElTableColumn>
        <ElTableColumn label="操作" width="72" fixed="right"><template #default="{ row }"><ElButton link type="danger" @click="remove(row)">移除</ElButton></template></ElTableColumn>
      </ElTable>
      <div v-if="showPipeDeduction" class="partition-note"><b>换算规则</b>　申请支数 ÷ 每根切割支数 = 整根数；整根数 × 原材料长度 = 扣库米数。系统按相同物料和规格的合格库存自动分配。</div>
    </section>
    <section class="mi-surface partition" data-testid="semi-partition">
      <header><div><h2>外发回库半成品领料</h2><span>管材按支、裁片按套领取，按部位分别计算</span></div><ElButton @click="open('SEMI')">＋ 添加半成品</ElButton></header>
      <ElTable class="scroll-actions-table" :data="semi" border empty-text="本次尚未选择外发回库半成品" row-key="requirement_id">
         <ElTableColumn label="半成品 / 部位" min-width="180"><template #default="{ row }"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys">{{ row.material_name }}</BomAttributesTooltip></template></ElTableColumn>
         <ElTableColumn label="材质" min-width="120" show-overflow-tooltip><template #default="{ row }">{{ materialValue(row) }}</template></ElTableColumn>
         <ElTableColumn label="规格" min-width="170" show-overflow-tooltip><template #default="{ row }">{{ specificationValue(row) }}</template></ElTableColumn>
         <ElTableColumn label="颜色" width="100"><template #default="{ row }">{{ colorValue(row, true) }}</template></ElTableColumn>
        <ElTableColumn label="加工状态" width="110"><template #default="{ row }">{{ processingStatusLabel(row) }}</template></ElTableColumn>
        <ElTableColumn label="库区" min-width="140" show-overflow-tooltip><template #default="{ row }">{{ row.warehouse_zone || '—' }}</template></ElTableColumn>
        <template v-if="hasPublicSemi">
          <ElTableColumn label="本订单需求" width="110"><template #default="{ row }">{{ row.stock_mode === 'PUBLIC_V2' ? issueQuantityText(row.required_quantity) : '—' }}</template></ElTableColumn>
          <ElTableColumn label="本订单已领取" width="120"><template #default="{ row }">{{ row.stock_mode === 'PUBLIC_V2' ? issueQuantityText(row.internal_issued_quantity) : '—' }}</template></ElTableColumn>
          <ElTableColumn label="本订单待审核" width="120"><template #default="{ row }">{{ row.stock_mode === 'PUBLIC_V2' ? issueQuantityText(row.pending_issue_quantity || '0') : '—' }}</template></ElTableColumn>
        </template>
        <ElTableColumn v-if="!hasPublicSemi" label="合格库存" width="130"><template #default="{ row }">{{ issueQuantityText(row.available_stock) }} {{ row.unit }}</template></ElTableColumn>
        <ElTableColumn v-if="hasPublicSemi" label="本次可领" width="110"><template #default="{ row }">{{ issueQuantityText(row.max_issue_quantity) }} {{ row.unit }}</template></ElTableColumn>
        <ElTableColumn label="申请数量" width="150"><template #default="{ row }"><ElTooltip :visible="Boolean(quantityRuleError(row))" placement="bottom" effect="light" popper-class="material-issue-rule-tooltip" :show-after="0" :hide-after="0" :teleported="true"><template #content><span role="alert">{{ quantityRuleError(row) }}</span></template><ElInput v-model="selected[row.requirement_id]" class="quantity-input" :class="{ 'is-rule-error': Boolean(quantityRuleError(row)) }" :aria-invalid="Boolean(quantityRuleError(row))" :aria-label="`${row.material_name}半成品申请数量`" inputmode="numeric"><template #suffix>{{ row.unit }}</template></ElInput></ElTooltip></template></ElTableColumn>
        <ElTableColumn :label="hasPublicSemi ? '预计库存结余' : '预计结余'" width="130"><template #default="{ row }">{{ remainder(row) }} {{ row.unit }}</template></ElTableColumn>
        <ElTableColumn label="可用说明" min-width="160" show-overflow-tooltip><template #default="{ row }">{{ row.stock_mode === 'PUBLIC_V2' ? `公共半成品可用 ${issueQuantityText(row.available_stock)} ${row.unit}` : '按当前订单半成品库存' }}</template></ElTableColumn>
        <ElTableColumn label="操作" width="72" fixed="right"><template #default="{ row }"><ElButton link type="danger" @click="remove(row)">移除</ElButton></template></ElTableColumn>
      </ElTable>
      <div class="partition-note">管材半成品按正整数支领取，裁片按正整数套领取；<template v-if="hasPublicSemi">按本订单 BOM 部位选择，系统从匹配规格、颜色和工艺的公共合格半成品中分配；不受来源订单限制，不扣原材料根数、米数及原料额度。</template><template v-else>只扣所选订单、产品、部位、工艺及库区的合格半成品，不扣原材料根数、米数及原料额度。</template></div>
    </section>
    <AppWindowDialog v-model="visible" :title="picker === 'RAW' ? '添加原材料' : '添加外发回库半成品'" :width="1680">
      <div class="selector-content">
        <div class="selector-filters">
          <ElInput v-model="search" clearable placeholder="搜索物料、部位、规格或颜色" aria-label="搜索可领材料" />
          <ElSelect v-if="picker === 'SEMI'" v-model="processingStatus" placeholder="加工状态：全部" aria-label="加工状态筛选" clearable>
            <ElOption label="加工状态：全部" value="" />
            <ElOption v-for="status in statusOptions" :key="status" :label="status" :value="status" />
          </ElSelect>
          <ElButton v-if="picker === 'SEMI'" type="primary">查询</ElButton>
        </div>
      <ElTable :data="candidates" class="candidate-table" border max-height="540" row-key="requirement_id" empty-text="当前范围没有可领库存或材料" :row-class-name="({ row }: { row: MaterialRequirement }) => draftSelectedIds.has(row.requirement_id) ? 'is-picked' : ''">
        <template v-if="picker === 'SEMI'">
           <ElTableColumn label="部位" min-width="130" show-overflow-tooltip><template #default="{ row }"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys">{{ partNames(row) }}</BomAttributesTooltip></template></ElTableColumn>
           <ElTableColumn label="材质" min-width="120" show-overflow-tooltip><template #default="{ row }">{{ materialValue(row) }}</template></ElTableColumn>
           <ElTableColumn label="规格" min-width="165" show-overflow-tooltip><template #default="{ row }">{{ specificationValue(row) }}</template></ElTableColumn>
           <ElTableColumn label="颜色" width="90"><template #default="{ row }">{{ colorValue(row, true) }}</template></ElTableColumn>
          <ElTableColumn label="加工状态" width="110"><template #default="{ row }">{{ processingStatusLabel(row) }}</template></ElTableColumn>
          <ElTableColumn label="公共可用" width="120" align="center"><template #default="{ row }">{{ issueQuantityText(row.available_stock) }} {{ row.unit }}</template></ElTableColumn>
          <ElTableColumn label="匹配依据" min-width="190" show-overflow-tooltip><template #default> BOM部位 + 材质 + 规格 + 颜色 </template></ElTableColumn>
          <ElTableColumn label="操作" width="90" align="center"><template #default="{ row }"><ElButton size="small" :type="draftSelectedIds.has(row.requirement_id) ? 'success' : 'primary'" @click.stop="addCandidate(row)">{{ draftSelectedIds.has(row.requirement_id) ? '已添加' : '添加' }}</ElButton></template></ElTableColumn>
        </template>
        <template v-else>
          <ElTableColumn width="52" align="center" header-align="center"><template #header><ElCheckbox :model-value="draftSelectedIds.size === candidates.length && candidates.length > 0" aria-label="选择材料" @change="(value: boolean | string | number) => candidates.forEach(row => setDraftSelected(row, Boolean(value)))" @click.stop /></template><template #default="{ row }"><ElCheckbox :model-value="draftSelectedIds.has(row.requirement_id)" :aria-label="`选择${name(row)}`" @change="(value: boolean | string | number) => setDraftSelected(row, Boolean(value))" @click.stop /></template></ElTableColumn>
           <ElTableColumn label="品名" min-width="145" show-overflow-tooltip><template #default="{ row }"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys">{{ row.material_name }}</BomAttributesTooltip></template></ElTableColumn>
           <ElTableColumn label="部位" min-width="125" show-overflow-tooltip><template #default="{ row }"><BomAttributesTooltip :fields="row.bom_attributes" :hide-keys="tooltipKeys">{{ partNames(row) }}</BomAttributesTooltip></template></ElTableColumn>
           <ElTableColumn label="材质" min-width="120" show-overflow-tooltip><template #default="{ row }">{{ materialValue(row) }}</template></ElTableColumn>
           <ElTableColumn label="规格" min-width="165" show-overflow-tooltip><template #default="{ row }">{{ specificationValue(row) }}</template></ElTableColumn>
           <ElTableColumn label="颜色" width="90"><template #default="{ row }">{{ colorValue(row) }}</template></ElTableColumn>
          <ElTableColumn prop="unit" label="单位" width="70" align="center" />
          <ElTableColumn label="本订单需求" width="110" align="center"><template #default="{ row }">{{ issueQuantityText(row.required_quantity) }}</template></ElTableColumn>
          <ElTableColumn label="本订单已领取" width="120" align="center"><template #default="{ row }">{{ issueQuantityText(row.internal_issued_quantity) }}</template></ElTableColumn>
          <ElTableColumn label="本订单已外发" width="120" align="center"><template #default="{ row }">{{ issueQuantityText(row.outsourcing_issued_quantity) }}</template></ElTableColumn>
          <ElTableColumn label="本订单待审核" width="120" align="center"><template #default="{ row }">{{ row.pending_issue_quantity || '0' }}</template></ElTableColumn>
          <ElTableColumn label="本次可领" width="110" align="center"><template #default="{ row }">{{ issueQuantityText(row.max_issue_quantity) }}</template></ElTableColumn>
        </template>
      </ElTable>
      </div>
      <template #footer><span class="picker-tip">只需选择物料并填写领取数量，系统按合格可用库存自动分配。</span><ElButton type="primary" @click="completeSelection">{{ picker === 'SEMI' ? '加入本次领料' : '完成选择' }}</ElButton></template>
    </AppWindowDialog>
  </div>
</template>

<style scoped lang="scss">
.issue-partitions { display: grid; gap: 16px; }
.partition { overflow: hidden; background: #fcfaf6; border: 1px solid #ddd6c9; border-radius: 6px; }
.partition header { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; gap: 16px; }
.partition header > div { display: flex; align-items: baseline; gap: 18px; }
h2 { margin: 0; font-size: 18px; color: #2e2b25; }
.partition header span, .partition-note, .picker-tip { font-size: 12px; color: #776e60; }
.partition-note { padding: 12px 18px; background: #faf6ed; border-top: 1px solid #e5dccb; line-height: 20px; }
small { display: block; font-size: 12px; color: #81776a; line-height: 20px; }
.partition :deep(.el-table th.el-table__cell), .selector-content :deep(.el-table th.el-table__cell) { background: #f0eadf; color: #706758; height: 44px; padding: 0; font-weight: 500; }
.partition :deep(.el-table td.el-table__cell), .selector-content :deep(.candidate-table td.el-table__cell) { height: 40px; padding: 0; }
.selector-content { display: grid; gap: 12px; }
.selector-filters { display: flex; align-items: center; gap: 12px; }
.selector-filters :deep(.el-input) { width: 370px; }
.selector-filters :deep(.el-select) { width: 180px; }
.selector-filters :deep(.el-input__wrapper), .selector-filters :deep(.el-select__wrapper), .selector-filters :deep(.el-button) { min-height: 32px; height: 32px; }
.quantity-input :deep(.el-input__inner) { text-align: center; }
.quantity-input.is-rule-error :deep(.el-input__wrapper) { box-shadow: 0 0 0 1px #e5484d inset; }
.quantity-input.is-rule-error :deep(.el-input__inner) { color: #c93439; }
:global(.material-issue-rule-tooltip.el-popper.is-light) { max-width: 280px; padding: 7px 10px; border-color: #efb2b4; background: #fff2f2; color: #c93439; font-size: 12px; line-height: 18px; }
:global(.material-issue-rule-tooltip.el-popper.is-light .el-popper__arrow::before) { border-color: #efb2b4; background: #fff2f2; }
.selector-content :deep(.candidate-table .el-table__body tr.is-picked > td.el-table__cell) { background: #fff2e9; }
.selector-content :deep(.candidate-table .el-table__body tr.is-picked:hover > td.el-table__cell) { background: #f9e8dd; }
.picker-tip { margin-right: auto; }
</style>
