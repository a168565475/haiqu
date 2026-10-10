import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FactoryDetailView from './FactoryDetailView.vue'

const api = vi.hoisted(() => ({ factory: vi.fn(), options: vi.fn(), orders: vi.fn(), update: vi.fn(), push: vi.fn() }))
const permissions = vi.hoisted(() => ({ viewOrders: true }))
vi.mock('@/api/outsourcing', () => ({ fetchOutsourcingFactory: api.factory, fetchOutsourcingFactoryOptions: api.options, updateOutsourcingFactory: api.update }))
vi.mock('@/api/unifiedOutsourcing', async original => ({ ...await original<object>(), fetchUnifiedOutsourcingOrders: api.orders }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: (permission: string) => permissions.viewOrders && permission === 'outsourcing.view_outsourcingorder' }) }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { factoryId: 'factory-1' } }), useRouter: () => ({ push: api.push }) }))
vi.mock('@/components/outsourcing/FactoryFormDialog.vue', () => ({ default: { template: '<div />' } }))

const wrappers: ReturnType<typeof mount>[] = []
const row = {
  id: 'rework-1', row_key: 'REWORK:rework-1', record_type: 'REWORK', detail_access: 'METAL',
  order_number: 'WF-REWORK-001', schedule_number: 'PC-001', product: { product_name: '椅子' }, product_count: 1,
  source_label: '重加工件', status: 'PENDING_HANDOFF', status_display: '待交接', delivery_date: null,
  dispatched_quantities: [{ quantity: '183.75', unit: '米' }], returned_quantities: [{ quantity: '120', unit: '套' }],
}

beforeEach(() => {
  vi.resetAllMocks()
  permissions.viewOrders = true
  api.factory.mockResolvedValue({ data: { id: 'factory-1', name: '测试加工厂', crafts: [], created_at: '2026-09-27', updated_at: '2026-09-27' }, etag: 'v1' })
  api.options.mockResolvedValue({ crafts: [] })
  api.orders.mockResolvedValue({ data: [row], meta: { total: 1 } })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

async function createView() {
  const wrapper = mount(FactoryDetailView, { global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

describe('加工厂关联统一外发单', () => {
  it('按加工厂查询统一接口，重加工单可进入自己的详情', async () => {
    const wrapper = await createView()
    expect(api.orders).toHaveBeenCalledWith({ factory_id: 'factory-1', page: 1, page_size: 20 })
    expect(wrapper.text()).toContain('重加工件')
    const button = wrapper.findAll('button').find(item => item.text() === '查看详情')
    await button!.trigger('click')
    expect(api.push).toHaveBeenCalledWith('/workshop/outsourcing/rework/rework-1')
  })

  it('本厂实发和合格回货分别携带单位，不显示跨单位未回差额', async () => {
    const wrapper = await createView()
    expect(wrapper.text()).toContain('183.75 米')
    expect(wrapper.text()).toContain('120 套')
    expect(wrapper.text()).not.toContain('未回数量')
  })

  it('关联单读取失败保留加工厂基础信息并提供单独重试', async () => {
    api.orders.mockRejectedValueOnce(new Error('network'))
    const wrapper = await createView()
    expect(wrapper.text()).toContain('测试加工厂')
    expect(wrapper.text()).toContain('关联外发单加载失败')
    expect(wrapper.text()).not.toContain('加工厂详情加载失败')
    await (wrapper.vm as any).loadRelatedOrders()
    expect(wrapper.text()).toContain('WF-REWORK-001')
  })

  it('只有加工厂权限时不请求外发数据', async () => {
    permissions.viewOrders = false
    const wrapper = await createView()
    expect(api.orders).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('暂无外发单查看权限')
    expect(wrapper.text()).toContain('测试加工厂')
  })
})
