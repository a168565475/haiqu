import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/inventory'
import * as sourceApi from '@/api/inventoryMaterialSources'
import MaterialInboundDetailView from './MaterialInboundDetailView.vue'
import MaterialTransferForm from '@/components/inventory/MaterialTransferForm.vue'

const identity = vi.hoisted(() => ({ user: { is_superuser: false, display_name: '测试操作人', employee: { display_name: '测试操作人' } }, canReadAccessDirectory: false,
  permissions: [] as string[], hasPermission(code: string) { return this.permissions.includes(code) } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => identity }))
vi.mock('@/api/inventory', () => ({ fetchMaterialReceivingOptions: vi.fn(), createMaterialTransfer: vi.fn() }))
vi.mock('@/api/inventoryMaterialSources', () => ({ fetchInboundMaterialOptions: vi.fn(), fetchInboundMaterials: vi.fn(), fetchInboundMaterial: vi.fn(), fetchInboundPublicOptions: vi.fn() }))
const wrappers: ReturnType<typeof mount>[] = []

async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/inventory/material-transfers', name: 'material-transfers', component: MaterialInboundDetailView },
    { path: '/inventory/material-transfer-records', name: 'material-inbound-records', component: { template: '<div />' } },
  ] })
  await router.push({ name: 'material-transfers' })
  const wrapper = mount(MaterialInboundDetailView, { global: { plugins: [router, ElementPlus] } })
  wrappers.push(wrapper); await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.clearAllMocks(); identity.permissions = ['inventory.receive_material']
  vi.mocked(api.fetchMaterialReceivingOptions).mockResolvedValue({ warehouses: [], zones: [] })
  vi.mocked(sourceApi.fetchInboundMaterialOptions).mockResolvedValue({ categories: [], spray_fields: [], units: [], warehouses: [] })
  vi.mocked(sourceApi.fetchInboundMaterials).mockResolvedValue({ data: [], meta: { page: 1, page_size: 200, total: 0, total_pages: 0 } })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('材料收发页面', () => {
  it('材料收发操作页移除通用记录入口', async () => {
    identity.permissions.push('inventory.view_material_receipt')
    const { wrapper, router } = await render()
    expect(wrapper.find('header.transfer-header button').exists()).toBe(false)
    expect(router.currentRoute.value.name).toBe('material-transfers')
  })

  it('直接展示筛选区和无弹窗的入库/出库共用表格', async () => {
    const { wrapper } = await render()
    expect(wrapper.get('h1').text()).toBe('材料收发')
    expect(wrapper.find('.erp-list-filter').exists()).toBe(true)
    expect(wrapper.find('[data-testid="transfer-direction-filter"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="transfer-section-filter"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="material-selection-panel"]').exists()).toBe(false)
    expect(wrapper.findAll('.el-dialog').length).toBe(0)
    expect(wrapper.findAll('th').map(item => item.text())).toContain('入库数量')
    expect(wrapper.findAll('th').map(item => item.text())).toContain('品名')
    expect(wrapper.find('[aria-label="操作人"]').exists()).toBe(true)
    expect(wrapper.find('header.transfer-header button').exists()).toBe(false)
    expect(wrapper.find('.table-footer').exists()).toBe(false)
    expect(wrapper.get('footer.transfer-footer').findAll('button').map(button => button.text())).toEqual(['保存入库'])
  })

  it('可以添加行和复制行', async () => {
    const { wrapper } = await render()
    expect(wrapper.findAll('th').map(item => item.text())).toContain('入库数量')
    const add = wrapper.findAll('button').find(item => item.text() === '添加一行')!
    await add.trigger('click')
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    const copy = wrapper.find('[aria-label="复制行"]')
    expect(copy.exists()).toBe(true)
    await copy.trigger('click')
    expect(wrapper.findAll('tbody tr')).toHaveLength(3)
  })

  it('切换分区会清空旧明细并保留当前分区空行，添加按钮位于表格上方', async () => {
    const { wrapper } = await render()
    const vm = wrapper.findComponent(MaterialTransferForm).vm as unknown as {
      rows: Array<{ key: string; category: string; quantity: string; catalogId: string; attributes: Record<string, string> }>
    }
    const oldKey = vm.rows[0]!.key
    Object.assign(vm.rows[0]!, { catalogId: 'old-material', attributes: { material: '铁' } })
    await wrapper.get('input[aria-label="第 1 行数量"]').setValue('3')
    const add = wrapper.get('.table-toolbar button')
    await add.trigger('click')
    await wrapper.get('.filter-remark input').setValue('盘点备注')
    const section = wrapper.findAllComponents(ElSelect).find(item => item.attributes('data-testid') === 'transfer-section-filter')!
    section.vm.$emit('update:modelValue', 'hardware')
    section.vm.$emit('change', 'hardware')
    await flushPromises()
    expect(vm.rows).toHaveLength(1)
    expect(vm.rows[0]).toMatchObject({ category: 'hardware', quantity: '', catalogId: '', attributes: {} })
    expect(vm.rows[0]!.key).not.toBe(oldKey)
    expect(wrapper.find('[aria-label="材料搜索"]').exists()).toBe(false)
    expect((wrapper.get('.filter-remark input').element as HTMLInputElement).value).toBe('盘点备注')
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expect(wrapper.findAll('th').map(item => item.text())).not.toContain('管材重量（kg）')
    const toolbar = wrapper.get('.erp-list-data .table-toolbar')
    expect(toolbar.text()).toContain('添加一行')
    expect(toolbar.element.nextElementSibling).toBe(wrapper.get('.erp-list-table-frame').element)
    expect(wrapper.find('.erp-list-filter .el-button').exists()).toBe(false)
    await add.trigger('click')
    expect(vm.rows.map(row => row.category)).toEqual(['hardware', 'hardware'])
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    section.vm.$emit('update:modelValue', 'tube')
    section.vm.$emit('change', 'tube')
    await flushPromises()
    expect(vm.rows).toHaveLength(1)
    expect(vm.rows[0]).toMatchObject({ category: 'tube', quantity: '', catalogId: '' })
  })

  it('只读用户只能看到无权提示，不加载收发选项', async () => {
    identity.permissions = ['inventory.view_material_receipt']
    const { wrapper } = await render()
    expect(wrapper.text()).toContain('没有材料收发权限')
    expect(api.fetchMaterialReceivingOptions).not.toHaveBeenCalled()
    expect(sourceApi.fetchInboundMaterialOptions).not.toHaveBeenCalled()
  })
})
