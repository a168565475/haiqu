<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, reactive, ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

import {
  fetchLocations,
  fetchVersioned,
  fetchWarehouses,
  fetchZones,
  saveLocation,
  saveWarehouse,
  saveZone,
} from '@/api/inventory'
import { useAuthStore } from '@/stores/auth'
import type { RecordStatus, Warehouse, WarehouseLocation, WarehouseType, WarehouseZone } from '@/types/inventory'

const props = withDefaults(defineProps<{ warehouseType?: WarehouseType }>(), {
  warehouseType: 'MATERIAL',
})
const emit = defineEmits<{ saved: [] }>()
const auth = useAuthStore()
const can = (permission: string) => auth.user?.is_superuser === true || auth.hasPermission(permission)

const warehouseVisible = ref(false)
const locationVisible = ref(false)
const editVisible = ref(false)
const loading = ref(false)
const saving = ref(false)
const keyword = ref('')
const locationTab = ref<'locations' | 'zones'>('locations')
const warehouses = ref<Warehouse[]>([])
const zones = ref<WarehouseZone[]>([])
const locations = ref<WarehouseLocation[]>([])
const editKind = ref<'warehouse' | 'zone' | 'location'>('warehouse')
const editId = ref<string | null>(null)
const editEtag = ref('')
const zoneOnly = computed(() => props.warehouseType === 'MATERIAL')

const warehouseForm = reactive({
  warehouse_number: '', warehouse_name: '', warehouse_type: props.warehouseType,
  address: '', status: 'ACTIVE' as RecordStatus, responsible_person_name: '', contact_phone: '',
})
const zoneForm = reactive({ warehouse: '', zone_name: '', status: 'ACTIVE' as RecordStatus })
const locationForm = reactive({ zone: '', location_number: '', capacity_box_slots: null as number | null, status: 'ACTIVE' as RecordStatus })

const scopedWarehouses = computed(() => warehouses.value.filter((item) => item.warehouse_type === props.warehouseType))
const scopedWarehouseIds = computed(() => new Set(scopedWarehouses.value.map((item) => item.id)))
const scopedZones = computed(() => zones.value.filter((item) => scopedWarehouseIds.value.has(item.warehouse)))
const scopedZoneIds = computed(() => new Set(scopedZones.value.map((item) => item.id)))
const scopedLocations = computed(() => locations.value.filter((item) => scopedZoneIds.value.has(item.zone)))
const visibleWarehouses = computed(() => scopedWarehouses.value.filter((item) => !keyword.value
  || `${item.warehouse_number}${item.warehouse_name}${item.address}`.toLowerCase().includes(keyword.value.toLowerCase())))
const visibleZones = computed(() => scopedZones.value.filter((item) => !keyword.value
  || `${item.warehouse_number}${item.warehouse_name}${item.zone_name}`.toLowerCase().includes(keyword.value.toLowerCase())))
const visibleLocations = computed(() => scopedLocations.value.filter((item) => !keyword.value
  || `${item.warehouse_number}${item.warehouse_name}${item.zone_name}${item.location_number}${item.unique_key}`.toLowerCase().includes(keyword.value.toLowerCase())))

const warehouseTypeColors: Record<WarehouseType, string> = {
  MATERIAL: 'rgb(240, 168, 0)',
  SEMI_FINISHED: 'rgb(162, 194, 4)',
  DEFECTIVE: 'rgb(0, 174, 209)',
  FINISHED: 'rgb(235, 80, 80)',
}
function warehouseTypeTagStyle(type: WarehouseType) {
  const color = warehouseTypeColors[type]
  return { backgroundColor: color, borderColor: color, color: '#fff' }
}
function statusTagStyle(status: RecordStatus) {
  const color = status === 'ACTIVE' ? 'rgb(70, 194, 111)' : 'rgb(144, 147, 153)'
  return { backgroundColor: color, borderColor: color, color: '#fff' }
}
function apiMessage(error: unknown, fallback: string): string {
  const response = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> }; detail?: string } } })?.response
  const field = response?.data?.error?.field_errors ? Object.values(response.data.error.field_errors).flat()[0] : ''
  return field || response?.data?.error?.message || response?.data?.detail || fallback
}

async function loadConfiguration() {
  loading.value = true
  try {
    ;[warehouses.value, zones.value, locations.value] = await Promise.all([
      fetchWarehouses(),
      fetchZones(),
      fetchLocations(),
    ])
  } catch (error) {
    ElMessage.error(apiMessage(error, '仓库配置加载失败。'))
  } finally {
    loading.value = false
  }
}

