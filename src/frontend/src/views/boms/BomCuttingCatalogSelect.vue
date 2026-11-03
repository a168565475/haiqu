<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElButton, ElOption, ElSelect } from 'element-plus'
import { fetchMaterialCatalog, fetchMaterialCatalogs, fetchPublicMaterialOptions, materialCatalogError } from '@/api/materialCatalog'
import { fetchBomCatalogSelectionOptions } from '@/api/boms'
import { applyMaterialSelection } from '@/components/products/materialSelection'
import type { MaterialCatalog, MaterialCatalogSummary, MaterialSelectionInput } from '@/types/materialCatalog'
import type { BomLineInput } from '@/types/bom'

const props = defineProps<{ line: BomLineInput; refreshKey?: number }>()
const emit = defineEmits<{ selected: [catalog: MaterialCatalog]; refreshed: [catalog: MaterialCatalog] }>()
const modelValue = computed(() => props.line.material_catalog_id || '')
const selectedName = computed(() => props.line.part_name)
const names = ref<MaterialCatalogSummary[]>([])
const loading = ref(false)
const selecting = ref(false)
const error = ref('')
const keyword = ref('')
let listRequest = 0
let selectionRequest = 0
let disposed = false

async function loadNames(query = '') {
  const token = ++listRequest
  keyword.value = query
  loading.value = true
  error.value = ''
  try {
    const rows: MaterialCatalogSummary[] = []
    let pages = 1
    for (let page = 1; page <= pages; page += 1) {
      const result = await fetchMaterialCatalogs({ category: 'FABRIC_SEMI', q: query, page, page_size: 100 })
      if (disposed || token !== listRequest) return
      rows.push(...result.data)
      pages = result.meta.total_pages
    }
    names.value = rows
  } catch (issue) {
    if (!disposed && token === listRequest) error.value = materialCatalogError(issue)
  } finally {
    if (!disposed && token === listRequest) loading.value = false
  }
}

async function readCatalog(id: string, refresh = false) {
  const token = ++selectionRequest
  const line = props.line
  selecting.value = true
  error.value = ''
  try {
    const result = await fetchMaterialCatalog(id)
    if (disposed || token !== selectionRequest || line !== props.line) return
    if (result.data.category_key !== 'FABRIC_SEMI') throw new Error('请选择裁片品名。')
    const previous = line.material_selection ?? line.material_selection_snapshot
    const [options, craftOptions] = await Promise.all([
      previous?.unit_id || previous?.unit_name ? null : fetchPublicMaterialOptions({ category_key: 'FABRIC_SEMI', template_key: result.data.template_key, scope: 'BASE' }),
      previous?.completed_craft ? null : fetchBomCatalogSelectionOptions(),
    ])
    if (disposed || token !== selectionRequest || line !== props.line) return
    const unit = options?.units.find(item => item.unit_name === '套')
    const unitId = previous?.unit_id || unit?.id
    const unitName = previous?.unit_name || (previous?.unit_id ? line.unit : unit?.unit_name)
    if (!unitName) throw new Error('裁片配置暂不可用，请重试。')
    let craft = previous?.completed_craft
    if (!craft) {
      const matches = craftOptions?.crafts.filter(item => item.craft_type === 'INTERNAL' && item.code === 'CUTTING') || []
      if (matches.length !== 1) throw new Error('请在生产维护配置唯一有效的内部裁剪工艺后重试。')
      craft = { id: matches[0]!.id, craft_type: 'INTERNAL', code: matches[0]!.code }
    }
    const specification = line.specification
    const attributes = Object.fromEntries(Object.entries({
      material: line.material, width: line.fabric_width, color: line.cutting_color,
      specification: previous?.attributes.specification || specification,
    }).filter(([, value]) => value))
    const selection: MaterialSelectionInput = {
      catalog_version: result.data.updated_at, scope: 'BASE', processing_state: 'PROCESSED', semi_kind: 'CUTTING',
      attributes, completed_craft: { id: craft.id, craft_type: craft.craft_type, code: craft.code },
      ...(unitId ? { unit_id: unitId } : { unit_name: unitName }),
    }
    applyMaterialSelection(line, result.data, selection)
    line.unit = unitName
    line.specification = specification
    if (refresh) emit('refreshed', result.data)
    else emit('selected', result.data)
  } catch (issue) {
    if (!disposed && token === selectionRequest && line === props.line) error.value = materialCatalogError(issue)
  } finally {
    if (!disposed && token === selectionRequest) selecting.value = false
  }
}

function choose(value: unknown) {
  if (typeof value === 'string') void readCatalog(value)
}

async function reload() {
  const selectedId = modelValue.value
  const activeRequest = selectionRequest
  await loadNames(keyword.value)
  if (!disposed && !error.value && selectedId && modelValue.value === selectedId && selectionRequest === activeRequest) await readCatalog(selectedId, true)
}
watch(() => props.refreshKey, reload)
onMounted(() => loadNames())
onBeforeUnmount(() => { disposed = true; ++listRequest; ++selectionRequest })
</script>

<template>
  <div>
    <ElSelect :model-value="modelValue || ''" filterable remote :remote-method="loadNames"
      :loading="loading || selecting" :disabled="selecting || !!error" placeholder="选择裁片品名"
      aria-label="裁片品名" no-data-text="暂无裁片品名，请到维护配置新增" @change="choose">
      <ElOption v-if="modelValue && !names.some(item => item.id === modelValue)" :value="modelValue" :label="selectedName" disabled />
      <ElOption v-for="item in names" :key="item.id" :value="item.id" :label="item.name" />
    </ElSelect>
    <small v-if="error" role="alert">{{ error }} <ElButton link size="small" @click="reload">重试</ElButton></small>
  </div>
</template>
