import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FactoryListView from './FactoryListView.vue'

const api = vi.hoisted(() => ({ list: vi.fn(), detail: vi.fn(), options: vi.fn(), create: vi.fn(), update: vi.fn(), disable: vi.fn(), push: vi.fn() }))
const access = vi.hoisted(() => ({ allowed: true }))
vi.mock('@/api/outsourcing', () => ({ fetchOutsourcingFactories: api.list, fetchOutsourcingFactory: api.detail, fetchOutsourcingFactoryOptions: api.options, createOutsourcingFactory: api.create, updateOutsourcingFactory: api.update, disableOutsourcingFactory: api.disable }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: () => access.allowed }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: api.push }) }))
vi.mock('@/components/outsourcing/FactoryFormDialog.vue', () => ({ default: { props: ['modelValue', 'mode', 'factory'], template: '<div v-if="modelValue" data-testid="factory-form">{{ mode }} {{ factory?.name }}</div>' } }))
vi.mock('@/components/common/AppWindowDialog.vue', () => ({ default: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' } }))

const factory = { id: 'factory-1', name: '加工厂测试', crafts: [], status: 'ACTIVE', remark: '需要完整显示的较长备注', updated_at: '2026-10-19T08:00:00Z', estimated_output: null }
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.resetAllMocks()
  access.allowed = true
  api.list.mockResolvedValue({ data: [factory], meta: { total: 1 } })
  api.options.mockResolvedValue({ crafts: [], processing_types: [] })
  api.detail.mockResolvedValue({ data: factory, etag: 'v1' })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = ''; vi.restoreAllMocks() })
async function createView() {
  const wrapper = mount(FactoryListView, { attachTo: document.body, global: { plugins: [ElementPlus], stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

describe('加工厂列表操作与备注', () => {
  it('点击更多展开菜单，不触发整行跳转；编辑读取原资料', async () => {
    const wrapper = await createView()
    await wrapper.get('button[aria-label="加工厂操作"]').trigger('click')
    await flushPromises()
    expect(api.push).not.toHaveBeenCalled()
    const edit = Array.from(document.querySelectorAll<HTMLElement>('.el-dropdown-menu__item')).find(item => item.textContent?.trim() === '编辑')
    expect(edit).toBeTruthy()
    edit!.click()
    await flushPromises()
    expect(api.detail).toHaveBeenCalledWith('factory-1')
    expect(wrapper.get('[data-testid="factory-form"]').text()).toContain('edit 加工厂测试')
    expect(api.push).not.toHaveBeenCalled()
  })

  it('普通单元格悬停显示完整备注，空备注不弹出', async () => {
    const wrapper = await createView()
    const table = wrapper.findComponent({ name: 'ElTable' })
    const cell = wrapper.get('.el-table__body td').element
    table.vm.$emit('cell-mouse-enter', factory, {}, cell)
    await flushPromises()
    expect(wrapper.findAllComponents({ name: 'ElTooltip' }).find(item => item.props('popperClass') === 'factory-remark-tooltip')?.props('content')).toBe(factory.remark)
    expect((wrapper.vm as any).remarkVisible).toBe(true)
    table.vm.$emit('cell-mouse-enter', { ...factory, remark: '' }, {}, cell)
    await flushPromises()
    expect((wrapper.vm as any).remarkVisible).toBe(false)
  })

  it('无维护权限时菜单不提供编辑和停用', async () => {
    access.allowed = false
    const wrapper = await createView()
    await wrapper.get('button[aria-label="加工厂操作"]').trigger('click')
    await flushPromises()
    const items = Array.from(document.querySelectorAll('.el-dropdown-menu__item')).map(item => item.textContent?.trim())
    expect(items).toEqual(['查看详情'])
  })
})
