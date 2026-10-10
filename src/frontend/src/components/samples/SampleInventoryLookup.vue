<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { ref, watch } from 'vue'
import { fetchSampleInventoryCandidates } from '@/api/sampleWarehouse'
import type { MaterialInventoryRow } from '@/types/inventory'
const props = defineProps<{ keyword: string; modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [open: boolean] }>()
const page = ref(1), count = ref(0), loading = ref(false)
const rows = ref<MaterialInventoryRow[]>([])
const errorMessage = ref('')
let requestNumber = 0
async function load() {
  const request = ++requestNumber
  loading.value = true
  errorMessage.value = ''
  rows.value = []
  try {
    const result = await fetchSampleInventoryCandidates(props.keyword, page.value)
    if (request === requestNumber) { rows.value = result.results; count.value = result.count }
  } catch { if (request === requestNumber) errorMessage.value = '库存查询失败或没有查看权限，请重试。' }
  finally { if (request === requestNumber) loading.value = false }
}
watch(() => [props.modelValue, props.keyword], () => {
  if (props.modelValue) { page.value = 1; void load() }
  else { requestNumber++; loading.value = false }
})
</script>
<template>
  <ElDialog :model-value="modelValue" title="查看材料库存" width="960px" class="sample-inventory-lookup" append-to-body @update:model-value="emit('update:modelValue', $event)">
    <p>“{{ keyword }}”库存查询结果。数量为已验收入库汇总，实际可供数量需仓库核实。</p>
    <div v-if="errorMessage" role="alert">{{ errorMessage }} <ElButton @click="load">重试</ElButton></div>
    <ElTable v-else v-loading="loading" :data="rows" height="390" empty-text="没有查询到库存记录；请核实名称、规格及仓库范围。"><ElTableColumn prop="material" label="材料" width="130" show-overflow-tooltip /><ElTableColumn prop="specification" label="规格" width="210" show-overflow-tooltip /><ElTableColumn prop="raw_material" label="材质" width="120" show-overflow-tooltip /><ElTableColumn prop="warehouse_name" label="仓库" width="140" show-overflow-tooltip /><ElTableColumn prop="zone_name" label="库区" width="110" show-overflow-tooltip /><ElTableColumn prop="inventory_quantity" label="参考数量" width="120" /><ElTableColumn prop="unit" label="单位" width="70" /></ElTable>
    <ElPagination v-if="!errorMessage" v-model:current-page="page" :page-size="50" :total="count" layout="total, prev, pager, next" @current-change="load" />
  </ElDialog>
</template>
<style lang="scss">
@use '@/styles/crm/tokens' as token;
.sample-inventory-lookup { --el-color-primary: #{token.$crm-primary}; --el-bg-color: #{token.$crm-color-surface}; max-width: calc(100vw - 48px); color: token.$crm-text-primary; font-family: token.$crm-font-body;
  p { color: token.$crm-text-secondary; font-size: 13px; }
  .el-pagination { justify-content: flex-end; margin-top: 16px; }
  .el-table { --el-table-header-bg-color: #{token.$crm-color-page}; --el-table-tr-bg-color: #{token.$crm-color-surface}; --el-table-border-color: #{token.$crm-border-subtle}; }
}
</style>
