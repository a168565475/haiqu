<script setup lang="ts">
import { computed, ref } from 'vue'
import SampleMaterialTabs from './SampleMaterialTabs.vue'
import { sampleMaterialCategories, type SampleMaterialCategory } from '@/types/sampleMaterial'
import type { SampleWarehouseLine } from '@/types/sampleWarehouse'
import { sampleSupplyResult } from '@/utils/sampleWarehouse'
const props = defineProps<{ modelValue: SampleWarehouseLine[]; available: boolean; fullscreen: boolean; errorMessage: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [lines: SampleWarehouseLine[]]; retry: []; refresh: []; 'toggle-fullscreen': [] }>()
const category = ref<SampleMaterialCategory>('tube')
const onlyShortage = ref(false)
const counts = computed(() => props.available ? Object.fromEntries(sampleMaterialCategories.map(item => [item.key, props.modelValue.filter(line => line.category === item.key).length])) : {})
const categoryLines = computed(() => props.modelValue.filter(line => line.category === category.value))
const visibleLines = computed(() => categoryLines.value.map(line => ({ ...line, supplyResult: sampleSupplyResult(line.quantity, line.supplyQuantity) })).filter(line => !onlyShortage.value || (line.supplyResult.valid && line.supplyResult.gap !== '0')))
const categoryLabel = (value: SampleMaterialCategory) => sampleMaterialCategories.find(item => item.key === value)?.label || '—'
const labels = { full: '已满足', partial: '部分缺料', none: '无库存', pending: '待核对', invalid: '数量有误' }
function supplyChanged(key: string, value: string) { emit('update:modelValue', props.modelValue.map(line => line.key === key ? { ...line, supplyQuantity: value } : line)) }
</script>
<template>
  <section class="warehouse-comparison" :class="{ 'comparison-fullscreen': fullscreen }" aria-label="库存对比与供料">
    <header class="comparison-toolbar"><h2>仓库核对与供料</h2><p>请根据实际库存填写本次可供数量。</p><ElButton :disabled="disabled" @click="emit('refresh')">刷新库存</ElButton><ElButton @click="emit('toggle-fullscreen')">{{ fullscreen ? '退出全屏' : '全屏核对' }}</ElButton></header>
    <SampleMaterialTabs v-model="category" :counts="counts" class="warehouse-tabs"><ElCheckbox v-model="onlyShortage">仅看缺料</ElCheckbox></SampleMaterialTabs>
    <div class="comparison-table" tabindex="0" aria-label="仓库材料对照表，可横向滚动">
      <table><colgroup><col class="col-category"><col class="col-name"><col class="col-spec"><col class="col-material"><col class="col-color"><col class="col-need"><col class="col-supply"><col class="col-gap"><col class="col-unit"><col class="col-result"></colgroup>
        <thead><tr><th>材料分类</th><th>材料名称</th><th>规格</th><th>材质</th><th>颜色 / 色号</th><th>需求数量</th><th>本次可供数量 *</th><th>采购缺口</th><th>单位</th><th>核对结果</th></tr></thead>
        <tbody><tr v-for="line in visibleLines" :key="line.key"><td>{{ categoryLabel(line.category) }}</td><td :title="line.name">{{ line.name }}</td><td :title="line.specification">{{ line.specification || '—' }}</td><td :title="line.material">{{ line.material || '—' }}</td><td :title="line.color">{{ line.color || '—' }}</td><td>{{ line.quantity }}</td><td><div class="supply-field"><ElInput :model-value="line.supplyQuantity" :disabled="disabled" :aria-label="`${line.name}本次可供数量`" inputmode="decimal" placeholder="请核实后填写" @update:model-value="supplyChanged(line.key, $event)" /><span>{{ line.unitLabel }}</span></div></td><td class="shortage-cell" :class="{ 'has-shortage': line.supplyResult.valid && line.supplyResult.gap !== '0' }">{{ line.supplyResult.gap == null ? '—' : line.supplyResult.gap }}</td><td>{{ line.unitLabel || '—' }}</td><td><span class="supply-result" :class="line.supplyResult.result">{{ labels[line.supplyResult.result] }}</span></td></tr>
          <tr v-if="!visibleLines.length" class="empty-row"><td colspan="10"><p>{{ errorMessage || (onlyShortage ? '当前分区暂无缺料项。' : '当前分区暂无材料需求。') }}</p><ElButton v-if="errorMessage" @click="emit('retry')">重新加载材料需求</ElButton></td></tr>
        </tbody>
      </table>
    </div>
    <div class="comparison-summary"><span>当前分区 {{ available ? categoryLines.length : '—' }} 项 · 全部分区 {{ available ? modelValue.length : '—' }} 项</span><span>采购缺口 = 需求数量 − 本次可供数量</span></div>
  </section>
