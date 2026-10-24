import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import InternalSemiReceiptEntryView from './InternalSemiReceiptEntryView.vue'

const route = vi.hoisted(() => ({ query: {} as Record<string, string | string[] | null | undefined> }))
const mounted = vi.hoisted(() => ({ metal: vi.fn(), sewing: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => route }))
vi.mock('./InternalSemiReceiptView.vue', () => ({ default: { name: 'LegacyReceipt', setup: () => { mounted.sewing() }, template: '<div>原车缝页</div>' } }))
vi.mock('./MetalInternalReceiptView.vue', () => ({ default: { name: 'MetalReceipt', setup: () => { mounted.metal() }, template: '<div>新版金工页</div>' } }))

const planId = '86e0c84b-a809-4689-845b-806012ad342c'
beforeEach(() => {
  vi.clearAllMocks()
  route.query = { schedule_product_id: planId, plan_category: 'METAL' }
})

describe('既有半成品入库入口分派', () => {
  it('METAL只加载独立金工页', () => {
    route.query.plan_category = 'METAL'
    const wrapper = mount(InternalSemiReceiptEntryView)
    expect(wrapper.findComponent({ name: 'MetalReceipt' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'LegacyReceipt' }).exists()).toBe(false)
    expect(mounted.metal).toHaveBeenCalledTimes(1)
    expect(mounted.sewing).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('SEWING继续加载原页，不实例化金工页', () => {
    route.query.plan_category = 'SEWING'
    const wrapper = mount(InternalSemiReceiptEntryView)
    expect(wrapper.findComponent({ name: 'LegacyReceipt' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'MetalReceipt' }).exists()).toBe(false)
    expect(mounted.sewing).toHaveBeenCalledTimes(1)
    expect(mounted.metal).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it.each(['METAL', 'SEWING'])('%s来源缺省、非法或重复时不加载任何入库子页', category => {
    for (const source of [undefined, null, '', 'plan-1', ` ${planId}`, [planId], [planId, planId]]) {
      route.query = { schedule_product_id: source, plan_category: category }
      const wrapper = mount(InternalSemiReceiptEntryView)
      expect(wrapper.text()).toContain(`请从${category === 'METAL' ? '金工' : '车缝'}内部计划的产品行进入半成品入库`)
      expect(wrapper.findComponent({ name: 'MetalReceipt' }).exists()).toBe(false)
      expect(wrapper.findComponent({ name: 'LegacyReceipt' }).exists()).toBe(false)
      expect(wrapper.find('button').exists()).toBe(false)
      wrapper.unmount()
    }
    expect(mounted.metal).not.toHaveBeenCalled()
    expect(mounted.sewing).not.toHaveBeenCalled()
  })
  it.each([undefined, null, '', 'ASSEMBLY', 'CUTTING', 'sewing', ['METAL'], ['SEWING', 'SEWING']].map(category => [category]))('非法或重复类别 %j 不加载任何入库子页', category => {
    route.query = { schedule_product_id: planId, plan_category: category }
    const wrapper = mount(InternalSemiReceiptEntryView)
    expect(wrapper.text()).toContain('请从金工或车缝内部计划的产品行进入半成品入库')
    expect(mounted.metal).not.toHaveBeenCalled()
    expect(mounted.sewing).not.toHaveBeenCalled()
    expect(wrapper.find('button').exists()).toBe(false)
    wrapper.unmount()
  })
})
