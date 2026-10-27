<script setup lang="ts">
import { computed } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import PinyinFilterSelect from '@/components/production/PinyinFilterSelect.vue'
import { compactDecimal } from '@/utils/compactDecimal'
import type {
  BomAuxiliaryProductOption,
  BomEditorReferenceOptions,
  BomHardwareMaterial,
  BomHardwareMaterialGroup,
} from '@/types/bom'

type PickerCallback = (...args: any[]) => any

const props = defineProps<{
  hardwarePickerVisible: boolean
  hardwarePickerMaterialName: string
  hardwarePickerKeyword: string
  hardwareGroupLoading: boolean
  hardwarePickerLoading: boolean
  hardwareGroupError: string
  hardwarePickerError: string
  visibleHardwareGroups: BomHardwareMaterialGroup[]
  hardwareCandidates: BomHardwareMaterial[]
  selectedHardware: Record<string, BomHardwareMaterial>
  hardwarePickerPage: number
  hardwarePickerPageSize: number
  hardwarePickerTotal: number
  selectedHardwareCount: number
  hardwarePageAllSelected: boolean
  hardwarePageSelectionIndeterminate: boolean
  canCreateHardwareRawMaterial: boolean
  resetHardwarePicker: PickerCallback

  plasticPickerVisible: boolean
  plasticPickerMaterialName: string
  plasticPickerKeyword: string
  plasticGroupLoading: boolean
  plasticPickerLoading: boolean
  plasticGroupError: string
  plasticPickerError: string
  visiblePlasticGroups: BomHardwareMaterialGroup[]
  plasticCandidates: BomHardwareMaterial[]
  selectedPlastic: Record<string, BomHardwareMaterial>
  plasticPickerPage: number
  plasticPickerPageSize: number
  plasticPickerTotal: number
  selectedPlasticCount: number
  plasticPageAllSelected: boolean
  plasticPageSelectionIndeterminate: boolean
  canCreateRawMaterial: boolean
  resetPlasticPicker: PickerCallback

  auxiliaryPickerVisible: boolean
  auxiliaryPickerProductName: string
  auxiliaryPickerKeyword: string
  auxiliaryCandidates: BomAuxiliaryProductOption[]
  selectedAuxiliaryProducts: Record<string, BomAuxiliaryProductOption>
  auxiliaryPickerPage: number
  auxiliaryPickerPageSize: number
  auxiliaryPickerTotal: number
  selectedAuxiliaryProductCount: number
  auxiliaryPageAllSelected: boolean
  auxiliaryPageSelectionIndeterminate: boolean
  editorReferenceOptions: BomEditorReferenceOptions | null
  editorReferenceOptionsLoading: boolean
  editorReferenceOptionsError: string
  resetAuxiliaryPicker: PickerCallback

  packagingPickerVisible: boolean
  packagingPickerMaterialName: string
  packagingPickerKeyword: string
  packagingGroupLoading: boolean
  packagingPickerLoading: boolean
  packagingGroupError: string
  packagingPickerError: string
  visiblePackagingGroups: BomHardwareMaterialGroup[]
  packagingCandidates: BomHardwareMaterial[]
  selectedPackaging: Record<string, BomHardwareMaterial>
  packagingPickerPage: number
  packagingPickerPageSize: number
  packagingPickerTotal: number
  selectedPackagingCount: number
  packagingPageAllSelected: boolean
  packagingPageSelectionIndeterminate: boolean
  resetPackagingPicker: PickerCallback

  cuttingPickerVisible: boolean
  cuttingPickerMaterialName: string
  cuttingPickerKeyword: string
  cuttingGroupLoading: boolean
  cuttingPickerLoading: boolean
  cuttingGroupError: string
  cuttingPickerError: string
  visibleCuttingGroups: BomHardwareMaterialGroup[]
  cuttingCandidates: BomHardwareMaterial[]
  selectedCutting: Record<string, BomHardwareMaterial>
  cuttingPickerPage: number
  cuttingPickerPageSize: number
  cuttingPickerTotal: number
  selectedCuttingCount: number
  cuttingPageAllSelected: boolean
  cuttingPageSelectionIndeterminate: boolean
  resetCuttingPicker: PickerCallback

  pendingRawMaterials: Record<string, unknown>
  formatHardwareColor: (value: string) => string
  filterHardwareGroups: PickerCallback
  searchHardwareCandidates: PickerCallback
  clearHardwareGroupFilter: PickerCallback
  loadHardwareGroups: PickerCallback
  loadHardwareCandidates: PickerCallback
  toggleHardwareRow: PickerCallback
  hardwarePickerRowClass: PickerCallback
  toggleHardwarePage: PickerCallback
  toggleHardwareCandidate: PickerCallback
  changeHardwarePage: PickerCallback
  openHardwareCreate: PickerCallback
  confirmHardwareSelection: PickerCallback

  filterPlasticGroups: PickerCallback
  searchPlasticCandidates: PickerCallback
  clearPlasticGroupFilter: PickerCallback
  loadPlasticGroups: PickerCallback
  loadPlasticCandidates: PickerCallback
  togglePlasticRow: PickerCallback
  plasticPickerRowClass: PickerCallback
  togglePlasticPage: PickerCallback
  togglePlasticCandidate: PickerCallback
  changePlasticPage: PickerCallback
  openRawMaterialCreate: PickerCallback
  confirmPlasticSelection: PickerCallback

  searchAuxiliaryCandidates: PickerCallback
  ensureEditorReferenceOptions: PickerCallback
  toggleAuxiliaryRow: PickerCallback
  auxiliaryPickerRowClass: PickerCallback
  toggleAuxiliaryPage: PickerCallback
  toggleAuxiliaryCandidate: PickerCallback
  changeAuxiliaryPage: PickerCallback
  openAuxiliaryCreate: PickerCallback
  confirmAuxiliarySelection: PickerCallback
  auxiliaryProductMaintenanceTip: PickerCallback
  auxiliaryProductIsSelectable: PickerCallback
  auxiliarySpecificationSummary: PickerCallback
  auxiliaryColorSummary: PickerCallback

  filterPackagingGroups: PickerCallback
  searchPackagingCandidates: PickerCallback
  clearPackagingGroupFilter: PickerCallback
  loadPackagingGroups: PickerCallback
  loadPackagingCandidates: PickerCallback
  togglePackagingRow: PickerCallback
  packagingPickerRowClass: PickerCallback
  togglePackagingPage: PickerCallback
  togglePackagingCandidate: PickerCallback
  changePackagingPage: PickerCallback
  confirmPackagingSelection: PickerCallback

  filterCuttingGroups: PickerCallback
  searchCuttingCandidates: PickerCallback
  clearCuttingGroupFilter: PickerCallback
  loadCuttingGroups: PickerCallback
  loadCuttingCandidates: PickerCallback
  toggleCuttingRow: PickerCallback
  cuttingPickerRowClass: PickerCallback
  toggleCuttingPage: PickerCallback
  toggleCuttingCandidate: PickerCallback
  changeCuttingPage: PickerCallback
  confirmCuttingSelection: PickerCallback
}>()

