<script setup lang="ts">
import { ref, watch } from 'vue'
import MaterialSelectionPanel from '@/components/products/MaterialSelectionPanel.vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import RawMaterialManagementView from '@/views/products/RawMaterialManagementView.vue'
import { bomCatalogCategories } from '@/components/products/materialSelection'
import type { MaterialCatalog } from '@/types/materialCatalog'
import type { SampleMaterialLine } from '@/types/sampleMaterial'
import { applySampleSelection, sampleCatalogTitles, sampleSelectionLine } from '@/utils/sampleCatalogSelection'

const props = withDefaults(defineProps<{ modelValue: SampleMaterialLine; disabled?: boolean; source?: 'catalog' | 'sample' }>(), { source: 'catalog' })
const emit = defineEmits<{ 'update:modelValue': [line: SampleMaterialLine]; loaded: [catalog: MaterialCatalog] }>()
const selection = ref(sampleSelectionLine(props.modelValue))
const maintenanceOpen = ref(false), refreshKey = ref(0)
const maintenanceView = ref<InstanceType<typeof RawMaterialManagementView>>()
async function beforeMaintenanceClose(done: () => void) {
  const view = maintenanceView.value
  if (!view || await view.canLeave()) done()
}
watch(selection, value => {
  if (!props.disabled && value.material_catalog_id) emit('update:modelValue', applySampleSelection(props.modelValue, value))
}, { deep: true })
</script>
<template>
  <fieldset class="sample-catalog-selection" :disabled="disabled">
    <MaterialSelectionPanel :line="selection" :source="source" :section-title="sampleCatalogTitles[modelValue.category]" :refresh-key="refreshKey" :fixed-unit="modelValue.category === 'tube' ? '根' : undefined" @loaded="emit('loaded', $event)" @maintain="maintenanceOpen = source === 'catalog'" />
  </fieldset>
  <AppWindowDialog v-model="maintenanceOpen" title="分区原料维护" :width="1100" height="80vh" destroy-on-close :close-on-click-modal="false" :before-close="beforeMaintenanceClose">
    <RawMaterialManagementView v-if="maintenanceOpen && source === 'catalog'" ref="maintenanceView" :fixed-category="bomCatalogCategories[sampleCatalogTitles[modelValue.category]]" @saved="refreshKey++" />
  </AppWindowDialog>
</template>
<style scoped>
.sample-catalog-selection { border: 0; padding: 0; margin: 0; min-width: 0; }
.sample-catalog-selection:disabled { pointer-events: none; opacity: .65; }
</style>
