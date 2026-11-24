import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { beforeEach, expect, it, vi } from 'vitest'
import * as api from '@/api/inventory'
import { router } from '@/router'
import MaterialInventoryView from './MaterialInventoryView.vue'
import ManualMaterialInboundDialog from '@/components/inventory/ManualMaterialInboundDialog.vue'
import FinishedGoodsInventoryView from './FinishedGoodsInventoryView.vue'

const routeState = vi.hoisted(() => ({ query: {} as Record<string, unknown> }))
vi.mock('@/router', () => ({ router: { push: vi.fn(), replace: vi.fn() } }))
vi.mock('vue-router', () => ({ useRoute: () => routeState, useRouter: () => router }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 0, identityRequestGeneration: 0, hasPermission: () => true }) }))
vi.mock('@/api/inventory', async importOriginal => {
  const original = await importOriginal<typeof api>()
  return Object.fromEntries(Object.keys(original).map(key => [key, vi.fn()]))
})
const filters = { warehouses: [], zones: [], sections: [] }
beforeEach(() => {
  vi.resetAllMocks()
  Object.keys(routeState.query).forEach(key => { delete routeState.query[key] })
  vi.mocked(api.fetchMaterialFilterOptions).mockResolvedValue({ ...filters, bom_sections: {
    RAW: [
      { key: 'TUBE', label: '管材', fields: [{ key: 'thickness', label: '厚度' }, { key: 'length', label: '单根长度' }] },
      { key: 'FABRIC', label: '面料', fields: [{ key: 'width', label: '门幅' }, { key: 'gram_weight', label: '克重' }] },
    ],
    SEMI: [
      { key: 'TUBE', label: '管材', fields: [{ key: 'cutting_length_mm', label: '切割长度（mm）' }] },
      { key: 'FABRIC_SEMI', label: '裁片', fields: [{ key: 'pieces_per_set', label: '每套片数' }] },
      { key: 'SEWN_PART', label: '部位半成品', fields: [{ key: 'size', label: '加工后尺寸' }] },
    ],
  } })
  vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue(filters)
  vi.mocked(api.fetchFinishedGoodsFilterOptions).mockResolvedValue(filters)
  vi.mocked(api.fetchMaterialInventory).mockResolvedValue({ count: 0, results: [] } as never)
  vi.mocked(api.fetchFinishedGoodsInventory).mockResolvedValue({ count: 0, results: [] })
  vi.mocked(api.fetchMaterialInboundDetails).mockResolvedValue([])
  vi.mocked(api.fetchManualMaterialOptions).mockResolvedValue({ categories: [], materials: [] })
})
it('三个库存读取页面仅加载筛选选项，明细和空列表可独立完成', async () => {
  for (const component of [MaterialInventoryView, FinishedGoodsInventoryView]) {
    const wrapper = shallowMount(component, { global: { plugins: [ElementPlus] } }); await flushPromises()
    expect((wrapper.vm as unknown as { loading: boolean }).loading).toBe(false)
    wrapper.unmount()
  }
  expect(api.fetchMaterialFilterOptions).toHaveBeenCalledTimes(1)
  expect(api.fetchFinishedGoodsFilterOptions).toHaveBeenCalledTimes(1)
  expect(api.fetchMaterialInventoryOptions).not.toHaveBeenCalled()
  expect(api.fetchInventoryOptions).not.toHaveBeenCalled()
})
it('手工入库只取材料仓和库区，未填写时不能提交', async () => {
  const wrapper = shallowMount(ManualMaterialInboundDialog, { global: { plugins: [ElementPlus] } }); await flushPromises()
  expect(api.fetchMaterialReceivingOptions).toHaveBeenCalledOnce()
  expect((wrapper.vm as unknown as { ready: boolean }).ready).toBe(false)
  expect(api.createManualMaterialReceipt).not.toHaveBeenCalled(); wrapper.unmount()
})
it('材料库存把配置放在重置旁边，移除刷新和收发记录入口', async () => {
  const wrapper = shallowMount(MaterialInventoryView, { global: { plugins: [ElementPlus], stubs: { ElButton: { template: '<button><slot /></button>' }, ElDropdown: { template: '<div><slot /></div>' } } } }); await flushPromises()
  expect(wrapper.findAll('button').some(button => button.text() === '材料入库')).toBe(false)
  expect(wrapper.findComponent(ManualMaterialInboundDialog).exists()).toBe(false)
  expect(wrapper.findAll('button').map(button => button.text())).not.toContain('收发记录')
  expect(wrapper.findAll('button').map(button => button.text())).not.toContain('刷新')
  expect(wrapper.get('.erp-list-filter-actions').findAll('button').map(button => button.text())).toEqual(['配置', '重置', '应用筛选'])
  wrapper.unmount()
})
it('材料库存旧响应和卸载后的响应失效', async () => {
  const wrapper = shallowMount(MaterialInventoryView, { global: { plugins: [ElementPlus] } }); await flushPromises()
  const vm = wrapper.vm as unknown as { loadRows: () => Promise<void>; total: number; loading: boolean }
  let finish!: (value: never) => void
  vi.mocked(api.fetchMaterialInventory).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  const pending = vm.loadRows(); vi.mocked(api.fetchMaterialInventory).mockResolvedValueOnce({ count: 2, results: [] } as never)
  await vm.loadRows(); finish({ count: 1, results: [] } as never); await pending
  expect(vm.total).toBe(2); expect(vm.loading).toBe(false)
  vi.mocked(api.fetchMaterialInventory).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  const late = vm.loadRows(); wrapper.unmount(); finish({ count: 3, results: [] } as never); await late; expect(vm.total).toBe(2)
})
it('材料库存遵循紧凑列表字段规范', async () => {
  const wrapper = shallowMount(MaterialInventoryView, { global: {
    plugins: [ElementPlus], stubs: { ElTable: { template: '<div><slot /></div>' } },
  } }); await flushPromises()
  expect(wrapper.find('.summary-grid').exists()).toBe(false)
  expect(wrapper.find('.page-heading').text()).toContain('材料库存')
  expect(wrapper.get('.inventory-table').find('.erp-list-toolbar').exists()).toBe(false)
  const sections = wrapper.get('nav[aria-label="BOM 分区"]').findAll('button')
  expect(sections.map(button => button.text())).toEqual(['管材', '面料'])
  expect(sections[0]!.attributes('aria-pressed')).toBe('true')
  expect(api.fetchMaterialInventory).toHaveBeenLastCalledWith(expect.objectContaining({ stock_kind: 'RAW', bom_section: 'TUBE', page: 1 }))
  const labels = () => wrapper.findAll('el-table-column-stub').map(column => column.attributes('label'))
  expect(labels()).toEqual(expect.arrayContaining(['厚度', '单根长度']))
  await sections[1]!.trigger('click')
  await flushPromises()
  expect(sections[1]!.attributes('aria-pressed')).toBe('true')
  expect(api.fetchMaterialInventory).toHaveBeenLastCalledWith(expect.objectContaining({ stock_kind: 'RAW', bom_section: 'FABRIC', page: 1 }))
  expect(labels()).toEqual(expect.arrayContaining(['门幅', '克重']))
  expect(labels()).not.toContain('厚度')
  const source = readFileSync(resolve(process.cwd(), 'src/views/inventory/MaterialInventoryView.vue'), 'utf8')
  expect(source).not.toContain('原材料按实物属性和库区汇总')
  expect(labels()).not.toContain('材料分类')
  expect(source).toContain('label-class-name="sequence-column"')
  expect(source).toContain("{{ row.warehouse_name || '—' }}")
  expect(labels()).not.toContain('BOM 分区')
  expect(source).not.toContain('label="原料信息"')
  expect(source).not.toContain('label="入库批次"')
  wrapper.unmount()
})
it('半成品分三个页签，喷塑筛选只作用于管材并在切出时清空', async () => {
  routeState.query.stock_kind = 'SEMI'
  const wrapper = shallowMount(MaterialInventoryView, { global: { plugins: [ElementPlus], stubs: { ElButton: { template: '<button><slot /></button>' } } } }); await flushPromises()
  expect(api.fetchMaterialInventory).toHaveBeenCalledWith(expect.objectContaining({ stock_kind: 'SEMI', bom_section: 'TUBE', processing_status: undefined }))
  const sections = wrapper.get('nav[aria-label="BOM 分区"]').findAll('button')
  expect(sections.map(button => button.text())).toEqual(['管材', '裁片', '部位半成品'])
  const coatingFilter = () => wrapper.findAllComponents(ElSelect).find(select => select.classes('filter-control--status'))
  const coating = coatingFilter()!
  coating.vm.$emit('update:modelValue', 'POWDER_COATING')
  coating.vm.$emit('change', 'POWDER_COATING')
  expect(api.fetchMaterialInventory).toHaveBeenLastCalledWith(expect.objectContaining({ bom_section: 'TUBE', processing_status: 'POWDER_COATING' }))
  for (const [index, section] of [[1, 'FABRIC_SEMI'], [2, 'SEWN_PART']] as const) {
    await sections[index]!.trigger('click')
    expect(wrapper.find('.filter-control--status').exists()).toBe(false)
    expect(api.fetchMaterialInventory).toHaveBeenLastCalledWith(expect.objectContaining({ stock_kind: 'SEMI', bom_section: section, processing_status: undefined }))
  }
  await sections[0]!.trigger('click')
  expect(coatingFilter()?.props('modelValue')).toBe('')
  expect(api.fetchMaterialInventory).toHaveBeenLastCalledWith(expect.objectContaining({ bom_section: 'TUBE', processing_status: undefined }))
  const source = readFileSync(resolve(process.cwd(), 'src/views/inventory/MaterialInventoryView.vue'), 'utf8')
  expect(source).toContain('label="加工状态"')
  expect(wrapper.findAll('button').some(button => button.text() === '喷塑入库')).toBe(false)
  expect(wrapper.findAll('button').some(button => button.text() === '入库记录')).toBe(false)
  expect(wrapper.findComponent(ManualMaterialInboundDialog).exists()).toBe(false)
  expect(source).toContain('processing_status_label')
  wrapper.unmount()
})
it('成品库存出库入口仅传递选中批次，由出库页面加载操作选项', async () => {
  const wrapper = shallowMount(FinishedGoodsInventoryView, { global: { plugins: [ElementPlus] } }); await flushPromises()
  const vm = wrapper.vm as unknown as { selectedRows: unknown[]; openOutbound: () => Promise<void> }
  vm.selectedRows = [{ task_number: 'TASK-1', receipt_ids: ['new'] }]
  await vm.openOutbound(); await flushPromises()
  expect(router.push).toHaveBeenCalledWith({ name: 'finished-goods-outbound-new', query: { receipt_ids: 'new' } })
  expect(api.fetchInventoryOptions).not.toHaveBeenCalled()
  expect(api.fetchOutboundBatches).not.toHaveBeenCalled()
  expect(api.createFinishedGoodsOutbound).not.toHaveBeenCalled(); wrapper.unmount()
})
