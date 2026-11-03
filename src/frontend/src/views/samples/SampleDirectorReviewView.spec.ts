import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SampleDirectorReviewView from './SampleDirectorReviewView.vue'

const api = vi.hoisted(() => ({ fetch: vi.fn(), review: vi.fn(), push: vi.fn(), dirty: null as null | (() => boolean) }))
vi.mock('@/api/samples', () => ({ fetchSample: api.fetch }))
vi.mock('@/api/sampleApplication', () => ({ reviewSampleApplication: api.review }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { sampleId: 'sample' } }), useRouter: () => ({ push: api.push }) }))
vi.mock('@/composables/useSampleUnsavedChanges', () => ({ useSampleUnsavedChanges: (dirty: () => boolean) => { api.dirty = dirty } }))
const wrappers: ReturnType<typeof mount>[] = []
function application() {
  return { etag: '"v1"', data: { id: 'sample', request_number: 'SRQ-1', status: 'DIRECTOR_REVIEW', status_display: '待厂长确认', application_actions: { is_application: true, can_director_review: true, can_resubmit: false },
    customer_name: '真实客户', owner: { display_name: '业务员' }, products: [], purpose: '', item_summary: { text: '样品', count: 1 } } }
}
function denied(status: number) { return new AxiosError('failed', undefined, undefined, undefined, { status } as never) }
async function render() {
  const wrapper = mount(SampleDirectorReviewView, { global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
function fieldValue(wrapper: ReturnType<typeof mount>, label: string) {
  return wrapper.findAll('.sample-readonly-field').find(field => field.get('.field-label').text() === label)!.get('.field-value').text()
}
beforeEach(() => { vi.clearAllMocks(); api.fetch.mockResolvedValue(application()); api.review.mockRejectedValue(new Error('当前申请流程尚未开放厂长确认或退回操作，处理意见未提交。')) })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('厂长确认页读取与操作边界', () => {
  it('按创建页字段回显完整编号与样品属性，使用实际单位并隐藏客户联系人', async () => {
    const result = application()
    Object.assign(result.data, { manual_request_number: '123', request_number: 'HTS123', customer_contact_name: '客户联系人甲', purpose: '请使用加厚面料并核对包装',
      products: [{ id: 'product-1', category_name: '休闲椅', product_name: '手填折叠椅', specification: '47*55*79', specification_display: '47*55*79；颜色：酒红色；材质：PE', material_snapshot: 'PE',
        product_selection_snapshot: { unit_name: '张' }, total_sample_quantity: 3,
        details: [{ color_card: 'PANTONE', color_code: '19-1629', color_name: '酒红色' }],
      }],
    })
    api.fetch.mockResolvedValueOnce(result)
    const wrapper = await render()
    expect(fieldValue(wrapper, '打样单号')).toBe('HTS123')
    expect(fieldValue(wrapper, '类别')).toBe('休闲椅')
    expect(fieldValue(wrapper, '品名')).toBe('手填折叠椅')
    expect(fieldValue(wrapper, '规格')).toBe('47*55*79')
    expect(fieldValue(wrapper, '材质')).toBe('PE')
    expect(fieldValue(wrapper, '色卡 / 色号 / 颜色')).toBe('PANTONE / 19-1629 / 酒红色')
    expect(fieldValue(wrapper, '单位')).toBe('张')
    expect(fieldValue(wrapper, '打样数量')).toBe('3 张')
    expect(wrapper.get('.summary-product .requirements').text()).toBe('备注（选填）请使用加厚面料并核对包装')
    expect(wrapper.get('.summary-product').text()).toContain('打样数量')
    expect(wrapper.get('.summary-aside').text()).not.toContain('打样数量')
    const labels = wrapper.findAll('.sample-readonly-field .field-label').map(label => label.text())
    expect(labels).not.toContain('客户')
    expect(labels).not.toContain('联系人')
    expect(wrapper.text()).not.toContain('真实客户')
    expect(wrapper.text()).not.toContain('客户联系人甲')
    expect(api.review).not.toHaveBeenCalled()
  })

  it('保留历史编号，切换产品时使用对应产品的单位和数量', async () => {
    const result = application()
    Object.assign(result.data, { manual_request_number: null, request_number: 'SRQ-202611-000139',
      products: [
        { id: 'product-1', product_name: '第一样品', product_selection_snapshot: { unit_name: '张' }, total_sample_quantity: 2, details: [] },
        { id: 'product-2', product_name: '第二样品', total_sample_quantity: 5, details: [] },
      ],
      items: [{ sample_product: 'product-1', unit_code: '张' }, { sample_product: 'product-2', unit_code: '米' }],
    })
    api.fetch.mockResolvedValueOnce(result)
    const wrapper = await render()
    expect(fieldValue(wrapper, '打样单号')).toBe('SRQ-202611-000139')
    expect(fieldValue(wrapper, '打样数量')).toBe('2 张')
    const select = wrapper.findComponent(ElSelect)
    select.vm.$emit('update:modelValue', 'product-2')
    await flushPromises()
    expect(fieldValue(wrapper, '单位')).toBe('米')
    expect(fieldValue(wrapper, '打样数量')).toBe('5 米')
    expect(fieldValue(wrapper, '打样单号')).toBe('SRQ-202611-000139')
    expect(api.review).not.toHaveBeenCalled()
  })

  it('已结束申请仅供查看，不能填写意见或发起处理', async () => {
    const result = application()
    result.data.status = 'FINISHED'
    result.data.status_display = '已完成'
    result.data.application_actions.can_director_review = false
    api.fetch.mockResolvedValueOnce(result)
    const wrapper = await render()
    expect(wrapper.find('textarea').attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('.action-buttons button').every(button => button.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.text()).toContain('仅供查看')
    expect(api.review).not.toHaveBeenCalled()
  })
  it.each([403, 404])('读取 %s 后关闭操作，重试可恢复真实申请与原状态', async status => {
    api.fetch.mockRejectedValueOnce(denied(status))
    const wrapper = await render()
    expect(wrapper.find('[role="alert"]').text()).toContain(status === 403 ? '没有查看' : '未找到')
    expect(wrapper.findAll('.action-buttons button').every(button => button.attributes('disabled') !== undefined)).toBe(true)
    await wrapper.find('.director-error button').trigger('click')
    await flushPromises()
    expect(wrapper.find('.director-error').exists()).toBe(false)
    expect(wrapper.text()).toContain('待厂长确认')
    expect(api.review).not.toHaveBeenCalled()
  })

  it('提交期间不重复发送或允许改写意见，失败解锁并保留意见', async () => {
    let reject!: (error: Error) => void
    api.review.mockImplementationOnce(() => new Promise((_resolve, failure) => { reject = failure }))
    const wrapper = await render()
    await wrapper.find('textarea').setValue('需要补充颜色')
    const button = wrapper.find('.action-buttons button')
    await button.trigger('click')
    await button.trigger('click')
    expect(api.review).toHaveBeenCalledTimes(1)
    expect(wrapper.find('textarea').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.back-button').attributes('disabled')).toBeDefined()
    reject(new Error('连接中断'))
    await flushPromises()
    expect(wrapper.find('textarea').element.value).toBe('需要补充颜色')
    expect(wrapper.find('textarea').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('[role="alert"]').text()).toContain('连接中断')
    expect(api.dirty!()).toBe(true)
  })

  it('处理后刷新遇到 403 时清除旧申请并禁用处理，保留意见', async () => {
    api.review.mockResolvedValueOnce(undefined)
    const wrapper = await render()
    await wrapper.find('textarea').setValue('原处理意见')
    api.fetch.mockRejectedValueOnce(denied(403))
    await wrapper.find('.action-buttons button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('没有查看')
    expect(wrapper.text()).not.toContain('SRQ-1')
    expect(wrapper.findAll('.action-buttons button').every(button => button.attributes('disabled') !== undefined)).toBe(true)
    expect(api.review).toHaveBeenCalledTimes(1)
  })
})
