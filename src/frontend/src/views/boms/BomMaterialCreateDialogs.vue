<script setup lang="ts">
import { computed } from 'vue'

import AuxiliaryReferenceCreateDialog from '@/components/AuxiliaryReferenceCreateDialog.vue'
import HardwareRawMaterialCreateDialog from '@/components/HardwareRawMaterialCreateDialog.vue'
import type { BomAuxiliaryProductOption } from '@/types/bom'
import type { RawMaterialInformation, RawMaterialInput } from '@/types/rawMaterial'

type RawMaterialTarget = 'hardware' | 'plastic' | 'packaging' | 'cutting'
type RawMaterialDisplay = Pick<RawMaterialInformation, 'category_name' | 'unit_name' | 'unit_code' | 'color_name'>
type StageRawMaterial = (
  target: RawMaterialTarget,
  payload: RawMaterialInput,
  display: RawMaterialDisplay,
) => void | Promise<void>

const props = defineProps<{
  hardwareCreateVisible: boolean
  plasticCreateVisible: boolean
  packagingCreateVisible: boolean
  cuttingCreateVisible: boolean
  auxiliaryCreateVisible: boolean
  stageRawMaterial: StageRawMaterial
  handleAuxiliaryCreated: (item: BomAuxiliaryProductOption) => void | Promise<void>
}>()

const emit = defineEmits<{
  (event: 'update:hardwareCreateVisible', value: boolean): void
  (event: 'update:plasticCreateVisible', value: boolean): void
  (event: 'update:packagingCreateVisible', value: boolean): void
  (event: 'update:cuttingCreateVisible', value: boolean): void
  (event: 'update:auxiliaryCreateVisible', value: boolean): void
}>()

const hardwareVisible = computed({
  get: () => props.hardwareCreateVisible,
  set: (value: boolean) => emit('update:hardwareCreateVisible', value),
})
const plasticVisible = computed({
  get: () => props.plasticCreateVisible,
  set: (value: boolean) => emit('update:plasticCreateVisible', value),
})
const packagingVisible = computed({
  get: () => props.packagingCreateVisible,
  set: (value: boolean) => emit('update:packagingCreateVisible', value),
})
const cuttingVisible = computed({
  get: () => props.cuttingCreateVisible,
  set: (value: boolean) => emit('update:cuttingCreateVisible', value),
})
const auxiliaryVisible = computed({
  get: () => props.auxiliaryCreateVisible,
  set: (value: boolean) => emit('update:auxiliaryCreateVisible', value),
})

const stageHardwareMaterial = (payload: RawMaterialInput, display: RawMaterialDisplay) => props.stageRawMaterial('hardware', payload, display)
const stagePlasticMaterial = (payload: RawMaterialInput, display: RawMaterialDisplay) => props.stageRawMaterial('plastic', payload, display)
const stagePackagingMaterial = (payload: RawMaterialInput, display: RawMaterialDisplay) => props.stageRawMaterial('packaging', payload, display)
const stageCuttingMaterial = (payload: RawMaterialInput, display: RawMaterialDisplay) => props.stageRawMaterial('cutting', payload, display)
</script>

<template>
  <HardwareRawMaterialCreateDialog
    v-model="hardwareVisible"
    category-name="五金"
    title="新增五金原料"
    subject-label="五金原料"
    :stage-material="stageHardwareMaterial"
  />

  <HardwareRawMaterialCreateDialog
    v-model="plasticVisible"
    category-name="塑料件"
    title="新增塑料件原料"
    subject-label="塑料件原料"
    test-id="plastic-raw-material-create-dialog"
    :stage-material="stagePlasticMaterial"
  />

  <HardwareRawMaterialCreateDialog
    v-model="packagingVisible"
    category-name="包材"
    title="新增包材原料"
    subject-label="包材原料"
    test-id="packaging-raw-material-create-dialog"
    :stage-material="stagePackagingMaterial"
  />

  <HardwareRawMaterialCreateDialog
    v-model="cuttingVisible"
    item-type="SEMI_FINISHED"
    title="新增裁片"
    subject-label="裁片"
    require-cutting-specification
    inherit-fabric-attributes
    test-id="cutting-raw-material-create-dialog"
    :stage-material="stageCuttingMaterial"
  />

  <AuxiliaryReferenceCreateDialog
    v-model="auxiliaryVisible"
    @created="props.handleAuxiliaryCreated"
  />
</template>
