import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox, ElSelect, ElOption, ElUpload } from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SampleEditorView from './SampleEditorView.vue'

const api = vi.hoisted(() => ({ fetch: vi.fn(), options: vi.fn(), products: vi.fn(), complete: vi.fn(), materials: vi.fn(), units: vi.fn(), save: vi.fn(), noMaterials: vi.fn(), push: vi.fn(), leave: vi.fn() }))
let testRoute = { params: { sampleId: 'sample-1' }, query: {} as Record<string, string> }
vi.mock('vue-router', () => ({ useRoute: () => testRoute, useRouter: () => ({ push: api.push }), onBeforeRouteLeave: api.leave, onBeforeRouteUpdate: vi.fn() }))
vi.mock('@/api/samples', () => ({ fetchSample: api.fetch, fetchSampleFormOptions: api.options }))
vi.mock('@/api/sampleApplication', () => ({ completeSampleApplicationProducts: api.complete, fetchSampleApplicationProductOptions: api.products }))
vi.mock('@/api/sampleMaterials', () => ({ fetchSampleMaterials: api.materials, fetchSampleMaterialUnits: api.units, saveSampleMaterials: api.save, confirmSampleNoMaterials: api.noMaterials }))

function sample(canComplete = true) {
  return { etag: '"p1"', data: {
    id: 'sample-1', request_number: 'SRQ-001', status: canComplete ? 'PENDING_COMPLETION' : 'MATERIALS_PENDING', status_display: '待完善',
    customer_name: '真实接口由实页检查', purpose: '初始要求', edit_capabilities: { mode: canComplete ? 'COMPLETE' : 'READ_ONLY', can_complete: canComplete }, application_actions: { is_application: true, can_edit_products: true },
    products: [{ id: 'sp1', product_id: 'product-1', product_name: '折叠椅', specification: '椅子规格', category_id: 'cat1', category_name: '椅子',
      length_cm: '50', armrest_width_cm: null, seat_width_cm: null, back_height_cm: null, seat_height_cm: null,
      details: [{ id: 'd1', product_color_id: 'color1', color_code: '蓝色号', sample_quantity: 3, tolerance: 'NONE', notes: '' }] }],
  } }
}
function materials(canEdit = true, version = '"p1"') {
  return { available: true, canEdit, canSubmit: canEdit, isRevision: false, etag: version, status: canEdit ? 'MATERIALS_PENDING' : 'PENDING_COMPLETION', statusLabel: '待填写', submittedAt: null,
    draft: { lines: [{ key: 'm1', category: 'fabric', name: '面料', specification: '规格', material: '', color: '', quantity: '2', unitId: 'u1', rawMaterialId: 'raw1', notes: '' }], notes: '' } }
}
const wrappers: ReturnType<typeof mount>[] = []
async function render() {
  const wrapper = mount(SampleEditorView, { global: { plugins: [ElementPlus], stubs: {
    SampleApplicationBasics: { name: 'SampleApplicationBasics', props: ['modelValue', 'options', 'sample'], emits: ['update:modelValue'], template: '<div class="basic-fields-stub" />' },
    SampleMaterialEditor: { name: 'SampleMaterialEditor', props: ['modelValue', 'disabled', 'layout'], emits: ['update:modelValue', 'editing-change'], template: '<div class="material-stub" :data-disabled="disabled" :data-layout="layout"><button :disabled="disabled" @click="$emit(\'update:modelValue\', [...modelValue, {...modelValue[0], key: \'m2\'}])">添加测试材料</button></div>' },
  } } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
function button(wrapper: ReturnType<typeof mount>, label: string) { return wrapper.findAll('button').find(item => item.text() === label)! }
beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal('URL', class extends URL {
    static createObjectURL = vi.fn((file: File) => `blob:${file.name}`)
    static revokeObjectURL = vi.fn()
  })
  testRoute = { params: { sampleId: 'sample-1' }, query: {} as Record<string, string> }
  api.fetch.mockResolvedValue(sample())
  api.options.mockResolvedValue({ categories: [{ id: 'cat1', category_name: '椅子' }], colors: [{ id: 'color1', color_name: '蓝', color_card: '色卡', color_code: '蓝色号' }], tolerances: [{ value: 'NONE', label: '无' }] })
  api.products.mockResolvedValue([])
  api.materials.mockResolvedValue(materials())
  api.units.mockResolvedValue([{ id: 'u1', label: '米', decimalPlaces: 2 }])
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks(); vi.unstubAllGlobals() })

function productSelect(wrapper: ReturnType<typeof mount>, index = 0) {
  return wrapper.findAllComponents(ElSelect).filter(item => item.props('ariaLabel') === '产品名称')[index]!
}
function colorSelect(wrapper: ReturnType<typeof mount>, index = 0) {
  return wrapper.findAllComponents(ElSelect).filter(item => item.props('ariaLabel') === '产品颜色')[index]!
}
async function chooseName(wrapper: ReturnType<typeof mount>, name: string, index = 0) {
  productSelect(wrapper, index).vm.$emit('change', name)
  await flushPromises()
}
async function chooseColor(wrapper: ReturnType<typeof mount>, id: string, index = 0) {
  colorSelect(wrapper, index).vm.$emit('update:modelValue', id)
  await flushPromises()
  colorSelect(wrapper, index).vm.$emit('change', id)
  await flushPromises()
}
async function editProductDraft(wrapper: ReturnType<typeof mount>) {
  await wrapper.get('#sample-purpose').setValue('未保存产品要求')

}

describe('打样编辑：组件契约测试（Mock 不代表真实验收）', () => {
  it('基础字段参与保存、冲突保留与取消恢复，后续阶段仍可编辑', async () => {
    const current = sample(false)
    api.fetch.mockResolvedValue({ ...current, data: { ...current.data, status: 'FINISHED', shipping_method: 'MAIL', customer_account: 'customer-1', owner: { id: 'owner-1' } } })
    const wrapper = await render()
    const basics = wrapper.findComponent({ name: 'SampleApplicationBasics' })
    const baseline = basics.props('modelValue')
    basics.vm.$emit('update:modelValue', { ...baseline, shipping_method: 'OTHER', order_date: '2026-10-22' })
    await flushPromises()
    api.complete.mockRejectedValueOnce(new AxiosError('conflict', '412', undefined, undefined, { status: 412 } as never))
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(api.complete.mock.calls[0]?.[5]).toMatchObject({ shipping_method: 'OTHER', order_date: '2026-10-22' })
    expect(basics.props('modelValue').shipping_method).toBe('OTHER')
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce('confirm' as never)
    await button(wrapper, '取消修改').trigger('click'); await flushPromises()
    expect(basics.props('modelValue')).toEqual(baseline)
    expect(wrapper.get('#sample-purpose').attributes('disabled')).toBeUndefined()
  })
  it('图片单独变化参与离页和材料推进保护，替换释放旧预览，取消仅恢复产品图片', async () => {
    api.fetch.mockResolvedValue({ ...sample(), data: { ...sample().data, reference_image: 'old-image' } })
    api.materials.mockResolvedValue(materials(true))
    const wrapper = await render()
    const upload = (file: File) => wrapper.findComponent(ElUpload).props('onChange')!({ raw: file } as never, [])
    const first = new File(['png'], 'one.png', { type: 'image/png' })
    upload(first); await flushPromises()
    expect(wrapper.get('.reference-preview img').attributes('src')).toBe('blob:one.png')
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    expect(await api.leave.mock.calls[0]![0]()).toBe(false)
    await button(wrapper, '材料需求').trigger('click')
    await wrapper.get('#sample-material-notes').setValue('保留材料')
    expect(wrapper.find('.product-form-actions').exists()).toBe(false)
    await button(wrapper, '提交仓库').trigger('click'); await flushPromises()
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('产品草稿尚未保存'), '产品草稿尚未保存', expect.any(Object))
    expect(wrapper.get('#sample-product-tab').attributes('aria-selected')).toBe('true')
    upload(new File(['png'], 'two.png', { type: 'image/png' })); await flushPromises()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:one.png')
    confirm.mockResolvedValueOnce('confirm' as never)
    await button(wrapper, '取消修改').trigger('click'); await flushPromises()
    expect(wrapper.get('.reference-preview img').attributes('src')).toContain('/business-files/old-image/')
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:two.png')
    expect((wrapper.get('#sample-material-notes').element as HTMLInputElement).value).toBe('保留材料')
    expect(api.fetch).toHaveBeenCalledTimes(1); expect(api.materials).toHaveBeenCalledTimes(1)
    expect(api.complete).not.toHaveBeenCalled(); expect(api.save).not.toHaveBeenCalled()
  })
  it('图片校验拒绝格式/空文件/超限，保存冲突保留File与预览，成功后材料读取失败保留新图', async () => {
    const wrapper = await render()
    const warning = vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
    const upload = (file: File) => wrapper.findComponent(ElUpload).props('onChange')!({ raw: file } as never, [])
    for (const file of [new File(['x'], 'bad.txt', { type: 'text/plain' }), new File([], 'empty.png', { type: 'image/png' }), new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'large.png', { type: 'image/png' })]) {
      upload(file); await flushPromises()
    }
    expect(warning).toHaveBeenCalledTimes(3); expect(URL.createObjectURL).not.toHaveBeenCalled()
    const image = new File(['png'], 'new.png', { type: 'image/png' })
    upload(image); await flushPromises()
    api.complete.mockRejectedValueOnce(new AxiosError('conflict', '412', undefined, undefined, { status: 412 } as never))
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(wrapper.get('.reference-preview img').attributes('src')).toBe('blob:new.png')
    expect(api.complete.mock.calls[0]![4]).toBe(image)
    api.complete.mockResolvedValue({ etag: '"p2"', data: { ...sample(false).data, reference_image: 'saved-image' } })
    api.materials.mockRejectedValue(new Error('材料读取失败'))
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('产品需求已保存'); expect(wrapper.text()).toContain('材料读取失败')
    expect(wrapper.get('.reference-preview img').attributes('src')).toContain('/business-files/saved-image/')
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:new.png')
    expect(wrapper.findComponent(ElUpload).exists()).toBe(true)
  })
  it.each(['materials', 'unknown', undefined])('初始query=%s选择对应页签，本地切换保留两份草稿与材料行保护', async tab => {
    if (tab) testRoute.query.tab = tab
    api.materials.mockResolvedValue(materials(true))
    const wrapper = await render()
    expect(wrapper.get(tab === 'materials' ? '#sample-materials-tab' : '#sample-product-tab').attributes('aria-selected')).toBe('true')
    await wrapper.get('#sample-materials-tab').trigger('click')
    await wrapper.get('#sample-material-notes').setValue('材料草稿')
    await wrapper.get('#sample-product-tab').trigger('click')
    await editProductDraft(wrapper)
    await wrapper.get('#sample-materials-tab').trigger('click')
    const editor = wrapper.findComponent({ name: 'SampleMaterialEditor' })
    editor.vm.$emit('editing-change', true); await flushPromises()
    await wrapper.get('#sample-product-tab').trigger('click')
    expect(wrapper.get('#sample-materials-tab').attributes('aria-selected')).toBe('true')
    editor.vm.$emit('editing-change', false); await flushPromises()
    await wrapper.get('#sample-product-tab').trigger('click')
    expect(wrapper.get('#sample-product-tab').attributes('aria-selected')).toBe('true')
    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('未保存产品要求')
    expect((wrapper.get('#sample-material-notes').element as HTMLInputElement).value).toBe('材料草稿')
    expect(api.fetch).toHaveBeenCalledTimes(1); expect(api.materials).toHaveBeenCalledTimes(1)
    expect(testRoute.query.tab).toBe(tab)
    expect(api.push).not.toHaveBeenCalled()
  })
  it('默认直接使用创建页表单，基础与产品可编辑，无编辑切换或弹窗', async () => {
    const wrapper = await render()
    const form = wrapper.get('.product-form-panel .application-form')
    expect(wrapper.findComponent({ name: 'SampleApplicationBasics' }).exists()).toBe(true)
    expect(form.classes()).toContain('erp-flat-form')
    expect(wrapper.findAll('.application-columns > .product-section')).toHaveLength(1)
    expect(wrapper.findAll('.application-aside > .sample-section')).toHaveLength(2)
    expect(wrapper.findAll('.product-record')).toHaveLength(1)
    expect(wrapper.findAll('.detail-fields')).toHaveLength(1)
    expect(wrapper.findAll('.dimensions-grid input')).toHaveLength(5)
    expect(productSelect(wrapper).props()).toMatchObject({ filterable: true, remote: true, allowCreate: true, defaultFirstOption: true })
    expect(form.find('#sample-purpose').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('.product-information-card, .material-application-info, .product-window, [role="dialog"]').exists()).toBe(false)
    expect(wrapper.findAll('button').some(item => /^(编辑|展开|收起|移除)/.test(item.text()))).toBe(false)
    expect(wrapper.findComponent(ElUpload).props('autoUpload')).toBe(false)
    expect(wrapper.find('.editor-breadcrumb').exists()).toBe(false)
    expect(wrapper.get('.editor-toolbar').find('.product-form-actions').exists()).toBe(true)
    expect(wrapper.get('[role="tablist"]').find('.product-form-actions').exists()).toBe(false)
    const confirm = vi.spyOn(ElMessageBox, 'confirm')
    await button(wrapper, '取消修改').trigger('click'); await flushPromises()
    expect(confirm).not.toHaveBeenCalled()
    expect(wrapper.find('#sample-purpose').exists()).toBe(true)
    expect(api.fetch).toHaveBeenCalledTimes(1); expect(api.materials).toHaveBeenCalledTimes(1)
  })
  it('取消确认恢复产品与关联缓存，保留材料草稿和ETag，保存更新当前表单', async () => {
    api.materials.mockResolvedValue(materials(true))
    const wrapper = await render()
    await wrapper.get('#sample-material-notes').setValue('保留材料')
    await chooseName(wrapper, '临时改名')
    await wrapper.get('#sample-purpose').setValue('临时要求')
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel')
    await button(wrapper, '取消修改').trigger('click'); await flushPromises()
    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('临时要求')
    confirm.mockResolvedValueOnce('confirm' as never)
    await button(wrapper, '取消修改').trigger('click'); await flushPromises()
    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('初始要求')
    expect(productSelect(wrapper).props('modelValue')).toBe('product-1')
    expect(wrapper.get('.product-record').text()).toContain('折叠椅')
    expect((wrapper.get('#sample-material-notes').element as HTMLInputElement).value).toBe('保留材料')
    expect(api.fetch).toHaveBeenCalledTimes(1); expect(api.materials).toHaveBeenCalledTimes(1)
    // 取消恢复关联缓存后，改规格仍须解除旧档案身份。
    await wrapper.get('input[aria-label="产品规格"]').setValue('再次改规格')
    expect(productSelect(wrapper).props('modelValue')).toBe('折叠椅')
    const latest = sample(); latest.data.purpose = '服务端已保存要求'; latest.data.products[0]!.product_name = '服务端名称'; latest.etag = '"p2"'
    api.complete.mockResolvedValue(latest); api.materials.mockResolvedValue(materials(true, '"p2"'))
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(api.complete.mock.calls[0]![1]).toBe('"p1"')
    expect(api.complete.mock.calls[0]![2][0]).toMatchObject({ product_id: '', product_name: '折叠椅', specification: '再次改规格' })
    expect(wrapper.get('#sample-product-tab').attributes('aria-selected')).toBe('true')
    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('服务端已保存要求')
    expect(productSelect(wrapper).props('modelValue')).toBe('product-1')
    expect(wrapper.get('.product-record').text()).toContain('服务端名称')
  })
  it('多产品多颜色逐项编辑，数量在右侧对应明细，保存保留全部ID', async () => {
    const current = sample()
    current.data.products[0]!.details.push({ ...current.data.products[0]!.details[0]!, id: 'd2', notes: '第二颜色' })
    current.data.products.push({ ...current.data.products[0]!, id: 'sp2', product_name: '第二产品', details: [{ ...current.data.products[0]!.details[0]!, id: 'd3' }] })
    api.fetch.mockResolvedValue(current)
    const wrapper = await render()
    expect(wrapper.findAll('.product-record')).toHaveLength(2)
    expect(wrapper.findAll('.detail-fields')).toHaveLength(3)
    expect(wrapper.findAll('.quantity-section input[aria-label="打样数量"]')).toHaveLength(3)
    expect(wrapper.findAll('.product-section input[aria-label="打样数量"]')).toHaveLength(0)
    await wrapper.get('[data-detail-id="d2"] input[aria-label="产品备注"]').setValue('第二颜色修改')
    await wrapper.get('[data-quantity-detail-id="d2"] input').setValue('7'); await flushPromises()
    await chooseName(wrapper, '第二产品新名', 1)
    await wrapper.get('[data-product-id="sp2"] input[aria-label="产品规格"]').setValue('第二产品规格')
    api.complete.mockResolvedValue({ ...current, etag: '"p2"' }); api.materials.mockResolvedValue(materials(false, '"p2"'))
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(api.complete.mock.calls[0]![2]).toEqual([
      expect.objectContaining({ id: 'sp1', product_name: '折叠椅', details: [expect.objectContaining({ id: 'd1' }), expect.objectContaining({ id: 'd2', notes: '第二颜色修改', sample_quantity: 7 })] }),
      expect.objectContaining({ id: 'sp2', product_id: '', product_name: '第二产品新名', specification: '第二产品规格', details: [expect.objectContaining({ id: 'd3' })] }),
    ])
    expect(wrapper.find('.application-form').exists()).toBe(true)
    expect(wrapper.get('#sample-product-tab').attributes('aria-selected')).toBe('true')
  })
  it.each([
    ['尺寸；材质:木；颜色：旧色', '尺寸；材质:木；颜色：蓝'],
    ['尺寸;材质：木;颜色:旧色', '尺寸;材质：木;颜色:蓝'],
    ['尺寸;材质：木', '尺寸;材质：木；颜色：蓝'],
  ])('单颜色明细只替换规格中的颜色段：%s', async (specification, expected) => {
    const current = sample(); current.data.products[0]!.specification = specification
    api.fetch.mockResolvedValue(current)
    const wrapper = await render()
    await chooseColor(wrapper, 'color1')
    expect((wrapper.get('input[aria-label="产品规格"]').element as HTMLInputElement).value).toBe(expected)
    await chooseColor(wrapper, '')
    expect((wrapper.get('input[aria-label="产品规格"]').element as HTMLInputElement).value).toBe(specification)
  })
  it('颜色名称为空时使用色号，多个颜色明细不自动改共享规格', async () => {
    const current = sample(); current.data.products[0]!.specification = '尺寸；材质：木；颜色：旧色'
    current.data.products[0]!.details.push({ ...current.data.products[0]!.details[0]!, id: 'd2' })
    api.fetch.mockResolvedValue(current)
    api.options.mockResolvedValue({ categories: [{ id: 'cat1', category_name: '椅子' }], colors: [
      { id: 'color1', color_name: '蓝', color_card: '色卡', color_code: '蓝色号' },
      { id: 'color2', color_name: '', color_card: '色卡2', color_code: 'R-02' },
    ], tolerances: [{ value: 'NONE', label: '无' }] })
    const wrapper = await render()
    await chooseColor(wrapper, 'color2', 0)
    expect((wrapper.get('input[aria-label="产品规格"]').element as HTMLInputElement).value).toBe('尺寸；材质：木；颜色：旧色')
    expect((wrapper.get('[data-detail-id="d1"] input[aria-label="色号"]').element as HTMLInputElement).value).toBe('R-02')
  })
  it('材料持续可编辑，切换页签不丢失产品输入', async () => {
    const wrapper = await render()
    await wrapper.get('#sample-purpose').setValue('未保存要求')
    await button(wrapper, '材料需求').trigger('click')
    expect(wrapper.get('.material-stub').attributes('data-disabled')).toBe('false')
    expect(wrapper.get('.material-stub').attributes('data-layout')).toBe('sidebar')
    await button(wrapper, '申请与产品').trigger('click')
    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('未保存要求')
    expect(api.complete).not.toHaveBeenCalled()
  })
  it('材料只读时只提示账号权限，不按样品阶段锁定', async () => {
    const current = sample(); current.data.status_display = '待工厂完善'
    const state = materials(false); state.statusLabel = '待工厂完善'
    api.fetch.mockResolvedValue(current); api.materials.mockResolvedValue(state)
    const wrapper = await render()
    await button(wrapper, '材料需求').trigger('click')
    expect(wrapper.text()).toContain('当前账号没有材料需求编辑权限')
    expect(wrapper.text()).not.toContain('当前样品阶段为')
  })
  it('材料处于可编辑阶段但账号无权时显示账号权限提示', async () => {
    const current = sample(false); current.data.status_display = '待填写材料'
    const state = materials(false); state.status = 'MATERIALS_PENDING'; state.statusLabel = '待填写材料'
    api.fetch.mockResolvedValue(current); api.materials.mockResolvedValue(state)
    const wrapper = await render()
    await button(wrapper, '材料需求').trigger('click')
    expect(wrapper.text()).toContain('当前账号没有材料需求编辑权限')
    expect(wrapper.text()).not.toContain('当前样品阶段为')
  })
  it('产品选择复用可创建名称交互，候选含名称规格，手输名称保留规格和类别且不提交', async () => {
    api.products.mockResolvedValue([{ id: 'candidate-2', product_name: '成品名称', specification: '成品规格', category_id: 'cat1' }])
    const wrapper = await render()
    // 已关联档案不在候选中时仍展示真实名称，不能显示UUID。
    expect(wrapper.get('.product-record .el-select__placeholder').text()).toBe('折叠椅')
    const candidate = productSelect(wrapper).findAllComponents(ElOption).find(item => item.props('value') === 'candidate-2')!
    expect(candidate.props('label')).toBe('成品名称')
    expect(candidate.get('.product-option-name').text()).toBe('成品名称')
    expect(candidate.get('.product-option-spec').text()).toBe('成品规格')
    await chooseName(wrapper, 'candidate-2')
    expect(productSelect(wrapper).props('modelValue')).toBe('candidate-2')
    expect((wrapper.get('input[aria-label="产品规格"]').element as HTMLInputElement).value).toBe('成品规格')
    await chooseName(wrapper, '手输新品')
    expect(productSelect(wrapper).props('modelValue')).toBe('手输新品')
    expect((wrapper.get('input[aria-label="产品规格"]').element as HTMLInputElement).value).toBe('成品规格')
    expect(api.complete).not.toHaveBeenCalled()
    await wrapper.get('.application-form').trigger('submit')
    expect(api.complete).not.toHaveBeenCalled()
    api.complete.mockResolvedValue(sample(false)); api.materials.mockResolvedValue(materials(true, '"p1"'))
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(api.complete.mock.calls[0]![2][0]).toMatchObject({ product_id: '', product_name: '手输新品', specification: '成品规格', category_id: 'cat1' })
  })
  it('产品保存后采用新版本提交材料，并分别提示结果', async () => {
    const wrapper = await render()
    const result = sample(false); result.etag = '"p2"'
    api.complete.mockResolvedValue(result)
    api.materials.mockResolvedValue(materials(true, '"p2"'))
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(api.complete.mock.calls[0]![1]).toBe('"p1"')
    expect(wrapper.text()).toContain('产品需求已保存。材料填写内容仍保留')
    expect(wrapper.get('.material-stub').attributes('data-disabled')).toBe('false')
    const saved = materials(false, '"p3"'); saved.status = 'WAREHOUSE_PENDING'
    api.save.mockResolvedValue(saved)
    api.fetch.mockResolvedValue(sample(false))
    await button(wrapper, '提交仓库').trigger('click'); await flushPromises()
    expect(api.save.mock.calls[0]![0]).toMatchObject({ sampleId: 'sample-1', etag: '"p2"', submit: true })
    expect(wrapper.text()).toContain('材料需求已提交仓库。')
  })
  it('产品保存版本冲突保留输入，不改变材料后端能力', async () => {
    api.materials.mockResolvedValue(materials(true))
    const wrapper = await render()
    await wrapper.get('#sample-purpose').setValue('冲突后保留')
    api.complete.mockRejectedValue(new AxiosError('conflict', '412', undefined, undefined, { status: 412 } as never))
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('数据版本已变化')
    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('冲突后保留')
    expect(wrapper.get('.material-stub').attributes('data-disabled')).toBe('false')
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
  it('非新版申请不出现保存操作，加载403显示错误', async () => {
    const readonly = sample(); readonly.data.edit_capabilities.can_complete = false
    readonly.data.application_actions.is_application = false
    api.fetch.mockResolvedValue(readonly)
    const wrapper = await render()
    expect(wrapper.findAll('button').some(item => item.text() === '保存')).toBe(false)
    expect(api.options).not.toHaveBeenCalled()

    expect(wrapper.get('#sample-purpose').attributes('disabled')).toBeDefined()
    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('初始要求')
    expect(wrapper.findAll('.product-section input').every(item => item.attributes('disabled') !== undefined)).toBe(true)
    api.fetch.mockRejectedValue(new AxiosError('forbidden', '403', undefined, undefined, { status: 403 } as never))
    expect((await render()).text()).toContain('当前账号没有此操作权限')
  })
  it('新版申请没有产品编辑权限时不读取候选、不显示保存，材料仍可独立编辑', async () => {
    const current = sample(); current.data.application_actions.can_edit_products = false
    api.fetch.mockResolvedValue(current)
    const wrapper = await render()
    expect(button(wrapper, '保存')).toBeUndefined()
    expect(api.options).not.toHaveBeenCalled(); expect(api.products).not.toHaveBeenCalled()
    expect(wrapper.get('input[aria-label="产品规格"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.material-stub').attributes('data-disabled')).toBe('false')
  })
  it.each(['DIRECTOR_REVIEW', 'WAREHOUSE_PENDING', 'PROCUREMENT_PENDING', 'MATERIAL_ISSUE_REVIEW', 'FINISHED'])('%s仍可保存产品和材料资料，不出现推进流程按钮', async status => {
    const current = sample(false); current.data.status = status
    const state = materials(true); state.status = status; state.canSubmit = false; state.isRevision = status !== 'DIRECTOR_REVIEW'
    api.fetch.mockResolvedValue(current); api.materials.mockResolvedValue(state)
    const wrapper = await render()
    expect(button(wrapper, '保存').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('input[aria-label="产品规格"]').attributes('disabled')).toBeUndefined()
    await button(wrapper, '材料需求').trigger('click')
    expect(button(wrapper, '提交仓库')).toBeUndefined(); expect(button(wrapper, '无需用料')).toBeUndefined()
    expect(wrapper.get('.material-stub').attributes('data-disabled')).toBe('false')
    await wrapper.get('#sample-material-notes').setValue('当前资料修订')
    const saved = { ...state, etag: '"m2"', draft: { ...state.draft, notes: '当前资料修订' } }
    api.save.mockResolvedValue(saved); api.fetch.mockResolvedValue({ ...current, etag: '"m2"' })
    const confirm = vi.spyOn(ElMessageBox, 'confirm')
    await button(wrapper, '保存材料').trigger('click'); await flushPromises()
    expect(api.save).toHaveBeenCalledWith(expect.objectContaining({ submit: false, etag: '"p1"', draft: expect.objectContaining({ notes: '当前资料修订' }) }))
    expect(api.noMaterials).not.toHaveBeenCalled(); expect(confirm).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('材料资料已保存。')
    if (state.isRevision) expect(wrapper.text()).toContain('已提交的仓库、采购和领料记录保留原快照')
  })
  it('产品成功但材料重载失败分别显示结果，不误称全部失败', async () => {
    const wrapper = await render()
    api.complete.mockResolvedValue(sample(false)); api.materials.mockRejectedValue(new Error('材料读取故障'))
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('产品需求已保存')
    expect(wrapper.text()).toContain('材料读取故障')
    expect(api.save).not.toHaveBeenCalled()
  })
  it('候选读取绑定当前申请；名称规格可手填，修改后解除旧关联', async () => {
    const wrapper = await render()
    expect(api.products).toHaveBeenCalledWith('sample-1', '')
    await chooseName(wrapper, '自定义新品')
    await wrapper.get('input[aria-label="产品规格"]').setValue('手工规格')

    expect(productSelect(wrapper).props('modelValue')).toBe('自定义新品')
    expect((wrapper.get('input[aria-label="产品规格"]').element as HTMLInputElement).value).toBe('手工规格')
    api.complete.mockResolvedValue(sample(false)); api.materials.mockResolvedValue(materials(true, '"p2"'))
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(api.complete.mock.calls[0]![2][0]).toMatchObject({ product_id: '', product_name: '自定义新品', specification: '手工规格' })
  })

  it('产品能力不再依赖需求阶段，材料可单独提交且普通无dirty流程不额外确认', async () => {
    const current = sample(); current.data.edit_capabilities.can_complete = false
    api.fetch.mockResolvedValue(current); api.materials.mockResolvedValue(materials(true))
    const confirm = vi.spyOn(ElMessageBox, 'confirm')
    const wrapper = await render()
    expect(api.options).toHaveBeenCalled()
    expect(wrapper.get('.material-stub').attributes('data-disabled')).toBe('false')
    const saved = materials(false, '"m2"'); saved.status = 'WAREHOUSE_PENDING'
    api.save.mockResolvedValue(saved); api.fetch.mockResolvedValue({ ...sample(false), etag: '"m2"' })
    await button(wrapper, '材料需求').trigger('click'); await button(wrapper, '提交仓库').trigger('click'); await flushPromises()
    expect(api.save.mock.calls[0]![0]).toMatchObject({ etag: '"p1"', submit: true })
    expect(confirm).not.toHaveBeenCalled(); expect(api.complete).not.toHaveBeenCalled()
  })

  it('先填材料再保存产品保留材料行、备注及dirty基线，随后提交使用新ETag', async () => {
    api.materials.mockResolvedValue(materials(true))
    const wrapper = await render()
    await button(wrapper, '材料需求').trigger('click')
    await button(wrapper, '添加测试材料').trigger('click')
    await wrapper.get('#sample-material-notes').setValue('未提交材料备注')
    await button(wrapper, '申请与产品').trigger('click')
    api.complete.mockResolvedValue({ ...sample(false), etag: '"p2"' })
    api.materials.mockResolvedValue(materials(true, '"p2"'))
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect((wrapper.get('#sample-material-notes').element as HTMLInputElement).value).toBe('未提交材料备注')
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    expect(await api.leave.mock.calls[0]![0]()).toBe(false)
    expect(confirm).toHaveBeenCalled()
    api.save.mockImplementation(async input => ({ ...materials(false, '"p3"'), draft: input.draft, status: 'WAREHOUSE_PENDING' }))
    api.fetch.mockResolvedValue({ ...sample(false), etag: '"p3"' })
    await button(wrapper, '提交仓库').trigger('click'); await flushPromises()
    expect(api.save.mock.calls[0]![0]).toMatchObject({ etag: '"p2"', draft: { notes: '未提交材料备注', lines: [expect.objectContaining({ key: 'm1' }), expect.objectContaining({ key: 'm2' })] } })
  })

  it('产品已保存但材料读取失败仍保留草稿，重读成功也不误清dirty', async () => {
    api.materials.mockResolvedValue(materials(true))
    const wrapper = await render()
    await wrapper.get('#sample-material-notes').setValue('失败仍保留的材料')
    api.complete.mockResolvedValue({ ...sample(false), etag: '"p2"' }); api.materials.mockRejectedValue(new Error('材料重读失败'))
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('产品需求已保存'); expect(wrapper.text()).toContain('材料重读失败')
    expect((wrapper.get('#sample-material-notes').element as HTMLInputElement).value).toBe('失败仍保留的材料')
    api.materials.mockResolvedValue(materials(true, '"p2"'))
    await button(wrapper, '重新加载材料').trigger('click'); await flushPromises()
    expect((wrapper.get('#sample-material-notes').element as HTMLInputElement).value).toBe('失败仍保留的材料')
    vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    expect(await api.leave.mock.calls[0]![0]()).toBe(false)
  })

  it('保留材料草稿回读遇第三方版本时不静默升版本，重读仍冲突并禁止材料写入', async () => {
    api.materials.mockResolvedValue(materials(true))
    const wrapper = await render()
    await wrapper.get('#sample-material-notes').setValue('旧版本上的材料草稿')
    api.complete.mockResolvedValue({ ...sample(false), etag: '"p2"' })
    api.materials.mockResolvedValue(materials(true, '"p3"'))
    await button(wrapper, '保存').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('产品需求已保存')
    expect(wrapper.text()).toContain('材料版本已被其他操作更新')
    expect((wrapper.get('#sample-material-notes').element as HTMLInputElement).value).toBe('旧版本上的材料草稿')
    expect(button(wrapper, '提交仓库').attributes('disabled')).toBeDefined()
    await button(wrapper, '重新加载材料').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('材料版本已被其他操作更新')
    await button(wrapper, '提交仓库').trigger('click')
    expect(api.save).not.toHaveBeenCalled()
  })

  it('材料成功后产品草稿回读遇第三方版本时不采用新ETag或旧能力', async () => {
    api.materials.mockResolvedValue(materials(true))
    const wrapper = await render(); await editProductDraft(wrapper)
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    api.save.mockResolvedValue({ ...materials(false, '"p2"'), status: 'WAREHOUSE_PENDING' })
    api.fetch.mockResolvedValue({ ...sample(false), etag: '"p3"' })
    await button(wrapper, '提交仓库').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('材料需求已提交仓库。')
    expect(wrapper.text()).toContain('产品版本已被其他操作更新')
    await button(wrapper, '重新核对产品能力').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('产品版本已被其他操作更新')
    expect(wrapper.findAll('button').some(item => item.text() === '保存')).toBe(false)

    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('未保存产品要求')
    expect(api.save).toHaveBeenCalledTimes(1); expect(api.complete).not.toHaveBeenCalled()
  })

  it('仅产品有草稿时，材料回读也不能借第三方版本抬升共享ETag', async () => {
    api.materials.mockResolvedValue(materials(true)); api.units.mockRejectedValueOnce(new Error('单位读取失败'))
    const wrapper = await render(); await editProductDraft(wrapper)
    api.materials.mockResolvedValue(materials(true, '"p3"'))
    await button(wrapper, '重新加载材料').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('材料版本已被其他操作更新')
    expect(wrapper.findAll('button').some(item => item.text() === '保存')).toBe(false)

    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('未保存产品要求')
    expect(api.complete).not.toHaveBeenCalled(); expect(api.save).not.toHaveBeenCalled()
  })

  it('材料重读期间阻止重复重读及材料/产品写入，不让旧读与新写交错', async () => {
    api.materials.mockResolvedValue(materials(true)); api.units.mockRejectedValueOnce(new Error('单位读取失败'))
    const wrapper = await render()
    let finishRead!: (value: ReturnType<typeof materials>) => void
    api.materials.mockImplementationOnce(() => new Promise<ReturnType<typeof materials>>(resolve => { finishRead = resolve }))
    const reload = button(wrapper, '重新加载材料')
    await Promise.all([reload.trigger('click'), reload.trigger('click')]); await flushPromises()
    expect(api.materials).toHaveBeenCalledTimes(2)
    for (const label of ['提交仓库', '无需用料', '保存']) {
      expect(button(wrapper, label).attributes('disabled')).toBeDefined()
      await button(wrapper, label).trigger('click')
    }
    expect(button(wrapper, '重新加载材料')).toBeUndefined()
    expect(api.save).not.toHaveBeenCalled(); expect(api.noMaterials).not.toHaveBeenCalled(); expect(api.complete).not.toHaveBeenCalled()
    finishRead(materials(true)); await flushPromises()
    expect(button(wrapper, '提交仓库').attributes('disabled')).toBeUndefined()
    expect(button(wrapper, '保存').attributes('disabled')).toBeUndefined()
    expect(api.materials).toHaveBeenCalledTimes(2)
  })

  it.each(['提交仓库', '无需用料'])('%s成功而详情重读失败，保留产品草稿和成功结果，禁止旧能力保存并可重试', async label => {
    api.materials.mockResolvedValue(materials(true))
    const wrapper = await render(); await editProductDraft(wrapper)
    await button(wrapper, '材料需求').trigger('click')
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const committed = materials(false, '"p2"'); committed.status = label === '提交仓库' ? 'WAREHOUSE_PENDING' : 'PRODUCTION_PENDING'
    const action = label === '提交仓库' ? api.save : api.noMaterials
    action.mockResolvedValue(committed); api.fetch.mockRejectedValue(new Error('详情重读故障'))
    await button(wrapper, label).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain(label === '提交仓库' ? '材料需求已提交仓库。' : '已确认无需用料')
    expect(wrapper.text()).toContain('产品能力读取失败'); expect(wrapper.text()).toContain('产品草稿尚未保存')
    expect(wrapper.findAll('button').some(item => item.text() === '保存')).toBe(false)

    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('未保存产品要求')

    api.fetch.mockResolvedValue({ ...sample(false), etag: '"p2"' })
    await button(wrapper, '重新核对产品能力').trigger('click'); await flushPromises()
    expect(action).toHaveBeenCalledTimes(1); expect(api.complete).not.toHaveBeenCalled()

    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('未保存产品要求')
    expect(wrapper.text()).not.toContain('产品能力读取失败')
  })

  it.each(['提交仓库', '无需用料'])('%s成功且能力同步成功后产品仍可编辑并保留未保存草稿', async label => {
    api.materials.mockResolvedValue(materials(true))
    const wrapper = await render(); await editProductDraft(wrapper)
    await button(wrapper, '材料需求').trigger('click')
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const committed = materials(false, '"p2"'); committed.status = label === '提交仓库' ? 'WAREHOUSE_PENDING' : 'PRODUCTION_PENDING'
    const action = label === '提交仓库' ? api.save : api.noMaterials
    action.mockResolvedValue(committed)
    const after = sample(false); after.data.status = committed.status; after.etag = '"p2"'
    api.fetch.mockResolvedValue(after)
    await button(wrapper, label).trigger('click'); await flushPromises()
    expect(api.fetch).toHaveBeenCalledTimes(2)
    await button(wrapper, '申请与产品').trigger('click')
    expect(button(wrapper, '保存').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('input[aria-label="产品规格"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('产品草稿尚未保存')

    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('未保存产品要求')
    expect(api.complete).not.toHaveBeenCalled()
    expect(action).toHaveBeenCalledTimes(1)
  })

  it.each(['提交仓库', '无需用料'])('产品dirty时取消%s返回产品，两个草稿均不丢失', async label => {
    api.materials.mockResolvedValue(materials(true))
    const wrapper = await render(); await editProductDraft(wrapper)
    await button(wrapper, '材料需求').trigger('click'); await wrapper.get('#sample-material-notes').setValue('保留的材料草稿')
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    await button(wrapper, label).trigger('click'); await flushPromises()
    expect(confirm.mock.calls[0]![0]).toContain('本次操作不会保存产品')
    expect(api.save).not.toHaveBeenCalled(); expect(api.noMaterials).not.toHaveBeenCalled(); expect(api.complete).not.toHaveBeenCalled()
    expect(wrapper.get('#sample-product-tab').attributes('aria-selected')).toBe('true')
    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('未保存产品要求')
    expect((wrapper.get('#sample-material-notes').element as HTMLInputElement).value).toBe('保留的材料草稿')
  })

  it.each(['提交仓库', '无需用料'])('确认继续%s但写入失败时仍保留产品与材料草稿', async label => {
    api.materials.mockResolvedValue(materials(true))
    const wrapper = await render(); await editProductDraft(wrapper)
    await button(wrapper, '材料需求').trigger('click')
    await wrapper.get('#sample-material-notes').setValue('失败保留材料')
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const action = label === '提交仓库' ? api.save : api.noMaterials
    action.mockRejectedValue(new Error('写入故障'))
    await button(wrapper, label).trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('写入故障'); expect(api.fetch).toHaveBeenCalledTimes(1)
    expect((wrapper.get('#sample-purpose').element as HTMLTextAreaElement).value).toBe('未保存产品要求')
    expect((wrapper.get('#sample-material-notes').element as HTMLInputElement).value).toBe('失败保留材料')
  })
})
