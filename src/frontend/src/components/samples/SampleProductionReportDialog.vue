<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { reportSampleProduction } from '@/api/samples'
import { sampleMaterialError } from '@/utils/sampleMaterial'
import type { SampleDetail, SampleProductionReportItem } from '@/types/sample'
const props = defineProps<{ modelValue: boolean; sample: SampleDetail; etag: string }>()
const emit = defineEmits<{ 'update:modelValue': [boolean]; saved: [SampleDetail, string] }>()
const rows = ref<Required<SampleProductionReportItem>[]>([])
const saving = ref(false), error = ref('')
const metalAllowed = computed(() => props.sample.workflow_actions?.can_report_metalwork ?? true)
const cuttingAllowed = computed(() => props.sample.workflow_actions?.can_report_cutting ?? true)
watch(() => props.modelValue, value => {
  if (!value) return
  error.value = ''
  rows.value = props.sample.items.map(item => ({ id: item.id,
    metalwork_reported_quantity: item.metalwork_reported_quantity || 0,
    cutting_reported_quantity: item.cutting_reported_quantity || 0,
    metalwork_completed: Boolean(item.metalwork_completed), cutting_completed: Boolean(item.cutting_completed) }))
})
async function save() {
  if (saving.value) return
  if (rows.value.some((row, index) => [row.metalwork_reported_quantity, row.cutting_reported_quantity].some(q => !Number.isInteger(q) || q < 0 || q > (props.sample.items[index]?.sample_quantity || 0)))) {
    error.value = '报工数量须为 0 到打样数量之间的整数。'; return
  }
  if (rows.value.some(row => (metalAllowed.value && row.metalwork_completed && row.metalwork_reported_quantity <= 0)
    || (cuttingAllowed.value && row.cutting_completed && row.cutting_reported_quantity <= 0))) {
    error.value = '工序标记完成时，报工数量必须大于 0。'; return
  }
  saving.value = true; error.value = ''
  try {
    const payload = rows.value.map(row => ({ id: row.id,
      ...(metalAllowed.value ? { metalwork_reported_quantity: row.metalwork_reported_quantity, metalwork_completed: row.metalwork_completed } : {}),
      ...(cuttingAllowed.value ? { cutting_reported_quantity: row.cutting_reported_quantity, cutting_completed: row.cutting_completed } : {}),
    }))
    const result = await reportSampleProduction(props.sample.id, props.etag, payload)
    emit('saved', result.data, result.etag); emit('update:modelValue', false); ElMessage.success('报工已保存。')
  } catch (cause) { error.value = sampleMaterialError(cause) }
  finally { saving.value = false }
}
</script>
<template>
  <ElDialog :model-value="modelValue" title="生产报工" width="900px" align-center append-to-body :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" class="sample-production-dialog" @update:model-value="!saving && emit('update:modelValue', $event)">
    <p>参数上传仅交付资料；请按实际生产情况填写数量并确认工序完成。</p>
    <ElTable :data="rows">
      <ElTableColumn label="样品 / 规格" min-width="190"><template #default="{ $index }">{{ sample.items[$index]?.product_description_snapshot }}<small>{{ sample.items[$index]?.specification_snapshot }}</small></template></ElTableColumn>
      <ElTableColumn label="打样数量" width="90"><template #default="{ $index }">{{ sample.items[$index]?.sample_quantity }} PCS</template></ElTableColumn>
      <ElTableColumn label="金工报工" width="150"><template #default="{ row, $index }"><ElInputNumber v-model="row.metalwork_reported_quantity" aria-label="金工报工数量" :min="0" :max="sample.items[$index]?.sample_quantity || 0" :precision="0" :disabled="saving || !metalAllowed" /></template></ElTableColumn>
      <ElTableColumn label="金工完成" width="90"><template #default="{ row }"><ElCheckbox v-model="row.metalwork_completed" aria-label="金工完成" :disabled="saving || !metalAllowed" /></template></ElTableColumn>
      <ElTableColumn label="裁剪报工" width="150"><template #default="{ row, $index }"><ElInputNumber v-model="row.cutting_reported_quantity" aria-label="裁剪报工数量" :min="0" :max="sample.items[$index]?.sample_quantity || 0" :precision="0" :disabled="saving || !cuttingAllowed" /></template></ElTableColumn>
      <ElTableColumn label="裁剪完成" width="90"><template #default="{ row }"><ElCheckbox v-model="row.cutting_completed" aria-label="裁剪完成" :disabled="saving || !cuttingAllowed" /></template></ElTableColumn>
    </ElTable>
    <p v-if="error" role="alert" class="report-error">{{ error }}</p>
    <template #footer><ElButton :disabled="saving" @click="emit('update:modelValue', false)">取消</ElButton><ElButton type="primary" :loading="saving" @click="save">保存报工</ElButton></template>
  </ElDialog>
</template>
<style lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/crm/sample-dialog' as sample;
.sample-production-dialog {
  @include sample.dialog;
  p { font-size: 13px; }
  small { display: block; color: token.$crm-text-secondary; }
  .el-input-number { width: 125px; }
  .el-table {
    --el-table-bg-color: #{token.$crm-color-surface};
    --el-table-tr-bg-color: #{token.$crm-color-surface};
    --el-table-header-bg-color: #{token.$crm-color-subtle};
    --el-table-border-color: #{token.$crm-border-subtle};
    --el-table-text-color: #{token.$crm-text-primary};
    --el-table-header-text-color: #{token.$crm-text-secondary};
    --el-table-row-hover-bg-color: #{token.$crm-color-row-hover};
    font-size: 13px;
    th.el-table__cell { height: 44px; }
    td.el-table__cell { height: 64px; }
  }
  .report-error { color: token.$crm-danger; }
}
</style>