const emit = defineEmits<{
  (event: 'update:hardwarePickerVisible', value: boolean): void
  (event: 'update:hardwarePickerMaterialName', value: string): void
  (event: 'update:hardwarePickerKeyword', value: string): void
  (event: 'update:plasticPickerVisible', value: boolean): void
  (event: 'update:plasticPickerMaterialName', value: string): void
  (event: 'update:plasticPickerKeyword', value: string): void
  (event: 'update:auxiliaryPickerVisible', value: boolean): void
  (event: 'update:auxiliaryPickerProductName', value: string): void
  (event: 'update:auxiliaryPickerKeyword', value: string): void
  (event: 'update:packagingPickerVisible', value: boolean): void
  (event: 'update:packagingPickerMaterialName', value: string): void
  (event: 'update:packagingPickerKeyword', value: string): void
  (event: 'update:cuttingPickerVisible', value: boolean): void
  (event: 'update:cuttingPickerMaterialName', value: string): void
  (event: 'update:cuttingPickerKeyword', value: string): void
}>()

const hardwarePickerVisibleModel = computed({ get: () => props.hardwarePickerVisible, set: value => emit('update:hardwarePickerVisible', value) })
const hardwarePickerMaterialNameModel = computed({ get: () => props.hardwarePickerMaterialName, set: value => emit('update:hardwarePickerMaterialName', value) })
const hardwarePickerKeywordModel = computed({ get: () => props.hardwarePickerKeyword, set: value => emit('update:hardwarePickerKeyword', value) })
const plasticPickerVisibleModel = computed({ get: () => props.plasticPickerVisible, set: value => emit('update:plasticPickerVisible', value) })
const plasticPickerMaterialNameModel = computed({ get: () => props.plasticPickerMaterialName, set: value => emit('update:plasticPickerMaterialName', value) })
const plasticPickerKeywordModel = computed({ get: () => props.plasticPickerKeyword, set: value => emit('update:plasticPickerKeyword', value) })
const auxiliaryPickerVisibleModel = computed({ get: () => props.auxiliaryPickerVisible, set: value => emit('update:auxiliaryPickerVisible', value) })
const auxiliaryPickerProductNameModel = computed({ get: () => props.auxiliaryPickerProductName, set: value => emit('update:auxiliaryPickerProductName', value) })
const auxiliaryPickerKeywordModel = computed({ get: () => props.auxiliaryPickerKeyword, set: value => emit('update:auxiliaryPickerKeyword', value) })
const packagingPickerVisibleModel = computed({ get: () => props.packagingPickerVisible, set: value => emit('update:packagingPickerVisible', value) })
const packagingPickerMaterialNameModel = computed({ get: () => props.packagingPickerMaterialName, set: value => emit('update:packagingPickerMaterialName', value) })
const packagingPickerKeywordModel = computed({ get: () => props.packagingPickerKeyword, set: value => emit('update:packagingPickerKeyword', value) })
const cuttingPickerVisibleModel = computed({ get: () => props.cuttingPickerVisible, set: value => emit('update:cuttingPickerVisible', value) })
const cuttingPickerMaterialNameModel = computed({ get: () => props.cuttingPickerMaterialName, set: value => emit('update:cuttingPickerMaterialName', value) })
const cuttingPickerKeywordModel = computed({ get: () => props.cuttingPickerKeyword, set: value => emit('update:cuttingPickerKeyword', value) })
</script>

