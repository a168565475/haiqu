<script setup lang="ts">
import { computed, ref } from 'vue'
import { sampleMaterialCategories, type SampleMaterialCategory } from '@/types/sampleMaterial'
import type { SampleWarehouseLine } from '@/types/sampleWarehouse'
import { sampleSupplyResult } from '@/utils/sampleWarehouse'
const props = defineProps<{ modelValue: SampleWarehouseLine[]; available: boolean; fullscreen: boolean; errorMessage: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [lines: SampleWarehouseLine[]]; retry: []; lookup: [lineKey: string] }>()
const category = ref<'all' | SampleMaterialCategory>('all')
const onlyShortage = ref(false)
const counts = computed(() => props.available ? Object.fromEntries(sampleMaterialCategories.map(item => [item.key, props.modelValue.filter(line => line.category === item.key).length])) : {})
const categoryLines = computed(() => category.value === 'all' ? props.modelValue : props.modelValue.filter(line => line.category === category.value))
const visibleLines = computed(() => categoryLines.value.map(line => ({ ...line, supplyResult: sampleSupplyResult(line.quantity, line.supplyQuantity) })).filter(line => !onlyShortage.value || (line.supplyResult.valid && line.supplyResult.gap !== '0')))
const categoryLabel = (value: SampleMaterialCategory) => sampleMaterialCategories.find(item => item.key === value)?.label || '—'
const labels = { full: '已满足', partial: '部分缺料', none: '无库存', pending: '待核对', invalid: '数量有误' }

</script>
<template>
  <section class="warehouse-comparison" :class="{ 'comparison-fullscreen': fullscreen }" aria-label="库存对比与供料">
    <header class="comparison-toolbar"><h2>仓库核对与供料</h2><div class="comparison-actions"><ElButton :disabled="disabled" @click="emit('lookup', '')">查询库存</ElButton></div></header>
    <nav class="warehouse-tabs" aria-label="材料分区">
      <button type="button" :aria-pressed="category === 'all'" :class="{ active: category === 'all' }" @click="category = 'all'">全部 {{ available ? modelValue.length : '—' }}</button>
      <button v-for="item in sampleMaterialCategories" :key="item.key" type="button" :aria-pressed="category === item.key" :class="{ active: category === item.key }" @click="category = item.key">{{ item.label }} {{ counts[item.key] ?? '—' }}</button>
      <ElCheckbox v-model="onlyShortage">仅看缺料</ElCheckbox>
    </nav>
    <div class="comparison-table" tabindex="0" aria-label="仓库材料对照表，可横向滚动">
      <table class="erp-table-editor"><colgroup><col class="col-category"><col class="col-name"><col class="col-spec"><col class="col-material"><col class="col-color"><col class="col-need"><col class="col-supply"><col class="col-gap"><col class="col-unit"><col class="col-result"></colgroup>
        <thead><tr><th>材料分类</th><th>材料名称</th><th>规格</th><th>材质</th><th>颜色 / 色号</th><th>需求数量</th><th>本次可供数量 *</th><th>采购缺口</th><th>单位</th><th>核对结果</th></tr></thead>
        <tbody><tr v-for="line in visibleLines" :key="line.key"><td>{{ categoryLabel(line.category) }}</td><td><button type="button" class="material-inventory-link" :aria-label="`${line.name} ${line.specification} 查看库存`" :title="`${line.name}：查看库存`" @click="emit('lookup', line.key)">{{ line.name }}</button></td><td :title="line.specification">{{ line.specification || '—' }}</td><td :title="line.material">{{ line.material || '—' }}</td><td :title="line.color">{{ line.color || '—' }}</td><td>{{ line.quantity }}</td><td><div class="supply-field"><ElInput :model-value="line.supplyQuantity" disabled :aria-label="`${line.name}本次可供数量`" inputmode="decimal" placeholder="查询库存后回填" /><span>{{ line.unitLabel }}</span></div></td><td class="shortage-cell" :class="{ 'has-shortage': line.supplyResult.valid && line.supplyResult.gap !== '0' }">{{ line.supplyResult.gap == null ? '—' : line.supplyResult.gap }}</td><td>{{ line.unitLabel || '—' }}</td><td><span class="supply-result" :class="line.supplyResult.result">{{ line.inventoryAllocations?.length ? '已关联 ' + line.inventoryAllocations.length + ' 处' : labels[line.supplyResult.result] }}</span></td></tr>
          <tr v-if="!visibleLines.length" class="empty-row"><td colspan="10"><p>{{ errorMessage || (onlyShortage ? '当前分区暂无缺料项。' : '当前分区暂无材料需求。') }}</p><ElButton v-if="errorMessage" @click="emit('retry')">重新加载材料需求</ElButton></td></tr>
        </tbody>
      </table>
    </div>
    <div class="comparison-summary"><span>当前分区 {{ available ? categoryLines.length : '—' }} 项 · 全部分区 {{ available ? modelValue.length : '—' }} 项</span><span>采购缺口 = 需求数量 − 本次可供数量</span></div>
  </section>
