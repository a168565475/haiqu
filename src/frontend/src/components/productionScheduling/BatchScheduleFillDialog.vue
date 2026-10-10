<script setup lang="ts">
import { computed, reactive, watch } from 'vue'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { ScheduleCraftOption, ScheduleWriteItem } from '@/types/productionScheduling'

const props = defineProps<{ modelValue: boolean; crafts: ScheduleCraftOption[]; selectedCount: number }>()
type BatchFillValue = Partial<ScheduleWriteItem> & { internal_craft_ids?: string[]; external_craft_ids?: string[] }
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; apply: [value: BatchFillValue] }>()
const form = reactive({
  material_inbound_date: '', metal_return_date: '', sewing_return_date: '', finished_inbound_date: '',
  internal_craft_ids: [] as string[], external_craft_ids: [] as string[],
})
const internalCrafts = computed(() => props.crafts.filter(item => item.craft_type === 'INTERNAL'))
const externalCrafts = computed(() => props.crafts.filter(item => item.craft_type === 'EXTERNAL'))
watch(() => props.modelValue, (visible) => { if (visible) Object.assign(form, { material_inbound_date: '', metal_return_date: '', sewing_return_date: '', finished_inbound_date: '', internal_craft_ids: [], external_craft_ids: [] }) })
function apply() {
  const value: BatchFillValue = {}
  if (form.material_inbound_date) value.material_inbound_date = form.material_inbound_date
  if (form.metal_return_date) value.metal_return_date = form.metal_return_date
  if (form.sewing_return_date) value.sewing_return_date = form.sewing_return_date
  if (form.finished_inbound_date) value.finished_inbound_date = form.finished_inbound_date
  if (form.internal_craft_ids.length) value.internal_craft_ids = [...form.internal_craft_ids]
  if (form.external_craft_ids.length) value.external_craft_ids = [...form.external_craft_ids]
  emit('apply', value)
  emit('update:modelValue', false)
}
</script>

<template>
  <AppWindowDialog :model-value="modelValue" :title="`批量填入（已选择 ${selectedCount} 项）`" :width="700" :height="496" destroy-on-close class="schedule-batch-dialog" @update:model-value="emit('update:modelValue', $event)">
    <div class="batch-grid">
      <label><span>材料入库时间</span><ElDatePicker v-model="form.material_inbound_date" value-format="YYYY-MM-DD" placeholder="选择日期" /></label>
      <label><span>金工回货时间</span><ElDatePicker v-model="form.metal_return_date" value-format="YYYY-MM-DD" placeholder="选择日期" /></label>
      <label><span>车缝回货时间</span><ElDatePicker v-model="form.sewing_return_date" value-format="YYYY-MM-DD" placeholder="选择日期" /></label>
      <label><span>成品入库时间</span><ElDatePicker v-model="form.finished_inbound_date" value-format="YYYY-MM-DD" placeholder="选择日期" /></label>
      <label class="batch-grid__craft"><span>厂内工艺</span><ElSelect v-model="form.internal_craft_ids" multiple collapse-tags collapse-tags-tooltip placeholder="选择厂内工艺；留空保持原值" popper-class="schedule-craft-popper"><ElOption v-for="craft in internalCrafts" :key="craft.id" :label="craft.name" :value="craft.id" /></ElSelect></label>
      <label class="batch-grid__craft"><span>厂外工艺</span><ElSelect v-model="form.external_craft_ids" multiple collapse-tags collapse-tags-tooltip placeholder="选择厂外工艺；留空保持原值" popper-class="schedule-craft-popper"><ElOption v-for="craft in externalCrafts" :key="craft.id" :label="craft.name" :value="craft.id" /></ElSelect></label>
    </div>
    <template #footer><ElButton @click="emit('update:modelValue', false)">取消</ElButton><ElButton type="primary" :disabled="selectedCount === 0" @click="apply">确认选择</ElButton></template>
  </AppWindowDialog>
</template>