<template>
  <AppWindowDialog v-model="hardwarePickerVisibleModel" class="hardware-picker-dialog" title="选择五金数据" width="1180px" append-to-body destroy-on-close :close-on-click-modal="false" @closed="props.resetHardwarePicker">
    <div class="hardware-picker-source"><strong>数据来源：原料信息 / 材料 / 五金</strong><span>只显示“五金”类别，支持跨页多选；确认后写入当前 BOM，不会修改原料主数据。</span></div>
    <div class="hardware-picker-toolbar hardware-picker-toolbar--hardware">
      <ElSelect v-model="hardwarePickerMaterialNameModel" clearable filterable :value-on-clear="''" :loading="props.hardwareGroupLoading" placeholder="全部品名分组" aria-label="五金品名分组" :filter-method="props.filterHardwareGroups" @change="props.searchHardwareCandidates" @visible-change="props.clearHardwareGroupFilter">
        <ElOption v-for="group in props.visibleHardwareGroups" :key="group.material_name" :label="`${group.material_name}（${group.count}）`" :value="group.material_name" />
      </ElSelect>
      <ElInput v-model="hardwarePickerKeywordModel" clearable maxlength="100" placeholder="搜索品名、材质、颜色或规格" @keyup.enter="props.searchHardwareCandidates" @clear="props.searchHardwareCandidates" />
      <ElButton type="primary" @click="props.searchHardwareCandidates">查询</ElButton>
      <ElTooltip :disabled="props.canCreateHardwareRawMaterial" content="需要“查看原料信息”和“新增原料信息”权限" placement="top"><span class="hardware-create-button-wrap"><ElButton data-testid="hardware-create-raw-material" :icon="Plus" :disabled="!props.canCreateHardwareRawMaterial" @click="props.openHardwareCreate">新增五金原料</ElButton></span></ElTooltip>
    </div>
    <ElAlert v-if="props.hardwareGroupError" class="hardware-picker-error" type="warning" :title="props.hardwareGroupError" show-icon :closable="false"><template #default><ElButton size="small" @click="props.loadHardwareGroups">重新加载品名分组</ElButton></template></ElAlert>
    <ElAlert v-if="props.hardwarePickerError" class="hardware-picker-error" type="error" :title="props.hardwarePickerError" show-icon :closable="false"><template #default><ElButton size="small" @click="props.loadHardwareCandidates">重新加载</ElButton></template></ElAlert>
    <ElTable v-loading="props.hardwarePickerLoading" class="hardware-picker-table" :data="props.hardwareCandidates" row-key="id" border max-height="460" empty-text="暂无符合条件的五金数据" :row-class-name="props.hardwarePickerRowClass" @row-click="props.toggleHardwareRow">
      <ElTableColumn width="52" align="center" header-align="center"><template #header><ElCheckbox :model-value="props.hardwarePageAllSelected" :indeterminate="props.hardwarePageSelectionIndeterminate" aria-label="全选当前页五金数据" @change="props.toggleHardwarePage" /></template><template #default="scope"><ElCheckbox :model-value="Boolean(props.selectedHardware[scope.row.id])" :aria-label="`选择 ${scope.row.material_name}`" @click.stop @change="props.toggleHardwareCandidate(scope.row, $event)" /></template></ElTableColumn>
      <ElTableColumn prop="material_name" label="品名" min-width="165" show-overflow-tooltip><template #default="scope"><span v-if="props.pendingRawMaterials[scope.row.id]" class="pending-material-label">暂存</span>{{ scope.row.material_name }}</template></ElTableColumn>
      <ElTableColumn prop="material" label="材质" width="100" show-overflow-tooltip /><ElTableColumn label="颜色" min-width="130" show-overflow-tooltip><template #default="scope">{{ props.formatHardwareColor(scope.row.color_name) }}</template></ElTableColumn><ElTableColumn prop="specification" label="规格" min-width="150" show-overflow-tooltip /><ElTableColumn prop="unit_name" label="单位" width="76" /><ElTableColumn label="单个材料重量（kg）" width="160"><template #default="scope">{{ compactDecimal(scope.row.weight_kg, '待填写') }}</template></ElTableColumn><ElTableColumn label="流转单位" width="90"><template #default="scope">{{ scope.row.flow_unit || '—' }}</template></ElTableColumn>
    </ElTable>
    <div class="hardware-picker-pagination"><span>已选择 {{ props.selectedHardwareCount }} 条</span><ElPagination :current-page="props.hardwarePickerPage" :page-size="props.hardwarePickerPageSize" :total="props.hardwarePickerTotal" layout="total, prev, pager, next" @current-change="props.changeHardwarePage" /></div>
    <template #footer><div class="hardware-picker-footer"><span>确认后可在五金件表格中填写用量、单重和喷塑信息。</span><div><ElButton @click="hardwarePickerVisibleModel = false">取消</ElButton><ElButton type="primary" :disabled="!props.selectedHardwareCount" @click="props.confirmHardwareSelection">确认添加（{{ props.selectedHardwareCount }}）</ElButton></div></div></template>
  </AppWindowDialog>

  <AppWindowDialog v-model="plasticPickerVisibleModel" class="hardware-picker-dialog" title="选择塑料件数据" width="1180px" append-to-body destroy-on-close :close-on-click-modal="false" @closed="props.resetPlasticPicker">
    <div class="hardware-picker-source"><strong>数据来源：原料信息 / 材料 / 塑料件</strong><span>支持搜索、分页和跨页多选；确认后只在当前 BOM 中填写用量和备注。</span></div>
    <div class="hardware-picker-toolbar hardware-picker-toolbar--grouped"><ElSelect v-model="plasticPickerMaterialNameModel" clearable filterable :value-on-clear="''" :loading="props.plasticGroupLoading" placeholder="全部品名分组" aria-label="塑料件品名分组" :filter-method="props.filterPlasticGroups" @change="props.searchPlasticCandidates" @visible-change="props.clearPlasticGroupFilter"><ElOption v-for="group in props.visiblePlasticGroups" :key="group.material_name" :label="`${group.material_name}（${group.count}）`" :value="group.material_name" /></ElSelect><ElInput v-model="plasticPickerKeywordModel" clearable maxlength="100" placeholder="搜索品名、材质、颜色或规格" @keyup.enter="props.searchPlasticCandidates" @clear="props.searchPlasticCandidates" /><ElButton type="primary" @click="props.searchPlasticCandidates">查询</ElButton><ElButton :icon="Plus" :disabled="!props.canCreateRawMaterial" @click="props.openRawMaterialCreate('plastic')">新增原料</ElButton></div>
    <ElAlert v-if="props.plasticGroupError" class="hardware-picker-error" type="warning" :title="props.plasticGroupError" show-icon :closable="false"><template #default><ElButton size="small" @click="props.loadPlasticGroups">重新加载品名分组</ElButton></template></ElAlert><ElAlert v-if="props.plasticPickerError" class="hardware-picker-error" type="error" :title="props.plasticPickerError" show-icon :closable="false"><template #default><ElButton size="small" @click="props.loadPlasticCandidates">重新加载</ElButton></template></ElAlert>
    <ElTable v-loading="props.plasticPickerLoading" class="plastic-picker-table picker-selectable-table" :data="props.plasticCandidates" row-key="id" border max-height="460" empty-text="暂无符合条件的塑料件数据" :row-class-name="props.plasticPickerRowClass" @row-click="props.togglePlasticRow"><ElTableColumn width="52" align="center" header-align="center"><template #header><ElCheckbox :model-value="props.plasticPageAllSelected" :indeterminate="props.plasticPageSelectionIndeterminate" aria-label="全选当前页塑料件数据" @change="props.togglePlasticPage" /></template><template #default="scope"><ElCheckbox :model-value="Boolean(props.selectedPlastic[scope.row.id])" :aria-label="`选择 ${scope.row.material_name}`" @click.stop @change="props.togglePlasticCandidate(scope.row, $event)" /></template></ElTableColumn><ElTableColumn prop="material_name" label="品名" min-width="190" show-overflow-tooltip><template #default="scope"><span v-if="props.pendingRawMaterials[scope.row.id]" class="pending-material-label">暂存</span>{{ scope.row.material_name }}</template></ElTableColumn><ElTableColumn prop="material" label="材质" width="120" show-overflow-tooltip /><ElTableColumn label="颜色" min-width="145" show-overflow-tooltip><template #default="scope">{{ props.formatHardwareColor(scope.row.color_name) }}</template></ElTableColumn><ElTableColumn prop="specification" label="规格" min-width="170" show-overflow-tooltip /><ElTableColumn prop="unit_name" label="单位" width="90" /></ElTable>
    <div class="hardware-picker-pagination"><span>已选择 {{ props.selectedPlasticCount }} 条</span><ElPagination :current-page="props.plasticPickerPage" :page-size="props.plasticPickerPageSize" :total="props.plasticPickerTotal" layout="total, prev, pager, next" @current-change="props.changePlasticPage" /></div>
    <template #footer><div class="hardware-picker-footer"><span>确认后保留主数据快照，表格中只需填写单个用量和备注。</span><div><ElButton @click="plasticPickerVisibleModel = false">取消</ElButton><ElButton type="primary" :disabled="!props.selectedPlasticCount" @click="props.confirmPlasticSelection">确认添加（{{ props.selectedPlasticCount }}）</ElButton></div></div></template>
  </AppWindowDialog>

  <AppWindowDialog v-model="auxiliaryPickerVisibleModel" class="hardware-picker-dialog" title="选择辅料品名" width="1180px" append-to-body destroy-on-close :close-on-click-modal="false" @closed="props.resetAuxiliaryPicker">
    <div class="hardware-picker-source"><strong>数据来源：系统设置 / 生产维护 / 辅料维护</strong><span>同一品名后续可以再次添加，以填写不同的规格、颜色或材质组合。</span></div>
    <div class="hardware-picker-toolbar hardware-picker-toolbar--grouped"><PinyinFilterSelect v-model="auxiliaryPickerProductNameModel" :options="props.editorReferenceOptions?.auxiliary_products || []" label-key="product_name" :loading="props.editorReferenceOptionsLoading" placeholder="全部品名分组" aria-label="辅料品名分组" @update:model-value="props.searchAuxiliaryCandidates" /><ElInput v-model="auxiliaryPickerKeywordModel" clearable maxlength="100" placeholder="搜索辅料品名、规格或颜色" @keyup.enter="props.searchAuxiliaryCandidates" @clear="props.searchAuxiliaryCandidates" /><ElButton type="primary" @click="props.searchAuxiliaryCandidates">查询</ElButton><ElButton :icon="Plus" @click="props.openAuxiliaryCreate">新增辅料资料</ElButton></div>
    <ElAlert v-if="props.editorReferenceOptionsError" class="hardware-picker-error" type="error" :title="props.editorReferenceOptionsError" show-icon :closable="false"><template #default><ElButton size="small" @click="props.ensureEditorReferenceOptions">重新加载</ElButton></template></ElAlert>
    <ElTable v-loading="props.editorReferenceOptionsLoading" class="auxiliary-picker-table picker-selectable-table" :data="props.auxiliaryCandidates" row-key="id" border max-height="460" empty-text="暂无符合条件的辅料品名" :row-class-name="props.auxiliaryPickerRowClass" @row-click="props.toggleAuxiliaryRow"><ElTableColumn width="52" align="center" header-align="center"><template #header><ElCheckbox :model-value="props.auxiliaryPageAllSelected" :indeterminate="props.auxiliaryPageSelectionIndeterminate" aria-label="全选当前页可选辅料" @change="props.toggleAuxiliaryPage" /></template><template #default="scope"><ElTooltip :disabled="props.auxiliaryProductMaintenanceTip(scope.row) === '可选择'" :content="props.auxiliaryProductMaintenanceTip(scope.row)" placement="right"><span><ElCheckbox :model-value="Boolean(props.selectedAuxiliaryProducts[scope.row.id])" :disabled="!props.auxiliaryProductIsSelectable(scope.row)" :aria-label="`选择 ${scope.row.product_name}`" @click.stop @change="props.toggleAuxiliaryCandidate(scope.row, $event)" /></span></ElTooltip></template></ElTableColumn><ElTableColumn prop="product_name" label="品名" min-width="180" show-overflow-tooltip /><ElTableColumn label="归属规格" min-width="230" show-overflow-tooltip><template #default="scope">{{ props.auxiliarySpecificationSummary(scope.row) }}</template></ElTableColumn><ElTableColumn label="归属颜色" min-width="230" show-overflow-tooltip><template #default="scope">{{ props.auxiliaryColorSummary(scope.row) }}</template></ElTableColumn><ElTableColumn label="单位" width="90"><template #default="scope">{{ scope.row.unit_name || '待维护' }}</template></ElTableColumn><ElTableColumn label="状态" width="150" align="center"><template #default="scope"><span class="picker-status-tag" :class="props.auxiliaryProductMaintenanceTip(scope.row) === '可选择' ? 'is-success' : 'is-warning'">{{ props.auxiliaryProductMaintenanceTip(scope.row) }}</span></template></ElTableColumn></ElTable>
    <div class="hardware-picker-pagination"><span>已选择 {{ props.selectedAuxiliaryProductCount }} 条</span><ElPagination :current-page="props.auxiliaryPickerPage" :page-size="props.auxiliaryPickerPageSize" :total="props.auxiliaryPickerTotal" layout="total, prev, pager, next" @current-change="props.changeAuxiliaryPage" /></div>
    <template #footer><div class="hardware-picker-footer"><span>缺少归属规格或颜色时不能选择；缺少单位时可添加，但需到“辅料维护”补全。</span><div><ElButton @click="auxiliaryPickerVisibleModel = false">取消</ElButton><ElButton type="primary" :disabled="!props.selectedAuxiliaryProductCount" @click="props.confirmAuxiliarySelection">确认添加（{{ props.selectedAuxiliaryProductCount }}）</ElButton></div></div></template>
  </AppWindowDialog>

  <AppWindowDialog v-model="packagingPickerVisibleModel" class="hardware-picker-dialog" title="选择包材数据" width="1180px" append-to-body destroy-on-close :close-on-click-modal="false" @closed="props.resetPackagingPicker">
    <div class="hardware-picker-source"><strong>数据来源：原料信息 / 材料 / 包材</strong><span>支持品名分组、关键词、分页和跨页多选；确认后填写箱数与单个用量。</span></div>
    <div class="hardware-picker-toolbar hardware-picker-toolbar--grouped"><ElSelect v-model="packagingPickerMaterialNameModel" clearable filterable :value-on-clear="''" :loading="props.packagingGroupLoading" placeholder="全部品名分组" aria-label="包材品名分组" :filter-method="props.filterPackagingGroups" @change="props.searchPackagingCandidates" @visible-change="props.clearPackagingGroupFilter"><ElOption v-for="group in props.visiblePackagingGroups" :key="group.material_name" :label="`${group.material_name}（${group.count}）`" :value="group.material_name" /></ElSelect><ElInput v-model="packagingPickerKeywordModel" clearable maxlength="100" placeholder="搜索品名、材质、颜色或规格" @keyup.enter="props.searchPackagingCandidates" @clear="props.searchPackagingCandidates" /><ElButton type="primary" @click="props.searchPackagingCandidates">查询</ElButton><ElButton :icon="Plus" :disabled="!props.canCreateRawMaterial" @click="props.openRawMaterialCreate('packaging')">新增原料</ElButton></div>
    <ElAlert v-if="props.packagingGroupError" class="hardware-picker-error" type="warning" :title="props.packagingGroupError" show-icon :closable="false"><template #default><ElButton size="small" @click="props.loadPackagingGroups">重新加载品名分组</ElButton></template></ElAlert><ElAlert v-if="props.packagingPickerError" class="hardware-picker-error" type="error" :title="props.packagingPickerError" show-icon :closable="false"><template #default><ElButton size="small" @click="props.loadPackagingCandidates">重新加载</ElButton></template></ElAlert>
    <ElTable v-loading="props.packagingPickerLoading" class="packaging-picker-table picker-selectable-table" :data="props.packagingCandidates" row-key="id" border max-height="460" empty-text="暂无符合条件的包材数据" :row-class-name="props.packagingPickerRowClass" @row-click="props.togglePackagingRow"><ElTableColumn width="52" align="center" header-align="center"><template #header><ElCheckbox :model-value="props.packagingPageAllSelected" :indeterminate="props.packagingPageSelectionIndeterminate" aria-label="全选当前页包材数据" @change="props.togglePackagingPage" /></template><template #default="scope"><ElCheckbox :model-value="Boolean(props.selectedPackaging[scope.row.id])" :aria-label="`选择 ${scope.row.material_name}`" @click.stop @change="props.togglePackagingCandidate(scope.row, $event)" /></template></ElTableColumn><ElTableColumn prop="material_name" label="品名" min-width="180" show-overflow-tooltip><template #default="scope"><span v-if="props.pendingRawMaterials[scope.row.id]" class="pending-material-label">暂存</span>{{ scope.row.material_name }}</template></ElTableColumn><ElTableColumn prop="material" label="材质" width="115" show-overflow-tooltip /><ElTableColumn label="颜色" min-width="135" show-overflow-tooltip><template #default="scope">{{ props.formatHardwareColor(scope.row.color_name) }}</template></ElTableColumn><ElTableColumn prop="specification" label="规格" min-width="170" show-overflow-tooltip /><ElTableColumn prop="unit_name" label="单位" width="86" /></ElTable>
    <div class="hardware-picker-pagination"><span>已选择 {{ props.selectedPackagingCount }} 条</span><ElPagination :current-page="props.packagingPickerPage" :page-size="props.packagingPickerPageSize" :total="props.packagingPickerTotal" layout="total, prev, pager, next" @current-change="props.changePackagingPage" /></div>
    <template #footer><div class="hardware-picker-footer"><span>每箱装数不会从规格数字自动推断，需在 BOM 中人工填写。</span><div><ElButton @click="packagingPickerVisibleModel = false">取消</ElButton><ElButton type="primary" :disabled="!props.selectedPackagingCount" @click="props.confirmPackagingSelection">确认添加（{{ props.selectedPackagingCount }}）</ElButton></div></div></template>
  </AppWindowDialog>

  <AppWindowDialog v-model="cuttingPickerVisibleModel" class="hardware-picker-dialog" title="选择裁剪数据" width="1180px" append-to-body destroy-on-close :close-on-click-modal="false" @closed="props.resetCuttingPicker">
    <div class="hardware-picker-source"><strong>数据来源：原料信息 / 半成品</strong><span>找不到现有裁片时可直接“新增裁片”；确认添加后须补齐规格和裁片用量。</span></div>
    <div class="hardware-picker-toolbar hardware-picker-toolbar--grouped"><ElSelect v-model="cuttingPickerMaterialNameModel" clearable filterable :value-on-clear="''" :loading="props.cuttingGroupLoading" placeholder="全部品名分组" aria-label="裁剪品名分组" :filter-method="props.filterCuttingGroups" @change="props.searchCuttingCandidates" @visible-change="props.clearCuttingGroupFilter"><ElOption v-for="group in props.visibleCuttingGroups" :key="group.material_name" :label="`${group.material_name}（${group.count}）`" :value="group.material_name" /></ElSelect><ElInput v-model="cuttingPickerKeywordModel" clearable maxlength="100" placeholder="搜索品名或规格" @keyup.enter="props.searchCuttingCandidates" @clear="props.searchCuttingCandidates" /><ElButton type="primary" @click="props.searchCuttingCandidates">查询</ElButton><ElButton :icon="Plus" :disabled="!props.canCreateRawMaterial" @click="props.openRawMaterialCreate('cutting')">新增裁片</ElButton></div>
    <ElAlert v-if="props.cuttingGroupError" class="hardware-picker-error" type="warning" :title="props.cuttingGroupError" show-icon :closable="false"><template #default><ElButton size="small" @click="props.loadCuttingGroups">重新加载品名分组</ElButton></template></ElAlert><ElAlert v-if="props.cuttingPickerError" class="hardware-picker-error" type="error" :title="props.cuttingPickerError" show-icon :closable="false"><template #default><ElButton size="small" @click="props.loadCuttingCandidates">重新加载</ElButton></template></ElAlert>
    <ElTable v-loading="props.cuttingPickerLoading" class="cutting-picker-table picker-selectable-table" :data="props.cuttingCandidates" row-key="id" border max-height="460" empty-text="暂无符合条件的裁剪数据" :row-class-name="props.cuttingPickerRowClass" @row-click="props.toggleCuttingRow"><ElTableColumn width="52" align="center" header-align="center"><template #header><ElCheckbox :model-value="props.cuttingPageAllSelected" :indeterminate="props.cuttingPageSelectionIndeterminate" aria-label="全选当前页裁剪数据" @change="props.toggleCuttingPage" /></template><template #default="scope"><ElCheckbox :model-value="Boolean(props.selectedCutting[scope.row.id])" :aria-label="`选择 ${scope.row.material_name}`" @click.stop @change="props.toggleCuttingCandidate(scope.row, $event)" /></template></ElTableColumn><ElTableColumn prop="material_name" label="裁剪名称" min-width="175" show-overflow-tooltip><template #default="scope"><span v-if="props.pendingRawMaterials[scope.row.id]" class="pending-material-label">暂存</span>{{ scope.row.material_name }}</template></ElTableColumn><ElTableColumn prop="category_name" label="类别" width="120" show-overflow-tooltip /><ElTableColumn prop="specification" label="规格" min-width="150" show-overflow-tooltip /><ElTableColumn prop="unit_name" label="单位" width="80" /></ElTable>
    <div class="hardware-picker-pagination"><span>已选择 {{ props.selectedCuttingCount }} 条</span><ElPagination :current-page="props.cuttingPickerPage" :page-size="props.cuttingPickerPageSize" :total="props.cuttingPickerTotal" layout="total, prev, pager, next" @current-change="props.changeCuttingPage" /></div>
    <template #footer><div class="hardware-picker-footer"><span>确认添加后即可打开行编辑抽屉批量上传图片，无需先保存 BOM。</span><div><ElButton @click="cuttingPickerVisibleModel = false">取消</ElButton><ElButton type="primary" :disabled="!props.selectedCuttingCount" @click="props.confirmCuttingSelection">确认添加（{{ props.selectedCuttingCount }}）</ElButton></div></div></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.pending-material-label { margin-right: 6px; color: token.$crm-warning; font-size: 12px; }
