import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import WarehouseOutsourcingActionDialog from './WarehouseOutsourcingActionDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { UnifiedOutsourcingOrder } from '@/types/unifiedOutsourcing'
import type { TubeOrderDetail } from '@/types/tubeOutsourcing'
import type { VersionedOutsourcingOrder } from '@/types/outsourcing'

const calls = vi.hoisted(() => ({ tube: vi.fn(), regular: vi.fn(), receiptCanClose: true }))
const route = reactive({ meta: { outsourcingWorkspace: 'warehouse' } as Record<string, string> })
vi.mock('vue-router', () => ({ useRoute: () => route }))
vi.mock('@/stores/auth', async () => {
  const { reactive } = await import('vue')
  const state = reactive({ user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 1, identityRequestGeneration: 1 })
  return { useAuthStore: () => state }
})
vi.mock('@/api/tubeOutsourcing', () => ({ fetchTubeOrder: calls.tube }))
vi.mock('@/api/outsourcing', () => ({ fetchOutsourcingOrder: calls.regular }))
vi.mock('./TubeOutsourcingPlanDetail.vue', () => ({ default: {
  name: 'TubeOutsourcingPlanDetail', props: { order: Object, warehouse: Boolean, actionOnly: Boolean, blocked: Boolean, entryAction: String },
  emits: ['updated', 'refresh', 'closed'], template: '<div data-testid="plan-action" />',
} }))
vi.mock('./OutsourcingFlowActions.vue', () => ({ default: {
  name: 'OutsourcingFlowActions', props: { detail: Object, etag: String, entryAction: String, hideTriggers: Boolean },
  emits: ['updated', 'closed'], template: '<div data-testid="regular-action" />',
} }))
vi.mock('@/views/outsourcing/TubeOutsourcingDetailView.vue', () => ({ default: {
  name: 'TubeOutsourcingDetailView', props: { orderId: String, entryAction: String, actionOnly: Boolean },
  emits: ['updated', 'closed'], template: '<div data-testid="legacy-dispatch" />',
} }))
vi.mock('@/views/inventory/TubeCoatingReceiptView.vue', async () => {
  const { defineComponent } = await import('vue')
  return { default: defineComponent({
    name: 'TubeCoatingReceiptView', props: { orderId: String, embedded: Boolean }, emits: ['updated', 'closed'],
    setup(_, { expose }) { expose({ canClose: () => calls.receiptCanClose }) },
    template: '<div data-testid="legacy-receipt" />',
  }) }
})
vi.mock('@/views/outsourcing/MetalProcessingP4View.vue', () => ({ default: {
  name: 'MetalProcessingP4View', props: { mode: String, originalOrderId: String, externalOrderId: String, entryAction: String, actionOnly: Boolean },
  emits: ['updated', 'closed'], template: '<div data-testid="metal-action" />',
} }))
vi.mock('@/components/common/AppWindowDialog.vue', async () => {
  const { defineComponent } = await import('vue')
  return { default: defineComponent({
    name: 'AppWindowDialog', props: ['modelValue', 'title', 'width', 'beforeClose'], emits: ['update:modelValue'],
    setup(props, { emit }) {
      const requestClose = () => {
        const done = () => emit('update:modelValue', false)
        if (props.beforeClose) props.beforeClose(done)
        else done()
      }
      return { requestClose }
    },
    template: '<section v-if="modelValue" :aria-label="title"><button data-testid="window-close" @click="requestClose">关闭窗口</button><slot/><slot name="footer"/></section>',
  }) }
})