async function open(kind: 'warehouse' | 'location') {
  keyword.value = ''
  if (kind === 'warehouse') warehouseVisible.value = true
  else {
    locationTab.value = zoneOnly.value ? 'zones' : 'locations'
    locationVisible.value = true
  }
  await loadConfiguration()
}

async function openEditor(kind: 'warehouse' | 'zone' | 'location', item?: Warehouse | WarehouseZone | WarehouseLocation) {
  editKind.value = kind
  editId.value = item?.id || null
  editEtag.value = ''
  Object.assign(warehouseForm, {
    warehouse_number: '', warehouse_name: '', warehouse_type: props.warehouseType,
    address: '', status: 'ACTIVE', responsible_person_name: '', contact_phone: '',
  })
  Object.assign(zoneForm, { warehouse: scopedWarehouses.value[0]?.id || '', zone_name: '', status: 'ACTIVE' })
  Object.assign(locationForm, { zone: scopedZones.value[0]?.id || '', location_number: '', capacity_box_slots: null, status: 'ACTIVE' })
  try {
    if (item) {
      const resource = kind === 'warehouse'
        ? `warehouses/${item.id}/`
        : kind === 'zone' ? `warehouse-zones/${item.id}/` : `warehouse-locations/${item.id}/`
      const versioned = await fetchVersioned<Warehouse | WarehouseZone | WarehouseLocation>(resource)
      editEtag.value = versioned.etag
      if (kind === 'warehouse') {
        const value = versioned.data as Warehouse
        Object.assign(warehouseForm, {
          warehouse_number: value.warehouse_number, warehouse_name: value.warehouse_name,
          warehouse_type: value.warehouse_type, address: value.address, status: value.status,
          responsible_person_name: value.responsible_person_name, contact_phone: value.contact_phone,
        })
      } else if (kind === 'zone') {
        const value = versioned.data as WarehouseZone
        Object.assign(zoneForm, { warehouse: value.warehouse, zone_name: value.zone_name, status: value.status })
      } else {
        const value = versioned.data as WarehouseLocation
        Object.assign(locationForm, {
          zone: value.zone, location_number: value.location_number,
          capacity_box_slots: value.capacity_box_slots, status: value.status,
        })
      }
    }
    editVisible.value = true
  } catch (error) {
    ElMessage.error(apiMessage(error, '配置详情加载失败。'))
  }
}

async function submitEditor() {
  if (editKind.value === 'warehouse' && (!warehouseForm.warehouse_number.trim() || !warehouseForm.warehouse_name.trim())) {
    return ElMessage.warning('请填写仓库号和仓库名称。')
  }
  if (editKind.value === 'zone' && (!zoneForm.warehouse || !zoneForm.zone_name.trim())) {
    return ElMessage.warning('请选择仓库并填写库区。')
  }
  if (editKind.value === 'location' && (!locationForm.zone || !locationForm.location_number.trim())) {
    return ElMessage.warning('请选择库区并填写库位号。')
  }
  saving.value = true
  try {
    if (editKind.value === 'warehouse') await saveWarehouse(editId.value, warehouseForm, editEtag.value)
    else if (editKind.value === 'zone') await saveZone(editId.value, zoneForm, editEtag.value)
    else await saveLocation(editId.value, locationForm, editEtag.value)
    editVisible.value = false
    ElMessage.success('保存成功。')
    await loadConfiguration()
    emit('saved')
  } catch (error) {
    ElMessage.error(apiMessage(error, '保存失败，请检查填写内容。'))
  } finally {
    saving.value = false
  }
}

defineExpose({ open })
</script>

