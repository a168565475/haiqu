import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElInputNumber } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/purchaseTracking'
import PurchaseTrackingPolicyDialog from './PurchaseTrackingPolicyDialog.vue'

vi.mock('@/api/purchaseTracking', () => ({ fetchPurchaseTrackingPolicy: vi.fn(), updatePurchaseTrackingPolicy: vi.fn() }))
const policy = () => ({ bom_timeout_days: 2, category_lead_days: { TUBE: 2, PACKAGING: 2 }, categories: [{ key: 'TUBE', label: '管材' }, { key: 'PACKAGING', label: '包装' }], etag: 'policy-v1', can_manage: true })
let wrapper: VueWrapper | undefined
async function open(visible = true) {
  wrapper = mount(PurchaseTrackingPolicyDialog, {
    props: { modelValue: visible },
    global: { plugins: [ElementPlus], stubs: { AppWindowDialog: { props: ['modelValue'], template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>' } } },
  })
  await flushPromises()
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchPurchaseTrackingPolicy).mockResolvedValue(policy())
  vi.mocked(api.updatePurchaseTrackingPolicy).mockResolvedValue({ ...policy(), etag: 'policy-v2' })
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('采购提醒设置', () => {
  it('打开时才读取规则，关闭未保存不写入，重开重新读取', async () => {
    await open(false)
    expect(api.fetchPurchaseTrackingPolicy).not.toHaveBeenCalled()
    await wrapper!.setProps({ modelValue: true }); await flushPromises()
    expect(wrapper!.findAllComponents(ElInputNumber).map(item => item.props('modelValue'))).toEqual([2, 2, 2])
    wrapper!.findAllComponents(ElInputNumber)[0]!.vm.$emit('update:modelValue', 5)
    await wrapper!.get('[data-testid="close-policy"]').trigger('click')
    expect(api.updatePurchaseTrackingPolicy).not.toHaveBeenCalled()
    expect(wrapper!.emitted('update:modelValue')).toEqual([[false]])
    await wrapper!.setProps({ modelValue: false }); await wrapper!.setProps({ modelValue: true }); await flushPromises()
    expect(api.fetchPurchaseTrackingPolicy).toHaveBeenCalledTimes(2)
    expect(wrapper!.findAllComponents(ElInputNumber)[0]!.props('modelValue')).toBe(2)
  })

  it('按分类保存，允许清空和零天，成功后通知列表刷新', async () => {
    await open()
    const fields = wrapper!.findAllComponents(ElInputNumber)
    fields[0]!.vm.$emit('update:modelValue', undefined)
    fields[1]!.vm.$emit('update:modelValue', 0)
    fields[2]!.vm.$emit('update:modelValue', 4)
    await wrapper!.get('[data-testid="save-policy"]').trigger('click'); await flushPromises()
    expect(api.updatePurchaseTrackingPolicy).toHaveBeenCalledWith({ bom_timeout_days: null, category_lead_days: { TUBE: 0, PACKAGING: 4 } }, 'policy-v1')
    expect(wrapper!.emitted('saved')).toEqual([[]])
    expect(wrapper!.emitted('update:modelValue')).toEqual([[false]])
  })

  it.each([412, 428])('并发冲突 %s 保留用户输入，明确重新加载才替换', async status => {
    vi.mocked(api.updatePurchaseTrackingPolicy).mockRejectedValueOnce({ response: { status } })
    await open()
    wrapper!.findAllComponents(ElInputNumber)[0]!.vm.$emit('update:modelValue', 7)
    await wrapper!.get('[data-testid="save-policy"]').trigger('click'); await flushPromises()
    expect(wrapper!.text()).toContain('输入已保留')
    expect(wrapper!.findAllComponents(ElInputNumber)[0]!.props('modelValue')).toBe(7)
    expect(wrapper!.emitted('saved')).toBeUndefined()
    expect(wrapper!.emitted('update:modelValue')).toBeUndefined()
    expect(wrapper!.get('[data-testid="save-policy"]').attributes('disabled')).toBeDefined()
    vi.mocked(api.fetchPurchaseTrackingPolicy).mockResolvedValueOnce({ ...policy(), bom_timeout_days: 3, etag: 'policy-v3' })
    await wrapper!.get('[data-testid="reload-policy"]').trigger('click'); await flushPromises()
    expect(wrapper!.findAllComponents(ElInputNumber)[0]!.props('modelValue')).toBe(3)
  })

  it('未启用显式提示且不可保存，支持重新加载', async () => {
    vi.mocked(api.fetchPurchaseTrackingPolicy).mockRejectedValueOnce({ response: { status: 503 } })
    await open()
    expect(wrapper!.text()).toContain('尚未启用')
    expect(wrapper!.get('[data-testid="save-policy"]').attributes('disabled')).toBeDefined()
    expect(wrapper!.findAllComponents(ElInputNumber)).toHaveLength(0)
    await wrapper!.get('[data-testid="reload-policy"]').trigger('click'); await flushPromises()
    expect(wrapper!.findAllComponents(ElInputNumber)).toHaveLength(3)
  })

  it('保存失败保留输入，不产生假成功', async () => {
    vi.mocked(api.updatePurchaseTrackingPolicy).mockRejectedValueOnce({ response: { status: 500 } })
    await open()
    wrapper!.findAllComponents(ElInputNumber)[1]!.vm.$emit('update:modelValue', 6)
    await wrapper!.get('[data-testid="save-policy"]').trigger('click'); await flushPromises()
    expect(wrapper!.text()).toContain('保存失败')
    expect(wrapper!.findAllComponents(ElInputNumber)[1]!.props('modelValue')).toBe(6)
    expect(wrapper!.emitted('saved')).toBeUndefined()
  })

  it.each([403, 503])('重新加载失败 %s 后保留输入并撤销保存能力，成功重载后恢复', async status => {
    vi.mocked(api.updatePurchaseTrackingPolicy).mockRejectedValueOnce({ response: { status: 500 } })
    await open()
    wrapper!.findAllComponents(ElInputNumber)[1]!.vm.$emit('update:modelValue', 6)
    await wrapper!.get('[data-testid="save-policy"]').trigger('click'); await flushPromises()
    vi.mocked(api.fetchPurchaseTrackingPolicy).mockRejectedValueOnce({ response: { status } })
    await wrapper!.get('[data-testid="reload-policy"]').trigger('click'); await flushPromises()
    expect(wrapper!.text()).toContain(status === 403 ? '无权修改' : '尚未启用')
    expect(wrapper!.findAllComponents(ElInputNumber)[1]!.props('modelValue')).toBe(6)
    expect(wrapper!.get('[data-testid="save-policy"]').attributes('disabled')).toBeDefined()
    expect(wrapper!.findAllComponents(ElInputNumber).every(item => item.props('disabled'))).toBe(true)
    expect(api.updatePurchaseTrackingPolicy).toHaveBeenCalledTimes(1)
    await wrapper!.get('[data-testid="reload-policy"]').trigger('click'); await flushPromises()
    expect(wrapper!.get('[data-testid="save-policy"]').attributes('disabled')).toBeUndefined()
    expect(wrapper!.findAllComponents(ElInputNumber)[1]!.props('modelValue')).toBe(2)
  })

  it('服务端撤销管理权限后禁止编辑与保存', async () => {
    vi.mocked(api.fetchPurchaseTrackingPolicy).mockResolvedValueOnce({ ...policy(), can_manage: false })
    await open()
    expect(wrapper!.text()).toContain('无权修改')
    expect(wrapper!.findAllComponents(ElInputNumber).every(item => item.props('disabled'))).toBe(true)
    expect(wrapper!.get('[data-testid="save-policy"]').attributes('disabled')).toBeDefined()
    expect(api.updatePurchaseTrackingPolicy).not.toHaveBeenCalled()
  })

  it('输入范围和整数约束在提交前检查', async () => {
    await open()
    wrapper!.findAllComponents(ElInputNumber)[0]!.vm.$emit('update:modelValue', 2.5)
    await wrapper!.get('[data-testid="save-policy"]').trigger('click'); await flushPromises()
    expect(wrapper!.text()).toContain('0～365')
    expect(api.updatePurchaseTrackingPolicy).not.toHaveBeenCalled()
  })

  it('保存过程中禁止重复提交和关闭，等待真实保存结果', async () => {
    let resolve!: (value: ReturnType<typeof policy>) => void
    vi.mocked(api.updatePurchaseTrackingPolicy).mockReturnValueOnce(new Promise(done => { resolve = done }))
    await open()
    await wrapper!.get('[data-testid="save-policy"]').trigger('click'); await flushPromises()
    expect(wrapper!.get('[data-testid="close-policy"]').attributes('disabled')).toBeDefined()
    expect(wrapper!.get('[data-testid="save-policy"]').attributes('disabled')).toBeDefined()
    expect(wrapper!.emitted('saved')).toBeUndefined()
    resolve(policy()); await flushPromises()
    expect(wrapper!.emitted('saved')).toEqual([[]])
  })
})