</template>
<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.warehouse-comparison { display: flex; height: 500px; flex: none; flex-direction: column; gap: 12px; min-width: 0; padding: 24px; border-radius: 5px; background: token.$crm-color-surface; box-shadow: inset 0 0 0 1px token.$crm-border-subtle; }
.comparison-toolbar { display: flex; min-height: 44px; flex: none; align-items: center; gap: 16px; }
h2 { width: auto; flex: none; margin: 0; font-family: token.$crm-font-display; font-size: 22px; line-height: 30px; }
.comparison-toolbar p { flex: 1; min-width: 0; margin: 0; }
.comparison-toolbar p { color: token.$crm-text-secondary; font-size: 12px; line-height: 22px; }
.warehouse-comparison .comparison-toolbar :deep(.el-button) { width: auto; min-width: 96px; height: 32px; flex: none; padding: 0 16px; border-radius: 5px; background: var(--erp-color-surface); font-size: 13px; }
.warehouse-tabs :deep(button) { width: 152px; flex: 0 0 152px; }
.warehouse-tabs :deep(.el-checkbox) { height: 32px; flex: none; align-items: center; color: token.$crm-text-secondary; }
.comparison-table { height: 312px; min-height: 0; overflow: auto; }
table { width: 100%; min-width: 1400px; border-spacing: 0; table-layout: fixed; }
.col-category { width: 110px; } .col-name { width: 190px; } .col-spec { width: 300px; } .col-material { width: 180px; } .col-color { width: 220px; } .col-need { width: 140px; } .col-supply { width: 260px; } .col-gap { width: 170px; } .col-unit { width: 90px; } .col-result { width: 170px; }
thead { position: sticky; z-index: 1; top: 0; background: token.$crm-color-page; }
th { height: 44px; padding: 0 16px; font-size: 12px; font-weight: 500; line-height: 18px; text-align: left; }
td { height: 34px; padding: 0 16px; overflow: hidden; border-bottom: 1px solid token.$crm-border-subtle; font-size: 12px; line-height: 18px; text-overflow: ellipsis; white-space: nowrap; }
.supply-field { display: flex; align-items: center; gap: 4px; }
.supply-field :deep(.el-input) { flex: 1; min-width: 0; }
.supply-field :deep(.el-input__wrapper) { min-height: 32px; height: 32px; padding: 1px 7px; border-radius: var(--erp-radius-control); background: var(--erp-input-surface); box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-border) inset; }
.supply-field :deep(.el-input__wrapper.is-focus) { box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-focus-border) inset; }
.shortage-cell { color: token.$crm-text-secondary; background: transparent; }
.shortage-cell.has-shortage { color: token.$crm-primary; }
.supply-result { display: inline-flex; height: 24px; align-items: center; padding: 0 10px; border-radius: 4px; color: token.$crm-neutral; background: token.$crm-color-page; font-size: 12px; line-height: 22px; white-space: nowrap; }
.full { color: token.$crm-success; background: token.$crm-success-soft; }
.partial { color: token.$crm-warning; background: token.$crm-warning-soft; }
.none, .invalid { color: token.$crm-danger; background: token.$crm-danger-soft; }
.empty-row td { height: auto; min-height: 0; padding-top: 48px; padding-bottom: 48px; color: token.$crm-text-secondary; text-align: center; }
.empty-row p { margin-bottom: 12px; }
.comparison-summary { display: flex; height: 22px; flex: none; justify-content: space-between; color: token.$crm-text-secondary; font-size: 12px; line-height: 22px; }
.comparison-fullscreen { height: 100%; }
.comparison-fullscreen .comparison-table { height: auto; flex: 1; }
</style>