<template>
  <ElDialog v-model="warehouseVisible" title="仓库信息" width="calc(100vw - 32px)" height="calc(100vh - 32px)" destroy-on-close class="warehouse-config-fullscreen">
    <section class="config-body" v-loading="loading">
      <div class="config-toolbar">
        <ElInput v-model="keyword" clearable placeholder="搜索仓库号、仓库名称或地址" />
        <ElButton v-if="can('inventory.add_warehouse')" type="primary" :icon="Plus" @click="openEditor('warehouse')">新增仓库</ElButton>
      </div>
      <ElTable :data="visibleWarehouses" border height="calc(100vh - 190px)">
        <ElTableColumn prop="warehouse_number" label="仓库号" min-width="110" />
        <ElTableColumn prop="warehouse_name" label="仓库名称" min-width="150" />
        <ElTableColumn prop="warehouse_type_display" label="仓库类型" min-width="120">
          <template #default="{ row }"><ElTag effect="dark" :style="warehouseTypeTagStyle(row.warehouse_type)">{{ row.warehouse_type_display }}</ElTag></template>
        </ElTableColumn>
        <ElTableColumn prop="address" label="仓库地址" min-width="150" />
        <ElTableColumn prop="status_display" label="仓库状态" min-width="100">
          <template #default="{ row }"><ElTag effect="dark" :style="statusTagStyle(row.status)">{{ row.status_display }}</ElTag></template>
        </ElTableColumn>
        <ElTableColumn prop="responsible_person_name" label="仓库负责人" min-width="120">
          <template #default="{ row }"><span class="warehouse-owner">{{ row.responsible_person_name || '—' }}</span></template>
        </ElTableColumn>
        <ElTableColumn prop="contact_phone" label="负责人联系电话" min-width="150" />
        <ElTableColumn prop="zone_count" label="库区数" min-width="90" />
        <ElTableColumn v-if="!zoneOnly" prop="location_count" label="库位数" min-width="90" />
        <ElTableColumn v-if="!zoneOnly" prop="capacity_box_slots_total" label="总箱位" min-width="100"><template #default="{ row }">{{ row.capacity_box_slots_total ?? '未设置' }}</template></ElTableColumn>
        <ElTableColumn v-if="!zoneOnly" prop="occupied_box_slots" label="已占箱位" min-width="100" />
        <ElTableColumn label="操作" width="90" fixed="right">
          <template #default="{ row }"><ElButton v-if="can('inventory.change_warehouse')" link type="primary" @click="openEditor('warehouse', row)">编辑</ElButton></template>
        </ElTableColumn>
      </ElTable>
    </section>
  </ElDialog>

  <ElDialog v-model="locationVisible" :title="zoneOnly ? '库区信息' : '库区与库位信息'" width="calc(100vw - 32px)" height="calc(100vh - 32px)" destroy-on-close class="warehouse-config-fullscreen">
    <section class="config-body" v-loading="loading">
      <div class="config-toolbar">
        <ElInput v-model="keyword" clearable :placeholder="zoneOnly ? '搜索仓库或库区' : '搜索仓库、库区、库位或唯一校验值'" />
        <div>
          <ElButton v-if="can('inventory.add_warehousezone')" @click="openEditor('zone')">新增库区</ElButton>
          <ElButton v-if="!zoneOnly && can('inventory.add_warehouselocation')" type="primary" :icon="Plus" @click="openEditor('location')">新增库位</ElButton>
        </div>
      </div>
      <ElTabs v-model="locationTab">
        <ElTabPane v-if="!zoneOnly" label="库位列表" name="locations">
          <ElTable :data="visibleLocations" border height="calc(100vh - 240px)">
            <ElTableColumn prop="warehouse_number" label="仓库号" min-width="100" />
            <ElTableColumn prop="warehouse_name" label="仓库名称" min-width="130" />
            <ElTableColumn prop="zone_name" label="库区" min-width="100" />
            <ElTableColumn prop="location_number" label="库位号" min-width="130" />
            <ElTableColumn prop="capacity_box_slots" label="仓库库容（箱位）" min-width="150"><template #default="{ row }">{{ row.capacity_box_slots ?? '未设置' }}</template></ElTableColumn>
            <ElTableColumn prop="occupied_box_slots" label="已占箱位" min-width="100" />
            <ElTableColumn prop="remaining_box_slots" label="剩余箱位" min-width="100"><template #default="{ row }">{{ row.remaining_box_slots ?? '不限' }}</template></ElTableColumn>
            <ElTableColumn prop="unique_key" label="库位号唯一校验" min-width="220" />
            <ElTableColumn prop="warehouse_type_display" label="仓库类型" min-width="120"><template #default="{ row }"><ElTag effect="dark" :style="warehouseTypeTagStyle(row.warehouse_type)">{{ row.warehouse_type_display }}</ElTag></template></ElTableColumn>
            <ElTableColumn prop="status_display" label="状态" min-width="90"><template #default="{ row }"><ElTag effect="dark" :style="statusTagStyle(row.status)">{{ row.status_display }}</ElTag></template></ElTableColumn>
            <ElTableColumn label="操作" width="90" fixed="right"><template #default="{ row }"><ElButton v-if="can('inventory.change_warehouselocation')" link type="primary" @click="openEditor('location', row)">编辑</ElButton></template></ElTableColumn>
          </ElTable>
        </ElTabPane>
        <ElTabPane label="库区列表" name="zones">
          <ElTable :data="visibleZones" border height="calc(100vh - 240px)">
            <ElTableColumn prop="warehouse_number" label="仓库号" min-width="120" />
            <ElTableColumn prop="warehouse_name" label="仓库名称" min-width="180" />
            <ElTableColumn prop="zone_name" label="库区" min-width="160" />
            <ElTableColumn prop="status_display" label="状态" min-width="100"><template #default="{ row }"><ElTag effect="dark" :style="statusTagStyle(row.status)">{{ row.status_display }}</ElTag></template></ElTableColumn>
            <ElTableColumn v-if="!zoneOnly" prop="location_count" label="库位数" min-width="100" />
            <ElTableColumn v-if="!zoneOnly" prop="capacity_box_slots_total" label="总箱位" min-width="120"><template #default="{ row }">{{ row.capacity_box_slots_total ?? '未设置' }}</template></ElTableColumn>
            <ElTableColumn v-if="!zoneOnly" prop="occupied_box_slots" label="已占箱位" min-width="120" />
            <ElTableColumn label="操作" width="90" fixed="right"><template #default="{ row }"><ElButton v-if="can('inventory.change_warehousezone')" link type="primary" @click="openEditor('zone', row)">编辑</ElButton></template></ElTableColumn>
          </ElTable>
        </ElTabPane>
      </ElTabs>
    </section>
  </ElDialog>

  <ElDialog v-model="editVisible" :title="`${editId ? '编辑' : '新增'}${editKind === 'warehouse' ? '仓库' : editKind === 'zone' ? '库区' : '库位'}`" width="620px" append-to-body destroy-on-close>
    <ElForm label-position="top">
      <template v-if="editKind === 'warehouse'">
        <ElFormItem label="仓库号" required><ElInput v-model="warehouseForm.warehouse_number" /></ElFormItem>
        <ElFormItem label="仓库名称" required><ElInput v-model="warehouseForm.warehouse_name" /></ElFormItem>
        <ElFormItem label="仓库类型" required><ElSelect v-model="warehouseForm.warehouse_type" disabled><ElOption label="材料仓" value="MATERIAL" /><ElOption label="半成品仓" value="SEMI_FINISHED" /><ElOption label="成品仓" value="FINISHED" /><ElOption label="不良品仓" value="DEFECTIVE" /></ElSelect></ElFormItem>
        <ElFormItem label="仓库地址"><ElInput v-model="warehouseForm.address" /></ElFormItem>
        <ElFormItem label="仓库负责人"><ElInput v-model="warehouseForm.responsible_person_name" /></ElFormItem>
        <ElFormItem label="负责人联系电话"><ElInput v-model="warehouseForm.contact_phone" /></ElFormItem>
        <ElFormItem label="状态"><ElRadioGroup v-model="warehouseForm.status"><ElRadio value="ACTIVE">正常</ElRadio><ElRadio value="DISABLED">停用</ElRadio></ElRadioGroup></ElFormItem>
      </template>
      <template v-else-if="editKind === 'zone'">
        <ElFormItem label="仓库" required><ElSelect v-model="zoneForm.warehouse" filterable><ElOption v-for="item in scopedWarehouses" :key="item.id" :label="`${item.warehouse_number} · ${item.warehouse_name}`" :value="item.id" /></ElSelect></ElFormItem>
        <ElFormItem label="库区" required><ElInput v-model="zoneForm.zone_name" /></ElFormItem>
        <ElFormItem label="状态"><ElRadioGroup v-model="zoneForm.status"><ElRadio value="ACTIVE">正常</ElRadio><ElRadio value="DISABLED">停用</ElRadio></ElRadioGroup></ElFormItem>
      </template>
      <template v-else>
        <ElFormItem label="库区" required><ElSelect v-model="locationForm.zone" filterable><ElOption v-for="item in scopedZones" :key="item.id" :label="`${item.warehouse_number} · ${item.zone_name}`" :value="item.id" /></ElSelect></ElFormItem>
        <ElFormItem label="库位号" required><ElInput v-model="locationForm.location_number" /></ElFormItem>
        <ElFormItem label="库容（箱位）"><ElInputNumber v-model="locationForm.capacity_box_slots" :min="1" /></ElFormItem>
        <ElFormItem label="状态"><ElRadioGroup v-model="locationForm.status"><ElRadio value="ACTIVE">正常</ElRadio><ElRadio value="DISABLED">停用</ElRadio></ElRadioGroup></ElFormItem>
      </template>
    </ElForm>
    <template #footer><ElButton @click="editVisible = false">取消</ElButton><ElButton type="primary" :loading="saving" @click="submitEditor">保存</ElButton></template>
  </ElDialog>
</template>

<style lang="scss" scoped>
.config-body{height:100%;padding:18px 24px;box-sizing:border-box}.config-toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:14px}.config-toolbar>.el-input{width:420px}.warehouse-owner{color:#2b73f0;font-weight:600}:global(.warehouse-config-fullscreen .el-dialog__body){height:auto;flex:1 1 auto;min-height:0;padding:0}
</style>
