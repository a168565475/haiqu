import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import InternalSemiReceiptEntryView from './InternalSemiReceiptEntryView.vue'

const route = vi.hoisted(() => ({ query: { schedule_product_id: 'plan-1', plan_category: 'METAL' } }))
vi.mock('vue-router', () => ({ useRoute: () => route }))
vi.mock('./InternalSemiReceiptView.vue', () => ({ default: { name: 'LegacyReceipt', template: '<div>原车缝页</div>' } }))
vi.mock('./MetalInternalReceiptView.vue', () => ({ default: { name: 'MetalReceipt', template: '<div>新版金工页</div>' } }))

describe('既有半成品入库入口分派', () => {
  it('METAL只加载独立金工页', () => {
    route.query.plan_category = 'METAL'
    const wrapper = mount(InternalSemiReceiptEntryView)
    expect(wrapper.findComponent({ name: 'MetalReceipt' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'LegacyReceipt' }).exists()).toBe(false)
    wrapper.unmount()
  })
  it('SEWING继续加载原页，不实例化金工页', () => {
    route.query.plan_category = 'SEWING'
    const wrapper = mount(InternalSemiReceiptEntryView)
    expect(wrapper.findComponent({ name: 'LegacyReceipt' }).exists()).toBe(true)
    expect(wrapper.findComponent({ name: 'MetalReceipt' }).exists()).toBe(false)
    wrapper.unmount()
  })
})
