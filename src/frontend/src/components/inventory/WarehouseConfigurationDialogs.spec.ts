import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import ElementPlus, { ElMessage } from 'element-plus'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { Warehouse, WarehouseLocation, WarehouseType, WarehouseZone } from '@/types/inventory'
import WarehouseConfigurationDialogs from './WarehouseConfigurationDialogs.vue'

const api = vi.hoisted(() => ({
  warehouses: vi.fn(), zones: vi.fn(), locations: vi.fn(), versioned: vi.fn(),
  saveWarehouse: vi.fn(), saveZone: vi.fn(), saveLocation: vi.fn(),
}))
const auth = vi.hoisted(() => ({ hasPermission: vi.fn(), user: { is_superuser: false } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('@/api/inventory', () => ({
  fetchWarehouses: api.warehouses, fetchZones: api.zones, fetchLocations: api.locations,
  fetchVersioned: api.versioned, saveWarehouse: api.saveWarehouse, saveZone: api.saveZone, saveLocation: api.saveLocation,
}))

// 保留真实表格、表单和组件逻辑，仅替换窗口容器，避免测试依赖拖动与传送层。
const Dialog = defineComponent({
  name: 'ElDialog', inheritAttrs: false, props: { modelValue: Boolean, title: String },
  template: '<section v-if="modelValue" :data-title="title"><slot/><footer><slot name="footer"/></footer></section>',
})
const warehouses: Warehouse[] = (['MATERIAL', 'SEMI_FINISHED', 'FINISHED', 'DEFECTIVE'] as const).map(type => ({
  id: type, warehouse_number: `${type}-01`, warehouse_name: `${type}仓库`, warehouse_type: type,
  warehouse_type_display: type, address: '一号楼', status: 'ACTIVE', status_display: '正常',
  responsible_person_name: '仓管员', contact_phone: '010-12345678', zone_count: 1, location_count: 1,
  capacity_box_slots_total: 20, occupied_box_slots: 3, updated_at: '',
}))
const zones: WarehouseZone[] = warehouses.map(warehouse => ({
  id: `${warehouse.id}-zone`, warehouse: warehouse.id, warehouse_number: warehouse.warehouse_number,
  warehouse_name: warehouse.warehouse_name, zone_name: `${warehouse.id}区`, status: 'ACTIVE', status_display: '正常',
  location_count: 1, capacity_box_slots_total: 20, occupied_box_slots: 3, updated_at: '',
}))
const locations: WarehouseLocation[] = zones.map((zone, index) => ({
  id: `${zone.id}-location`, zone: zone.id, warehouse_id: zone.warehouse, warehouse_number: zone.warehouse_number,
  warehouse_name: zone.warehouse_name, zone_name: zone.zone_name, location_number: `${zone.warehouse}-L01`,
  capacity_box_slots: 20, occupied_box_slots: 3, remaining_box_slots: 17, unique_key: `${zone.id}:L01`,
  warehouse_type: warehouses[index]!.warehouse_type, warehouse_type_display: warehouses[index]!.warehouse_type_display,
  status: 'ACTIVE', status_display: '正常', updated_at: '',
}))
const finishedWarehouse = warehouses[2]!
const finishedZone = zones[2]!
const finishedLocation = locations[2]!
let wrapper: VueWrapper<InstanceType<typeof WarehouseConfigurationDialogs>>

function render(warehouseType: WarehouseType = 'FINISHED') {
  wrapper = mount(WarehouseConfigurationDialogs, {
    props: { warehouseType }, global: { plugins: [ElementPlus], stubs: { ElDialog: Dialog } },
  })
  return wrapper
}
function tableFor(id: string) {
  return wrapper.findAllComponents({ name: 'ElTable' }).find(table => table.props('data')[0]?.id === id)!
}
async function clickButton(text: string) {
  await wrapper.findAll('button').find(button => button.text() === text)!.trigger('click')
  await flushPromises()
}

beforeEach(() => {
  vi.resetAllMocks()
  auth.hasPermission.mockReturnValue(true)
  auth.user.is_superuser = false
  api.warehouses.mockResolvedValue(warehouses)
  api.zones.mockResolvedValue(zones)
  api.locations.mockResolvedValue(locations)
  api.saveWarehouse.mockResolvedValue({})
  api.saveZone.mockResolvedValue({})
  api.saveLocation.mockResolvedValue({})
})
afterEach(() => { wrapper?.unmount(); ElMessage.closeAll(); vi.restoreAllMocks() })

it('成品配置按仓库类型及父子关系过滤，保留箱位、负责人和库位唯一校验字段', async () => {
  render()
  expect(api.warehouses).not.toHaveBeenCalled()
  await wrapper.vm.open('warehouse')
  await flushPromises()
  const warehouseTable = tableFor(finishedWarehouse.id)
  expect(warehouseTable.props('data')).toEqual([finishedWarehouse])
  expect(warehouseTable.text()).toContain('仓库负责人')
  expect(warehouseTable.text()).toContain('负责人联系电话')
  expect(warehouseTable.text()).toContain('总箱位')
  expect(warehouseTable.text()).toContain('已占箱位')
  await wrapper.vm.open('location')
  await flushPromises()
  expect(tableFor(finishedZone.id).props('data')).toEqual([finishedZone])
  const locationTable = tableFor(finishedLocation.id)
  expect(locationTable.props('data')).toEqual([finishedLocation])
  for (const label of ['仓库库容（箱位）', '已占箱位', '剩余箱位', '库位号唯一校验']) expect(locationTable.text()).toContain(label)
  expect(locationTable.text()).toContain(finishedLocation.unique_key)
  const search = wrapper.get('input[placeholder="搜索仓库、库区、库位或唯一校验值"]')
  await search.setValue('MATERIAL')
  expect(wrapper.findAllComponents({ name: 'ElTable' }).every(table => table.props('data').length === 0)).toBe(true)
})

it('MATERIAL 消费者仍只显示材料仓和库区，不出现库位或箱位操作', async () => {
  render('MATERIAL')
  await wrapper.vm.open('warehouse')
  await wrapper.vm.open('location')
  await flushPromises()
  expect(tableFor('MATERIAL').props('data')).toEqual([warehouses[0]])
  expect(tableFor('MATERIAL-zone').props('data')).toEqual([zones[0]])
  expect(wrapper.findAllComponents({ name: 'ElTabs' })[0]!.props('modelValue')).toBe('zones')
  for (const text of ['库位列表', '新增库位', '总箱位', '已占箱位']) expect(wrapper.text()).not.toContain(text)
  expect(wrapper.text()).toContain('新增库区')
  await clickButton('新增仓库')
  expect(wrapper.findComponent({ name: 'ElSelect' }).props('modelValue')).toBe('MATERIAL')
})

it('只读权限仍可看配置，但没有新增或编辑按钮', async () => {
  auth.hasPermission.mockImplementation((permission: string) => permission.startsWith('inventory.view_'))
  render()
  await wrapper.vm.open('warehouse')
  await wrapper.vm.open('location')
  await flushPromises()
  const buttons = wrapper.findAll('button').map(button => button.text())
  for (const text of ['新增仓库', '新增库区', '新增库位', '编辑']) expect(buttons).not.toContain(text)
  expect(api.saveWarehouse).not.toHaveBeenCalled()
  expect(api.saveZone).not.toHaveBeenCalled()
  expect(api.saveLocation).not.toHaveBeenCalled()
})

it.each([
  { kind: 'warehouse', resource: 'warehouses/', row: finishedWarehouse, save: api.saveWarehouse, payload: {
    warehouse_number: finishedWarehouse.warehouse_number, warehouse_name: finishedWarehouse.warehouse_name,
    warehouse_type: 'FINISHED', address: '一号楼', responsible_person_name: '仓管员', contact_phone: '010-12345678', status: 'ACTIVE',
  } },
  { kind: 'zone', resource: 'warehouse-zones/', row: finishedZone, save: api.saveZone, payload: {
    warehouse: 'FINISHED', zone_name: 'FINISHED区', status: 'ACTIVE',
  } },
  { kind: 'location', resource: 'warehouse-locations/', row: finishedLocation, save: api.saveLocation, payload: {
    zone: 'FINISHED-zone', location_number: 'FINISHED-L01', capacity_box_slots: 20, status: 'ACTIVE',
  } },
])('$kind 编辑保留完整字段及 ETag，成功后重载配置并通知页面', async ({ kind, resource, row, save, payload }) => {
  api.versioned.mockResolvedValue({ data: row, etag: '"version-2"' })
  render()
  await wrapper.vm.open(kind === 'warehouse' ? 'warehouse' : 'location')
  await flushPromises()
  const table = tableFor(row.id)
  await table.findAll('button').find(button => button.text() === '编辑')!.trigger('click')
  await flushPromises()
  expect(api.versioned).toHaveBeenCalledWith(`${resource}${row.id}/`)
  if (kind === 'location') {
    expect(wrapper.findComponent({ name: 'ElInputNumber' }).props('modelValue')).toBe(20)
  }
  await clickButton('保存')
  expect(save).toHaveBeenCalledWith(row.id, payload, '"version-2"')
  expect(api.warehouses).toHaveBeenCalledTimes(2)
  expect(api.zones).toHaveBeenCalledTimes(2)
  expect(api.locations).toHaveBeenCalledTimes(2)
  expect(wrapper.emitted('saved')).toHaveLength(1)
})

it('新增成品仓保留固定类型，必填未填时不请求保存', async () => {
  const warning = vi.spyOn(ElMessage, 'warning')
  render()
  await wrapper.vm.open('warehouse')
  await flushPromises()
  await clickButton('新增仓库')
  const typeSelect = wrapper.findComponent({ name: 'ElSelect' })
  expect(typeSelect.props('modelValue')).toBe('FINISHED')
  expect(typeSelect.props('disabled')).toBe(true)
  await clickButton('保存')
  expect(warning).toHaveBeenCalledWith('请填写仓库号和仓库名称。')
  expect(api.saveWarehouse).not.toHaveBeenCalled()
  for (const [label, value] of [['仓库号', 'FG-NEW'], ['仓库名称', '新增成品仓']]) {
    await wrapper.findAllComponents({ name: 'ElFormItem' }).find(item => item.props('label') === label)!.get('input').setValue(value)
  }
  await clickButton('保存')
  expect(api.saveWarehouse).toHaveBeenCalledWith(null, expect.objectContaining({ warehouse_type: 'FINISHED', warehouse_number: 'FG-NEW', warehouse_name: '新增成品仓' }), '')
  expect(wrapper.emitted('saved')).toHaveLength(1)
})

it('版本冲突保留编辑内容且不发出保存成功事件', async () => {
  const error = vi.spyOn(ElMessage, 'error')
  api.versioned.mockResolvedValue({ data: finishedLocation, etag: '"old-version"' })
  api.saveLocation.mockRejectedValue({ response: { status: 412, data: { error: { message: '配置已被其他人修改。' } } } })
  render()
  await wrapper.vm.open('location')
  await flushPromises()
  await tableFor(finishedLocation.id).findAll('button').find(button => button.text() === '编辑')!.trigger('click')
  await flushPromises()
  await clickButton('保存')
  expect(error).toHaveBeenCalledWith('配置已被其他人修改。')
  expect(wrapper.find('[data-title="编辑库位"]').exists()).toBe(true)
  expect(wrapper.findComponent({ name: 'ElInputNumber' }).props('modelValue')).toBe(20)
  expect(wrapper.emitted('saved')).toBeUndefined()
  expect(api.locations).toHaveBeenCalledOnce()
})
