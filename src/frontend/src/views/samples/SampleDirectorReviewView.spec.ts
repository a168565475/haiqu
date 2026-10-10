import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
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
beforeEach(() => { vi.clearAllMocks(); api.fetch.mockResolvedValue(application()); api.review.mockRejectedValue(new Error('当前申请流程尚未开放厂长确认或退回操作，处理意见未提交。')) })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('厂长确认页读取与操作边界', () => {
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
