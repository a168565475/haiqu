<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, ref, watch } from 'vue'
import { fetchSampleMaterialCandidates } from '@/api/sampleMaterials'
import { sampleMaterialError } from '@/utils/sampleMaterial'
import type { SampleMaterialCandidate, SampleMaterialCategory, SampleMaterialReferences, SampleMaterialUnit } from '@/types/sampleMaterial'
const props = defineProps<{ modelValue: boolean; category: SampleMaterialCategory; references: SampleMaterialReferences | null; units: SampleMaterialUnit[]; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; choose: [items: SampleMaterialCandidate[]] }>()
const keyword = ref(''), productName = ref(''), page = ref(1), total = ref(0), loading = ref(false), error = ref('')
const productNames = computed(() => props.references?.catalogNames?.[props.category] || [])
const candidates = ref<SampleMaterialCandidate[]>([])
const selected = ref<Record<string, SampleMaterialCandidate>>({})
let requestId = 0
const selectedCount = computed(() => Object.keys(selected.value).length)
async function load() {
  const request = ++requestId
  loading.value = true
  error.value = ''
  try {
    const result = await fetchSampleMaterialCandidates(props.category, keyword.value.trim(), page.value, productName.value)
    if (request !== requestId) return
    candidates.value = result.data
    total.value = result.meta.total
  } catch (reason) { if (request === requestId) { candidates.value = []; error.value = sampleMaterialError(reason) } }
  finally { if (request === requestId) loading.value = false }
}
function toggle(row: SampleMaterialCandidate) {
  if (props.disabled) return
  if (selected.value[row.id]) delete selected.value[row.id]
  else selected.value[row.id] = row
}
function search() { page.value = 1; void load() }
function confirm() { if (props.disabled || loading.value || !selectedCount.value) return; emit('choose', Object.values(selected.value)); emit('update:modelValue', false) }
watch(() => props.modelValue, visible => {
  if (visible) { selected.value = {}; keyword.value = ''; productName.value = ''; page.value = 1; void load() }
  else requestId++
})
</script>
<template>
  <ElDialog :model-value="modelValue" class="sample-material-picker-dialog" title="选择材料数据" width="1100px" append-to-body :close-on-click-modal="false" @update:model-value="emit('update:modelValue', $event)">
    <div class="material-picker">
      <form class="picker-search" @submit.prevent="search"><ElSelect v-model="productName" aria-label="按品名分组" filterable clearable placeholder="全部品名" @change="search"><ElOption v-for="name in productNames" :key="name" :label="name" :value="name" /></ElSelect><ElInput v-model="keyword" aria-label="搜索材料" maxlength="100" clearable placeholder="搜索品号、规格、材质或颜色" /><ElButton native-type="submit" :loading="loading">查询</ElButton><span>已选 {{ selectedCount }} 项</span></form>
      <div v-if="error" role="alert" class="picker-error">{{ error }} <ElButton link @click="load">重试</ElButton></div>
      <ElTable v-loading="loading" :data="candidates" height="440" row-key="id" @row-click="toggle">
        <ElTableColumn width="48"><template #default="{ row }"><span @click.stop><ElCheckbox :model-value="Boolean(selected[row.id])" :aria-label="`选择${row.name} ${row.specification}`" :disabled="disabled" @change="toggle(row)" /></span></template></ElTableColumn>
        <ElTableColumn prop="number" label="品号" width="140" show-overflow-tooltip />
        <ElTableColumn prop="name" label="材料名称" min-width="160" show-overflow-tooltip />
        <ElTableColumn prop="specification" label="规格" min-width="240" show-overflow-tooltip />
        <ElTableColumn prop="material" label="材质" width="150" show-overflow-tooltip />
        <ElTableColumn prop="color" label="颜色" width="130" show-overflow-tooltip />
        <ElTableColumn prop="unitLabel" label="单位" width="80" />
      </ElTable>
      <div class="picker-pagination"><span>选入后填写本次打样需求数量</span><ElPagination v-model:current-page="page" :page-size="50" :total="total" layout="total, prev, pager, next" @current-change="load" /></div>
    </div>
    <template #footer><ElButton @click="emit('update:modelValue', false)">取消</ElButton><ElButton type="primary" :disabled="disabled || loading || !selectedCount" @click="confirm">添加所选（{{ selectedCount }}）</ElButton></template>
  </ElDialog>
</template>
<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.material-picker :deep(.el-table) { --el-table-header-bg-color: #{token.$crm-color-page}; --el-table-tr-bg-color: #{token.$crm-color-surface}; --el-table-border-color: #{token.$crm-border-subtle}; --el-table-row-hover-bg-color: #{token.$crm-color-row-hover}; }
.material-picker { display: grid; gap: 16px; }
.picker-search, .picker-pagination { display: flex; align-items: center; gap: 12px; }
.picker-search .el-select { width: 260px; }
.picker-search .el-input { width: 380px; }
.picker-search > span, .picker-pagination > span { color: token.$crm-text-secondary; font-size: 12px; }
.picker-pagination { justify-content: space-between; }
.picker-error { color: token.$crm-danger; }
</style>