.hardware-picker-source { display: flex; justify-content: space-between; gap: 20px; padding: 10px 12px; border: 1px solid var(--erp-color-border); border-radius: 5px; background: var(--erp-color-subtle); color: var(--erp-color-text-secondary); font-size: 12px; }
.hardware-picker-source strong { color: var(--erp-color-brand-hover); }
.hardware-picker-toolbar { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; margin: 14px 0 12px; }
.hardware-picker-toolbar--hardware, .hardware-picker-toolbar--grouped { grid-template-columns: 240px minmax(0, 1fr) auto auto; }
.hardware-create-button-wrap { display: inline-flex; }
.hardware-picker-error { margin-bottom: 12px; }
.hardware-picker-table :deep(.el-table__row) { cursor: pointer; }
.hardware-picker-table :deep(.el-table__row.is-picker-selected > td.el-table__cell), .picker-selectable-table :deep(.el-table__row.is-picker-selected > td.el-table__cell) { background: var(--erp-table-selected); }
.picker-selectable-table :deep(.el-table__row) { cursor: pointer; }
.picker-selectable-table :deep(.el-table__row.is-picker-disabled) { cursor: not-allowed; }
.hardware-picker-pagination { display: flex; min-height: 42px; align-items: center; justify-content: space-between; gap: 16px; color: var(--erp-color-text-regular); font-size: 13px; }
.hardware-picker-footer { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.hardware-picker-footer > span { color: var(--erp-color-text-secondary); font-size: 12px; }
.hardware-picker-footer > div { display: flex; gap: 8px; }
.picker-status-tag { min-width: 56px; height: 24px; display: inline-flex; align-items: center; justify-content: center; padding: 0 8px; box-sizing: border-box; border: 0; border-radius: 999px; color: var(--erp-tag-success-text); font-family: "Noto Sans SC", sans-serif; font-size: 12px; line-height: 18px; font-weight: 500; white-space: nowrap; }
.picker-status-tag.is-success { background: var(--erp-tag-success-background); }
.picker-status-tag.is-warning { background: var(--erp-tag-warning-background); }
</style>