const auth = useAuthStore()
const baseRecord = {
  id: 'order-1', row_key: 'TUBE:order-1', record_type: 'TUBE', detail_access: 'TUBE',
  is_plan: true, direct_handoff: false, warehouse_actions: ['dispatch', 'return'],
} as UnifiedOutsourcingOrder
// 子组件在本文件使用替身；这里只核宿主分流、读接口参数、版本传递及生命周期。
const latestPlan = { id: 'order-1', is_plan: true, etag: 'fresh-plan-v2' } as TubeOrderDetail
const latestRegular = { data: { id: 'order-1' }, etag: 'fresh-regular-v3' } as VersionedOutsourcingOrder
const wrappers: ReturnType<typeof mount>[] = []
function mountHost(record: Partial<UnifiedOutsourcingOrder> = {}, action: 'dispatch' | 'return' = 'dispatch') {
  const wrapper = mount(WarehouseOutsourcingActionDialog, {
    props: { record: { ...baseRecord, ...record }, action },
    global: {
      directives: { loading: () => undefined },
      stubs: {
        ElAlert: { props: ['title'], template: '<div role="alert">{{ title }}</div>' },
        ElButton: { props: ['loading'], template: '<button><slot/></button>' },
      },
    },
  })
  wrappers.push(wrapper)
  return wrapper
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
beforeEach(() => {
  vi.resetAllMocks(); calls.receiptCanClose = true
  Object.assign(auth, { user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 1, identityRequestGeneration: 1 })
  route.meta = { outsourcingWorkspace: 'warehouse' }
  calls.tube.mockResolvedValue(latestPlan)
  calls.regular.mockResolvedValue(latestRegular)
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('仓库列表委外动作宿主', () => {
  it.each(['dispatch', 'return'] as const)('总单%s读取仓库最新单据，再复用同一收发组件', async action => {
    const wrapper = mountHost({}, action)
    expect(wrapper.text()).toContain('正在读取最新委外单')
    await flushPromises()
    expect(calls.tube).toHaveBeenCalledExactlyOnceWith('order-1', true)
    expect(calls.regular).not.toHaveBeenCalled()
    expect(wrapper.getComponent({ name: 'TubeOutsourcingPlanDetail' }).props()).toMatchObject({ order: latestPlan, warehouse: true, actionOnly: true, entryAction: action, blocked: false })
  })
  it('普通旧单传递最新仓库详情与ETag，子组件更新与关闭可回到列表', async () => {
    const wrapper = mountHost({ record_type: 'ORIGINAL', detail_access: 'REGULAR', is_plan: false }, 'return')
    await flushPromises()
    expect(calls.regular).toHaveBeenCalledExactlyOnceWith('order-1', true)
    expect(calls.tube).not.toHaveBeenCalled()
    const child = wrapper.getComponent({ name: 'OutsourcingFlowActions' })
    expect(child.props()).toMatchObject({ detail: latestRegular.data, etag: latestRegular.etag, entryAction: 'return', hideTriggers: true })
    const updated = { ...latestRegular, etag: 'after-return' }
    child.vm.$emit('updated', updated); await flushPromises()
    expect(wrapper.emitted('updated')).toHaveLength(1)
    expect(child.props('etag')).toBe('after-return')
    child.vm.$emit('closed')
    expect(wrapper.emitted('closed')).toHaveLength(1)
  })
  it('旧管材发出沿用原详情动作，不转换为总单接口', async () => {
    const wrapper = mountHost({ is_plan: false })
    await flushPromises()
    expect(wrapper.getComponent({ name: 'TubeOutsourcingDetailView' }).props()).toMatchObject({ orderId: 'order-1', entryAction: 'dispatch', actionOnly: true })
    expect(calls.tube).not.toHaveBeenCalled(); expect(calls.regular).not.toHaveBeenCalled()
  })
  it('旧管材入库使用宽窗口和原入库页，提交中阻止关闭', async () => {
    const wrapper = mountHost({ is_plan: false }, 'return')
    await flushPromises()
    expect(wrapper.getComponent({ name: 'TubeCoatingReceiptView' }).props()).toMatchObject({ orderId: 'order-1', embedded: true })
    expect(wrapper.getComponent({ name: 'AppWindowDialog' }).props()).toMatchObject({ width: 1800, title: '外发入库' })
    calls.receiptCanClose = false
    await wrapper.get('[data-testid="window-close"]').trigger('click')
    expect(wrapper.emitted('closed')).toBeUndefined()
    calls.receiptCanClose = true
    await wrapper.get('[data-testid="window-close"]').trigger('click')
    expect(wrapper.emitted('closed')).toHaveLength(1)
  })
  it.each([
    [{ record_type: 'ORIGINAL', detail_access: 'METAL', direct_handoff: false }, 'original'],
    [{ record_type: 'ORIGINAL', detail_access: 'REGULAR', direct_handoff: true }, 'original'],
    [{ record_type: 'REWORK', detail_access: 'METAL', direct_handoff: false }, 'rework'],
  ] as const)('金工和返工使用原P4动作：%j', async (record, mode) => {
    const wrapper = mountHost({ ...record, is_plan: false }, 'return')
    await flushPromises()
    expect(wrapper.getComponent({ name: 'MetalProcessingP4View' }).props()).toMatchObject({ mode, originalOrderId: mode === 'original' ? 'order-1' : undefined, externalOrderId: mode === 'rework' ? 'order-1' : undefined, entryAction: 'return', actionOnly: true })
    expect(calls.tube).not.toHaveBeenCalled(); expect(calls.regular).not.toHaveBeenCalled()
  })
  it.each(['workshop', 'no-action', 'unverified'] as const)('%s不读取或挂载可写动作，保留关闭入口', async boundary => {
    if (boundary === 'workshop') route.meta = { outsourcingWorkspace: 'workshop' }
    if (boundary === 'unverified') Object.assign(auth, { identityReady: false })
    const wrapper = mountHost(boundary === 'no-action' ? { warehouse_actions: [] } : {})
    await flushPromises()
    expect(calls.tube).not.toHaveBeenCalled(); expect(calls.regular).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="plan-action"]').exists()).toBe(false)
    expect(wrapper.get('[role="alert"]').text()).toMatch(/身份|未开放/)
    await wrapper.get('[data-testid="window-close"]').trigger('click')
    expect(wrapper.emitted('closed')).toHaveLength(1)
  })
  it.each(['uid', 'generation', 'request', 'ready', 'unmount'] as const)('%s边界后的迟到读取不应用、不通知成功', async boundary => {
    const pending = deferred<TubeOrderDetail>()
    calls.tube.mockReturnValueOnce(pending.promise)
    const wrapper = mountHost()
    if (boundary === 'uid') auth.user!.id = 8
    if (boundary === 'generation') auth.identityGeneration++
    if (boundary === 'request') auth.identityRequestGeneration++
    if (boundary === 'ready') Object.assign(auth, { identityReady: false })
    if (boundary === 'unmount') wrapper.unmount()
    pending.resolve(latestPlan); await flushPromises()
    expect(wrapper.find('[data-testid="plan-action"]').exists()).toBe(false)
    expect(wrapper.emitted('updated')).toBeUndefined()
    expect(calls.tube).toHaveBeenCalledTimes(1)
  })
  it('读取失败显示原因，重试成功后传递最新单据', async () => {
    calls.tube.mockRejectedValueOnce(new Error('网络读取失败'))
    const wrapper = mountHost()
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe('网络读取失败')
    await wrapper.findAll('button').find(button => button.text() === '重新读取')!.trigger('click')
    await flushPromises()
    expect(calls.tube).toHaveBeenCalledTimes(2)
    expect(wrapper.getComponent({ name: 'TubeOutsourcingPlanDetail' }).props('order')).toEqual(latestPlan)
  })
  it('读取后的类型不符不进入总单动作，仍可关闭', async () => {
    calls.tube.mockResolvedValueOnce({ ...latestPlan, is_plan: false })
    const wrapper = mountHost()
    await flushPromises()
    expect(wrapper.text()).toContain('单据类型已变化')
    expect(wrapper.find('[data-testid="plan-action"]').exists()).toBe(false)
    await wrapper.get('[data-testid="window-close"]').trigger('click')
    expect(wrapper.emitted('closed')).toHaveLength(1)
  })
  it('子组件刷新时保持原组件挂载并暂停操作，返回最新版本', async () => {
    const wrapper = mountHost(); await flushPromises()
    const child = wrapper.getComponent({ name: 'TubeOutsourcingPlanDetail' })
    const pending = deferred<TubeOrderDetail>()
    calls.tube.mockReturnValueOnce(pending.promise)
    child.vm.$emit('refresh'); await flushPromises()
    expect(wrapper.getComponent({ name: 'TubeOutsourcingPlanDetail' }).vm).toBe(child.vm)
    expect(child.props('blocked')).toBe(true)
    pending.resolve({ ...latestPlan, etag: 'refreshed-v3' }); await flushPromises()
    expect(child.props('blocked')).toBe(false)
    expect(child.props('order').etag).toBe('refreshed-v3')
  })
})
