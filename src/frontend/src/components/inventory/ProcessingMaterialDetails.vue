<script setup lang="ts">
import { computed } from 'vue'
import { ElPopover } from 'element-plus'
import type { MaterialSelectionSnapshot } from '@/types/materialCatalog'
import type { ProcessingMaterialPair } from '@/types/processingMaterial'

const props = defineProps<{ materials: ProcessingMaterialPair }>()
const stages: Record<string, string> = {
  RAW: '原料', METAL: '金工完成', POWDER_COATING: '喷塑完成', CUTTING: '裁剪完成',
  SEWING: '车缝完成', SCREEN_PRINTING: '丝印完成', EMBROIDERY: '刺绣完成',
}
const labels: Record<string, string> = {
  material: '材质', color: '颜色', shape: '形状', section_size: '规格', thickness: '厚度', hardness: '硬度', length: '长度',
  fabric_spec: '面料规格', width: '门幅', size: '尺寸', model: '型号', process: '工艺版本', specification: '规格',
}
const rows = computed(() => [
  { label: '部位 / 裁片档案', value: props.materials.component_material_selection_snapshot },
  { label: '投入材料', value: props.materials.input_material_selection_snapshot },
  { label: '产出材料', value: props.materials.output_material_selection_snapshot },
].filter((item): item is { label: string; value: MaterialSelectionSnapshot } => Boolean(item.value?.catalog_id))
  .map(row => row.label === '部位 / 裁片档案' ? { ...row, value: { ...row.value,
    attributes: Object.fromEntries(Object.entries(row.value.attributes).filter(([key]) => !['material', 'color', 'fabric_spec', 'width'].includes(key))),
  } } : row))
const sources = computed(() => props.materials.component_source_materials || [])
</script>

<template>
  <ElPopover v-if="rows.length || sources.length" :trigger="['hover', 'focus']" placement="right-start" :width="360" :popper-style="{ maxWidth: 'calc(100vw - 32px)' }">
    <template #reference><span tabindex="0" class="processing-material-trigger"><slot /></span></template>
    <div class="processing-material-details">
    <div v-for="(source, index) in sources" :key="source.source_bom_line_id || index" class="material-stage material-source">
      <strong>来源布料：{{ source.name || '品名未记录' }}</strong>
      <dl><dt>材质</dt><dd>{{ source.material || '未记录' }}</dd><dt>颜色</dt><dd>{{ source.color || '未记录' }}</dd>
        <dt>色号</dt><dd>{{ source.color_code || '未记录' }}</dd><dt>面料规格</dt><dd>{{ source.fabric_spec || '未记录' }}</dd>
        <dt>门幅</dt><dd>{{ source.width || '未记录' }}</dd><dt>单位</dt><dd>{{ source.unit || '未记录' }}</dd></dl>
    </div>
    <div v-for="row in rows" :key="row.label" class="material-stage">
      <strong>{{ row.label }}：{{ row.value.name }}</strong>
      <span>{{ row.value.processing_stage ? `${stages[row.value.processing_stage] || row.value.processing_stage} · ` : '' }}{{ row.value.unit_name }}</span>
      <dl><template v-for="(value, key) in row.value.attributes" :key="key"><dt>{{ labels[key] || key }}</dt><dd>{{ value }}</dd></template></dl>
    </div>
    </div>
  </ElPopover>
  <slot v-else />
</template>

<style scoped>
.processing-material-trigger { display: inline-block; max-width: 100%; vertical-align: middle; cursor: help; }
.processing-material-details { font-size: 12px; line-height: 1.5; text-align: left; white-space: normal; overflow-wrap: anywhere; }
.material-stage { display: grid; gap: 4px; margin-top: 8px; }
.material-stage > span { color: var(--el-text-color-secondary); }
dl { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 2px 8px; margin: 0; }
dt { color: var(--el-text-color-secondary); }
dd { margin: 0; }
</style>
