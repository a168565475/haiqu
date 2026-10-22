import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProductionTimeline from './ProductionTimeline.vue'

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), push: vi.fn() }))
vi.mock('@/api/productionTimeline', () => ({ fetchProductionTimeline: mocks.fetch }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }) }))
const event = { id: 'audit:1', kind: 'PRODUCTION_TASK', title: '创建 · 生产任务单', actor_name: '张三', occurred_at: '2026-10-22T01:00:00Z', document_number: 'HT001', detail_path: '/production-tasks/1', changes: [] }
const wrappers: ReturnType<typeof mount>[] = []
async function view() {
  const wrapper = mount(ProductionTimeline, { props: { scheduleId: 'schedule-1', revision: 1 }, global: {
    plugins: [ElementPlus], stubs: { AppWindowDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' } },
  } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
beforeEach(() => { vi.resetAllMocks(); mocks.fetch.mockResolvedValue({ data: [event], meta: { total: 1, page: 1, page_size: 20 } }) })
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))
describe('生产事件时间轴', () => {
  it('显示操作人时间事项，打开事件及关联单据', async () => {
    const wrapper = await view()
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).toContain('09:00:00')
    await wrapper.get('button[aria-label^="查看详情"]').trigger('click')
    await wrapper.findAll('button').find(button => button.text() === '打开关联单据')!.trigger('click')
    expect(mocks.push).toHaveBeenCalledWith('/production-tasks/1')
  })
  it('搜索传给接口，分页保持查询条件', async () => {
    const wrapper = await view()
    await wrapper.get('input').setValue('张三')
    await wrapper.get('input').trigger('keyup.enter')
    await flushPromises()
    expect(mocks.fetch).toHaveBeenLastCalledWith('schedule-1', { page: 1, page_size: 20, search: '张三' })
  })
  it('失败保留已有记录并允许重试，不把失败显示为无记录', async () => {
    const wrapper = await view()
    mocks.fetch.mockRejectedValueOnce(new Error('network'))
    await wrapper.findAll('button').find(button => button.text() === '刷新')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('事件记录加载失败')
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).not.toContain('暂无可查看')
  })
})