</template>
<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/theme/detail';
.warehouse-comparison { @include detail.surface; display: flex; flex: none; flex-direction: column; min-width: 0; padding: var(--erp-list-card-padding); }
.comparison-toolbar { display: flex; min-height: 30px; flex: none; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 4px; }
h2 { margin: 0; font-family: token.$crm-font-body; font-size: 18px; font-weight: 700; line-height: 26px; }
.comparison-actions { display: flex; flex: none; gap: 10px; }
.warehouse-comparison .comparison-toolbar :deep(.el-button) { width: auto; min-width: 96px; height: 32px; flex: none; padding: 0 16px; border-radius: 5px; background: var(--erp-color-surface); font-size: 13px; }
.warehouse-tabs { display: flex; height: 40px; flex: none; gap: 22px; border-bottom: 1px solid token.$crm-border-subtle; }
.warehouse-tabs button { height: 40px; flex: none; padding: 0 2px; border: 0; border-bottom: 2px solid transparent; color: token.$crm-text-secondary; background: transparent; font: inherit; font-size: 13px; cursor: pointer; }
.warehouse-tabs button.active { border-bottom-color: token.$crm-primary; color: token.$crm-primary; font-weight: 600; }
.warehouse-tabs button:hover { background: token.$crm-color-page; }
.warehouse-tabs button:focus-visible { border-radius: 2px; outline: 2px solid token.$crm-focus; outline-offset: 2px; }
.warehouse-tabs :deep(.el-checkbox) { height: 40px; flex: none; align-items: center; margin-left: auto; color: token.$crm-text-secondary; }
.comparison-table { min-height: 0; overflow: auto; border: 1px solid var(--erp-table-frame-border); border-radius: 5px; background: var(--erp-table-background); }
table { width: 100%; min-width: 1300px; border-collapse: collapse; table-layout: fixed; }
.col-category { width: 96px; } .col-name { width: 148px; } .col-spec { width: 220px; } .col-material { width: 118px; } .col-color { width: 180px; } .col-need { width: 92px; } .col-supply { width: 170px; } .col-gap { width: 92px; } .col-unit { width: 62px; } .col-result { width: 110px; }
thead { position: sticky; z-index: 1; top: 0; background: var(--erp-table-header-background); }
// 表格使用专用主题色与规范密度，避免旧工作区样式覆盖。
.warehouse-comparison .comparison-table table th { height: 44px; padding: 0 16px !important; border-bottom: 1px solid var(--erp-table-border); color: var(--erp-table-header-text); background: var(--erp-table-header-background); font-size: 12px; font-weight: 500; line-height: 18px; text-align: left; white-space: nowrap; }
.warehouse-comparison .comparison-table table td { height: 34px; padding: 0 16px !important; overflow: hidden; border-bottom: 1px solid var(--erp-table-border); color: var(--erp-table-text); background: var(--erp-table-background); font-size: 12px; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.warehouse-comparison .comparison-table table tbody tr:last-child td { border-bottom: 0; }
.warehouse-comparison .comparison-table table td:nth-child(2) { font-size: 13px; font-weight: 500; line-height: 20px; }
.warehouse-comparison .comparison-table table tbody tr:not(.empty-row):hover td { background: var(--erp-table-hover); }
.material-inventory-link { display: inline-flex; padding: 0; border: 0; border-radius: 0; color: token.$crm-primary; background: transparent; font: inherit; cursor: pointer; }
.material-inventory-link:hover { color: token.$crm-primary-hover; text-decoration: underline; text-underline-offset: 3px; }
.material-inventory-link:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 2px; }
.supply-field { display: flex; align-items: center; gap: 4px; }
.supply-field :deep(.el-input) { flex: 1; min-width: 0; }
.supply-field :deep(.el-input__wrapper) { min-height: 32px; height: 32px; padding: 1px 7px; border-radius: var(--erp-radius-control); background: var(--erp-input-surface); box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-border) inset; }
.supply-field :deep(.el-input__wrapper.is-focus) { box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-focus-border) inset; }
.warehouse-comparison .comparison-table table .shortage-cell.has-shortage { color: token.$crm-primary; }
.supply-result { display: inline-flex; height: 24px; align-items: center; padding: 0 10px; border-radius: 4px; color: token.$crm-neutral; background: token.$crm-color-page; font-size: 12px; line-height: 22px; white-space: nowrap; }
.full { color: token.$crm-success; background: token.$crm-success-soft; }
.partial { color: token.$crm-warning; background: token.$crm-warning-soft; }
.none, .invalid { color: token.$crm-danger; background: token.$crm-danger-soft; }
.warehouse-comparison .comparison-table table .empty-row td { height: auto; min-height: 0; padding: 48px 16px !important; text-align: center; }
.empty-row p { margin-bottom: 12px; }
.comparison-summary { display: flex; flex: none; flex-wrap: wrap; justify-content: space-between; gap: 8px 16px; margin: 14px 0 10px; color: token.$crm-text-secondary; font-size: 13px; line-height: 20px; }
.comparison-fullscreen { height: 100%; min-height: 0; }
.comparison-fullscreen .comparison-table { height: auto; flex: 1; }
@media (max-width: 800px) {
  .comparison-toolbar { flex-wrap: wrap; }
  .warehouse-tabs { height: auto; flex-wrap: wrap; gap: 0 22px; }
}
</style>
