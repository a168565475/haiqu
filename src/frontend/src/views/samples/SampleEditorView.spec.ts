import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SampleEditorView from './SampleEditorView.vue'

const api = vi.hoisted(() => ({ fetch: vi.fn(), options: vi.fn(), products: vi.fn(), complete: vi.fn(), materials: vi.fn(), units: vi.fn(), save: vi.fn(), noMaterials: vi.fn(), push: vi.fn(), leave: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { sampleId: 'sample-1' } }), useRouter: () => ({ push: api.push }), onBeforeRouteLeave: api.leave, onBeforeRouteUpdate: vi.fn() }))
vi.mock('@/api/samples', () => ({ fetchSample: api.fetch, fetchSampleFormOptions: api.options }))
vi.mock('@/api/sampleApplication', () => ({ completeSampleApplicationProducts: api.complete, fetchSampleApplicationProductOptions: api.products }))
vi.mock('@/api/sampleMaterials', () => ({ fetchSampleMaterials: api.materials, fetchSampleMaterialUnits: api.units, saveSampleMaterials: api.save, confirmSampleNoMaterials: api.noMaterials }))

function sample(canComplete = true) {
  return { etag: '"p1"', data: {
    id: 'sample-1', request_number: 'SRQ-001', status: canComplete ? 'PENDING_COMPLETION' : 'MATERIALS_PENDING', status_display: '待完善',
    customer_name: '真实接口由实页检查', purpose: '初始要求', edit_capabilities: { mode: canComplete ? 'COMPLETE' : 'READ_ONLY', can_complete: canComplete }, application_actions: { is_application: true },
    products: [{ id: 'sp1', product_id: 'product-1', product_name: '折叠椅', specification: '椅子规格', category_id: 'cat1', category_name: '椅子',
      length_cm: '50', armrest_width_cm: null, seat_width_cm: null, back_height_cm: null, seat_height_cm: null,
      details: [{ id: 'd1', product_color_id: 'color1', color_code: '蓝色号', sample_quantity: 3, tolerance: 'NONE', notes: '' }] }],
  } }
}
function materials(canEdit = false, version = '"p1"') {
  return { available: true, canEdit, etag: version, status: canEdit ? 'MATERIALS_PENDING' : 'PENDING_COMPLETION', statusLabel: '待填写', submittedAt: null,
    draft: { lines: [{ key: 'm1', category: 'fabric', name: '面料', specification: '规格', material: '', color: '', quantity: '2', unitId: 'u1', rawMaterialId: 'raw1', notes: '' }], notes: '' } }
}
const wrappers: ReturnType<typeof mount>[] = []
async function render() {
  const wrapper = mount(SampleEditorView, { global: { plugins: [ElementPlus], stubs: { SampleMaterialApplicationInfo: true,
    AppWindowDialog: { props: ['modelValue'], template: '<div v-if="modelValue" class="product-window"><slot /><slot name="footer" /></div>' },
    SampleMaterialEditor: { props: ['modelValue', 'disabled', 'layout'], emits: ['update:modelValue'], template: '<div class="material-stub" :data-disabled="disabled" :data-layout="layout"><button :disabled="disabled" @click="$emit(\'update:modelValue\', [...modelValue, {...modelValue[0], key: \'m2\'}])">添加测试材料</button></div>' },
  } } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
function button(wrapper: ReturnType<typeof mount>, label: string) { return wrapper.findAll('button').find(item => item.text() === label)! }
beforeEach(() => {
  vi.clearAllMocks()
  api.fetch.mockResolvedValue(sample())
  api.options.mockResolvedValue({ categories: [{ id: 'cat1', category_name: '椅子' }], colors: [{ id: 'color1', color_name: '蓝', color_card: '色卡', color_code: '蓝色号' }], tolerances: [{ value: 'NONE', label: '无' }] })
  api.products.mockResolvedValue([])
  api.materials.mockResolvedValue(materials())
  api.units.mockResolvedValue([{ id: 'u1', label: '米', decimalPlaces: 2 }])
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('打样编辑：组件契约测试（Mock 不代表真实验收）', () => {
  it('产品完善前材料锁定，切换页签不丢失产品输入', async () => {
    const wrapper = await render()
    expect(wrapper.find('.product-window').exists()).toBe(false)
    expect(wrapper.find('.product-card .product-details').exists()).toBe(true)
    expect(wrapper.find('.product-card .el-form').exists()).toBe(false)
    await button(wrapper, '编辑产品信息').trigger('click')
    await wrapper.get('#sample-purpose').setValue('未保存要求')
    await button(wrapper, '返回概览').trigger('click')
    await button(wrapper, '材料需求').trigger('click')
    expect(wrapper.get('.material-stub').attributes('data-disabled')).toBe('true')
    expect(wrapper.get('.material-stub').attributes('data-layout')).toBe('sidebar')
    await button(wrapper, '申请与产品').trigger('click')
    await button(wrapper, '编辑产品信息').trigger('click')
    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('未保存要求')
    expect(api.complete).not.toHaveBeenCalled()
  })
  it('产品保存后采用新版本提交材料，并分别提示结果', async () => {
    const wrapper = await render()
    const result = sample(false); result.etag = '"p2"'
    api.complete.mockResolvedValue(result)
    api.materials.mockResolvedValue(materials(true, '"p2"'))
    await button(wrapper, '保存产品需求').trigger('click'); await flushPromises()
    expect(api.complete.mock.calls[0]![1]).toBe('"p1"')
    expect(wrapper.text()).toContain('产品需求已保存。材料需求尚未提交')
    expect(wrapper.get('.material-stub').attributes('data-disabled')).toBe('false')
    const saved = materials(false, '"p3"'); saved.status = 'WAREHOUSE_PENDING'
    api.save.mockResolvedValue(saved)
    await button(wrapper, '提交仓库').trigger('click'); await flushPromises()
    expect(api.save.mock.calls[0]![0]).toMatchObject({ sampleId: 'sample-1', etag: '"p2"', submit: true })
    expect(wrapper.text()).toContain('材料需求已提交仓库。')
  })
  it('产品保存版本冲突保留输入且不开放材料', async () => {
    const wrapper = await render()
    await button(wrapper, '编辑产品信息').trigger('click')
    await wrapper.get('#sample-purpose').setValue('冲突后保留')
    api.complete.mockRejectedValue(new AxiosError('conflict', '412', undefined, undefined, { status: 412 } as never))
    await button(wrapper, '保存产品需求').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('数据版本已变化')
    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('冲突后保留')
    expect(wrapper.get('.material-stub').attributes('data-disabled')).toBe('true')
    expect(api.save).not.toHaveBeenCalled()
  })
  it('材料保存失败保留内容，返回产品页再切回也不丢失', async () => {
    api.fetch.mockResolvedValue(sample(false)); api.materials.mockResolvedValue(materials(true))
    const wrapper = await render()
    await button(wrapper, '材料需求').trigger('click')
    await wrapper.get('#sample-material-notes').setValue('未提交备注')
    api.save.mockRejectedValue(new Error('网络故障'))
    await button(wrapper, '提交仓库').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('网络故障')
    await button(wrapper, '申请与产品').trigger('click'); await button(wrapper, '材料需求').trigger('click')
    expect((wrapper.get('#sample-material-notes').element as HTMLInputElement).value).toBe('未提交备注')
    expect(api.save.mock.calls[0]![0].draft.notes).toBe('未提交备注')
  })
  it('无完善权限与终态不出现保存操作，加载403显示错误', async () => {
    const readonly = sample(); readonly.data.edit_capabilities.can_complete = false
    api.fetch.mockResolvedValue(readonly)
    const wrapper = await render()
    expect(wrapper.findAll('button').some(item => item.text() === '保存产品需求')).toBe(false)
    expect(api.options).not.toHaveBeenCalled()
    await button(wrapper, '查看产品信息').trigger('click')
    expect(wrapper.get('#sample-purpose').attributes('disabled')).toBeDefined()
    api.fetch.mockRejectedValue(new AxiosError('forbidden', '403', undefined, undefined, { status: 403 } as never))
    expect((await render()).text()).toContain('当前账号没有此操作权限')
  })
  it('产品成功但材料重载失败分别显示结果，不误称全部失败', async () => {
    const wrapper = await render()
    api.complete.mockResolvedValue(sample(false)); api.materials.mockRejectedValue(new Error('材料读取故障'))
    await button(wrapper, '保存产品需求').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('产品需求已保存')
    expect(wrapper.text()).toContain('材料读取故障')
    expect(api.save).not.toHaveBeenCalled()
  })
  it('候选读取绑定当前申请；名称规格可手填，修改后解除旧关联', async () => {
    const wrapper = await render()
    expect(api.products).toHaveBeenCalledWith('sample-1', '')
    await button(wrapper, '编辑产品信息').trigger('click')
    await wrapper.get('input[aria-label="产品名称"]').setValue('自定义新品')
    await wrapper.get('input[aria-label="产品规格"]').setValue('手工规格')
    await button(wrapper, '返回概览').trigger('click')
    expect(wrapper.get('.product-card').text()).toContain('自定义新品')
    expect(wrapper.get('.product-card').text()).toContain('自定义产品')
    api.complete.mockResolvedValue(sample(false)); api.materials.mockResolvedValue(materials(true, '"p2"'))
    await button(wrapper, '保存产品需求').trigger('click'); await flushPromises()
    expect(api.complete.mock.calls[0]![2][0]).toMatchObject({ product_id: '', product_name: '自定义新品', specification: '手工规格' })
  })
})
