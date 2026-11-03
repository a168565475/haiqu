import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import type { ImportPayload, ProductionTaskImport } from '@/types/productionTaskImport'
import { importedText, importedBoolean } from '@/utils/productionTaskImport'
import Panel from './ProductionTaskImportPanel.vue'

const api = vi.hoisted(() => ({ get: vi.fn(), review: vi.fn(), action: vi.fn(), source: vi.fn() }))
vi.mock('@/api/productionTaskImports', async original => ({ ...await original<typeof import('@/api/productionTaskImports')>(),
  fetchProductionTaskImport: api.get, reviewProductionTaskImport: api.review, actOnProductionTaskImport: api.action, fetchImportSources: api.source }))
const id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const payload = (): ImportPayload => ({ task_number: 'HT123', order_source: 'NEW', order_number: 'HT123', order_date: '', delivery_date: '',
  salesperson_id: '', follower_ids: [], currency_id: '', includes_tax: false, tax_rate: null, order_tolerance_percent: '', is_repeat_order: false,
  preproduction_sample_required: false, delivery_method: 'SINGLE', special_requirements_html: '', freight_amount: '0', other_fee_amount: '0', products: [], delivery_batches: [] })
const record = (state = 'REVIEW'): ProductionTaskImport => ({ id, state, phase: 'extraction', original_name: 'test.xlsx', scan_status: 'CLEAN', expires_at: '2026-11-10',
  attempt_no: 1, result_revision: 1, candidates: [], selected_candidate: {}, extraction: { fields: {}, products: [], image_candidates: [] }, matching: {}, review: {},
  issues: [], error_code: '', blocked_reason: '', saved_task_id: null, saved_task_number: '', saved_at: null, duplicates: [] })
const response = (state = 'REVIEW') => ({ data: record(state), etag: '"v1"' })
const wrappers: ReturnType<typeof mount>[] = []
async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
  await router.push({ path: '/', query: { import_id: id } }); await router.isReady()
  const wrapper = mount(Panel, { props: { payload: payload(), appliedId: id, hasEdits: false, displayValue: (_key: string, value: unknown) => String(value) },
    global: { plugins: [ElementPlus, router] } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); setActivePinia(createPinia()); api.get.mockResolvedValue(response()); api.review.mockResolvedValue(response()) })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks() })
describe('生产任务导入核对边界（模拟 API 的组件测试）', () => {
  it('缺失和冲突不预填，明确的零价格和 false 保留语义', () => {
    expect(importedText({ status: 'MISSING', value: null, source_ids: [] })).toBe('')
    expect(importedText({ status: 'CONFLICT', value: '100', source_ids: ['source'] })).toBe('')
    expect(importedText({ status: 'EXTRACTED', value: '0', source_ids: ['source'] })).toBe('0')
    expect(importedBoolean({ status: 'EXTRACTED', value: false, source_ids: ['source'] })).toBe(false)
  })
  it('未核对不保存，并且没有提交 PMC 操作', async () => {
    const wrapper = await render()
    await expect(wrapper.vm.saveReview(true)).rejects.toThrow('逐项确认')
    expect(api.review).not.toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('保存并提交 PMC')
  })
  it('修改已确认字段会取消确认，核对稿不含合同预留值', async () => {
    const wrapper = await render()
    for (const checkbox of wrapper.findAllComponents({ name: 'ElCheckbox' })) checkbox.vm.$emit('change', true)
    await flushPromises()
    await wrapper.vm.saveReview(true)
    expect(api.review.mock.calls[0]![1].payload).not.toHaveProperty('contract_number')
    await wrapper.setProps({ payload: { ...payload(), task_number: 'HT124' } })
    await expect(wrapper.vm.saveReview(true)).rejects.toThrow('逐项确认')
  })
  it('关键冲突不能以待办保存', async () => {
    const result = response(); result.data.issues = [{ id: 'issue_0', type: 'CONFLICT', blocking: true, message: '尺寸冲突', source_ids: [], field_path: null }]
    api.get.mockResolvedValue(result)
    const wrapper = await render()
    for (const checkbox of wrapper.findAllComponents({ name: 'ElCheckbox' })) checkbox.vm.$emit('change', true)
    await flushPromises()
    await expect(wrapper.vm.saveReview(true)).rejects.toThrow('关键冲突')
  })
  it('解析时轮询，卸载后不继续请求', async () => {
    api.get.mockResolvedValue(response('PARSING'))
    const wrapper = await render()
    await vi.advanceTimersByTimeAsync(2100)
    expect(api.get).toHaveBeenCalledTimes(2)
    wrapper.unmount(); wrappers.splice(wrappers.indexOf(wrapper), 1)
    await vi.advanceTimersByTimeAsync(6000)
    expect(api.get).toHaveBeenCalledTimes(2)
  })
  it('身份变更清除来源并忽略迟到响应', async () => {
    let finish!: (value: ReturnType<typeof response>) => void
    api.get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await render()
    useAuthStore().identityGeneration++
    await flushPromises(); finish(response()); await flushPromises()
    expect(wrapper.text()).not.toContain('test.xlsx')
    expect(wrapper.emitted('clear')).toHaveLength(1)
  })
  it('离开当前导入后，迟到的动作不能恢复旧记录或改写路由', async () => {
    let finish!: (value: ReturnType<typeof response>) => void
    api.action.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await render()
    await wrapper.findAll('button').find(button => button.text() === '取消本次解析')!.trigger('click')
    await wrapper.vm.$router.replace({ query: {} }); await flushPromises()
    finish(response('CANCELED')); await flushPromises()
    expect(wrapper.vm.$route.query.import_id).toBeUndefined()
    expect(wrapper.text()).not.toContain('test.xlsx')
    expect(wrapper.text()).toContain('上传并解析')
  })
  it('切换导入后，迟到来源不会打开旧文件', async () => {
    let finish!: (value: object) => void
    api.source.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await render()
    await wrapper.findAll('button').find(button => button.text() === '查看来源')!.trigger('click')
    await wrapper.vm.$router.replace({ query: {} }); await flushPromises()
    finish({ source_index: {}, private_source: 'old-content' }); await flushPromises()
    expect(wrapper.findComponent({ name: 'ElDialog' }).props('modelValue')).toBe(false)
    expect(wrapper.text()).not.toContain('old-content')
  })
})
