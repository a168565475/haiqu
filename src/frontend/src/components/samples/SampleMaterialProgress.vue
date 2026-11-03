<script setup lang="ts">
import { ref, watch } from 'vue'
import { fetchSampleMaterials } from '@/api/sampleMaterials'
import type { SampleMaterialProgress } from '@/types/sampleMaterial'
import { materialAttributeFields } from '@/utils/materialAttributes'
import SampleSection from './SampleSection.vue'
import SampleStatusTag from './SampleStatusTag.vue'
const props = defineProps<{ sampleId: string; version?: string }>()
const progress = ref<SampleMaterialProgress | null>(null)
const hoveredRowKey = ref('')
const error = ref(''), loading = ref(false)
let generation = 0
function handleCellMouseEnter(row: SampleMaterialProgress['lines'][number]) {
  hoveredRowKey.value = row.key
}
async function load() {
  const current = ++generation
  loading.value = true; error.value = ''; progress.value = null
  try {
    const result = await fetchSampleMaterials(props.sampleId)
    if (current !== generation) return
    if (result.available) progress.value = result.progress || null
    else error.value = result.reason
  } catch { if (current === generation) error.value = '材料到货进度加载失败，请重试。' }
  finally { if (current === generation) loading.value = false }
}
watch(() => [props.sampleId, props.version], load, { immediate: true })
</script>
<template>
  <SampleSection v-loading="loading" class="sample-material-progress" title="用料需求与到货">
    <template #actions><SampleStatusTag v-if="progress" :status="progress.status" :label="progress.label" /></template>
    <p v-if="error" role="alert">{{ error }} <ElButton link @click="load">重试</ElButton></p>
    <template v-else-if="progress">
      <p v-if="progress.label === '无需用料'">打样部已确认无需用料，可进行生产和参数上传。</p>
      <ElTable v-else-if="progress.lines.length" :data="progress.lines" row-key="key" size="small" @cell-mouse-enter="handleCellMouseEnter" @mouseleave="hoveredRowKey = ''">
        <ElTableColumn prop="name" label="材料名称" min-width="120" />
        <ElTableColumn prop="specification" label="规格" min-width="110"><template #default="{ row }"><ElTooltip placement="top" :show-after="80" :visible="hoveredRowKey === row.key" :teleported="true"><template #content><div class="material-attribute-tooltip"><div v-for="field in materialAttributeFields({ ...row, part_name: row.name })" :key="field.key"><span>{{ field.label }}</span><strong>{{ field.value }}</strong></div></div></template><span>{{ row.specification }}</span></ElTooltip></template></ElTableColumn>
        <ElTableColumn prop="material" label="材质" min-width="80" />
        <ElTableColumn prop="color" label="颜色 / 色卡 / 色号" min-width="130" />
        <ElTableColumn prop="quantity" label="需求数量" width="90" />
        <ElTableColumn prop="supplyQuantity" label="仓库供料" width="90" />
        <ElTableColumn prop="arrivedQuantity" label="采购已入库" width="100" />
        <ElTableColumn prop="remainingQuantity" label="采购剩余缺口" width="110" />
        <ElTableColumn label="实际领料" width="90"><template #default="{ row }">{{ row.issuedQuantity ?? '—' }}</template></ElTableColumn>
        <ElTableColumn label="领料后缺口" width="100"><template #default="{ row }">{{ row.shortageQuantity ?? '—' }}</template></ElTableColumn>
        <ElTableColumn prop="unitLabel" label="单位" width="65" />
      </ElTable>
      <p v-else>尚未提交用料需求。</p>
      <p v-if="progress.status === 'PROCUREMENT_PENDING'" class="progress-note">采购仍可继续接收入库；材料到货后由打样部发起领料。</p>
      <p v-else-if="progress.status === 'MATERIAL_ISSUE_PENDING'" class="progress-note">材料已有可供数量，请发起样品领料。</p>
      <p v-else-if="progress.status === 'MATERIAL_ISSUE_REVIEW'" class="progress-note">打样部已发起领料，等待仓库确认实际领料数量。</p>
      <p v-else-if="progress.status === 'MATERIALS_ISSUED'" class="progress-note">已记录实际领料数量，不足部分不补料。</p>
    </template>
  </SampleSection>
</template>
<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.sample-material-progress {
  min-width: 0;
  margin-bottom: 16px;
  p { font-size: 13px; color: token.$crm-text-secondary; }
  :deep(.el-table) {
    --el-table-bg-color: #{token.$crm-color-surface};
    --el-table-tr-bg-color: #{token.$crm-color-surface};
    --el-table-header-bg-color: #{token.$crm-color-page};
    --el-table-border-color: #{token.$crm-border-subtle};
    --el-table-text-color: #{token.$crm-text-primary};
    --el-table-header-text-color: #{token.$crm-text-secondary};
    --el-table-row-hover-bg-color: #{token.$crm-color-row-hover};
    font-family: token.$crm-font-body;
    font-size: 13px;
    th.el-table__cell { height: 44px; font-weight: 500; }
    td.el-table__cell { height: 52px; }
  }
}
.progress-note { margin: 12px 0 0; }
.material-attribute-tooltip { min-width: 180px; line-height: 24px; font-size: 14px; }
.material-attribute-tooltip > div { display: flex; gap: 8px; }
.material-attribute-tooltip span { color: var(--erp-color-text-secondary); min-width: 42px; }
</style>
