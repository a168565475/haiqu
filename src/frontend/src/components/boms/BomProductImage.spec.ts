import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'
import { apiClient } from '@/api/request'
import type { ProductionTask, ProductionTaskProduct, ProductionTaskProductImage } from '@/types/productionTask'
import BomProductImage from './BomProductImage.vue'

const getTask = vi.spyOn(apiClient, 'get')
const image = (id: string): ProductionTaskProductImage => ({ id, name: `${id}.png`, content_type: 'image/png', size_bytes: 100 })
const product = (id: string, images: ProductionTaskProductImage[] = []): ProductionTaskProduct => ({
  id, line_number: 1, product_id: 'master-1', source_delivery_batch_line_id: null, source_sales_order_line_id: null,
  product_number: 'P001', product_code: 'C001', item_number: 'I001', product_name: '折叠床', specification: '186×55×24cm',
  image_name: images[0]?.name || null, images, product_color_id: null, color_card: '', color_name: '深蓝', color_code: '',
  quantity: 1000, unit_id: 'unit-1', unit_code: 'PCS', unit_name: '张', currency_id: 'currency-1', currency_code: 'CNY',
  unit_price: '1.00', total_amount: '1000.00', exchange_rate: '1.0000', local_unit_price: '1.00', local_total_amount: '1000.00',
  special_requirements: '', packaging_method: '', details: [],
})
function response(products: ProductionTaskProduct[], id = 'task-1') {
  const task: ProductionTask = {
    id, task_number: 'SC001', contract_number: 'HT001', order_source: 'NEW', order_source_display: '新单', order_number: 'SO001',
    customer_id: null, customer_code: '', customer_name: '', order_date: '2026-10-15', delivery_date: '2026-10-31',
    salesperson: { id: 'employee-1', employee_code: 'E001', display_name: '测试员工' }, followers: [],
    delivery_method: 'SINGLE', delivery_method_display: '一次交付', freight_amount: '0.00', other_fee_amount: '0.00',
    product_total_amount: '1000.00', total_amount: '1000.00', status: 'DRAFT', status_display: '草稿',
    total_quantity: '1000', batch_total_quantity: '1000', quantity_difference: '0', products,
    created_at: '2026-10-15T00:00:00Z', updated_at: '2026-10-15T00:00:00Z',
  }
  return { data: { data: task }, headers: { etag: '"v1"' } }
}

const wrappers: ReturnType<typeof mount>[] = []
function open(taskId = 'task-1', productLineId = 'line-1') {
  const wrapper = mount(BomProductImage, {
    props: { taskId, productLineId },
    global: { stubs: { AppWindowDialog: true, ElIcon: { template: '<span><slot /></span>' }, ElButton: { template: '<button><slot /></button>' } } },
  })
  wrappers.push(wrapper)
  return wrapper
}
beforeEach(() => { getTask.mockReset() })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('BOM 来源产品图片', () => {
  it('精确匹配产品明细，只展示该明细的第一张真实图片', async () => {
    getTask.mockResolvedValue(response([
      product('other-line', [image('wrong-image')]),
      product('line-1', [image('main-image'), image('second-image')]),
    ]))
    const wrapper = open()
    await flushPromises()
    expect(wrapper.findAll('img')).toHaveLength(1)
    expect(wrapper.get('img').attributes('src')).toBe('http://localhost:8000/api/v1/production-tasks/task-1/business-files/main-image/')
    expect(wrapper.get('img').attributes('alt')).toContain('折叠床')
  })

  it.each([
    ['', 'line-1', '未关联生产任务'],
    ['task-1', '', '未关联生产任务产品明细'],
  ])('来源缺失时不发送无效请求：%s / %s', async (taskId, productLineId, message) => {
    const wrapper = open(taskId, productLineId)
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain(message)
    expect(getTask).not.toHaveBeenCalled()
    expect(wrapper.find('img').exists()).toBe(false)
  })

  it('没有图片时显示空状态，不借用其他产品的图片', async () => {
    getTask.mockResolvedValue(response([product('other-line', [image('wrong-image')]), product('line-1')]))
    const wrapper = open()
    await flushPromises()
    expect(wrapper.text()).toContain('暂无产品图片')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.find('img').exists()).toBe(false)
  })

  it('来源任务不含关联明细时显示关联异常', async () => {
    getTask.mockResolvedValue(response([product('other-line', [image('wrong-image')])]))
    const wrapper = open()
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('关联的产品明细不存在')
    expect(wrapper.find('img').exists()).toBe(false)
  })

  it.each([
    [403, '无权查看生产任务产品图片'],
    [404, '图片来源不存在或无权访问'],
  ])('来源接口返回 %s 时明确提示且不伪装为空图片', async (status, message) => {
    getTask.mockRejectedValue({ isAxiosError: true, response: { status } })
    const wrapper = open()
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain(message)
    expect(wrapper.text()).not.toContain('暂无产品图片')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('网络失败保留错误提示，原地重试成功后展示图片', async () => {
    getTask.mockRejectedValueOnce(new AxiosError('Network Error', 'ERR_NETWORK')).mockResolvedValueOnce(response([product('line-1', [image('main-image')])]))
    const wrapper = open()
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('加载失败')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('img').attributes('src')).toContain('/business-files/main-image/')
  })

  it.each([
    { status: 401, code: '' },
    { status: 403, code: 'AUTHENTICATION_REQUIRED' },
  ])('未登录或会话失效返回 $status 时提示重新登录', async ({ status, code }) => {
    getTask.mockRejectedValue({ isAxiosError: true, response: { status, data: { error: { code, message: '身份认证信息未提供。' } } } })
    const wrapper = open()
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('请重新登录')
    expect(wrapper.text()).not.toContain('无权查看')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('切换任务与产品后，旧请求晚返回也不能覆盖新图片', async () => {
    let finishOld!: (value: ReturnType<typeof response>) => void
    getTask.mockReturnValueOnce(new Promise(resolve => { finishOld = resolve })).mockResolvedValueOnce(response([product('line-2', [image('new-image')])], 'task-2'))
    const wrapper = open()
    await wrapper.setProps({ taskId: 'task-2', productLineId: 'line-2' })
    await flushPromises()
    expect(wrapper.find('img').exists()).toBe(true)
    finishOld(response([product('line-1', [image('old-image')])]))
    await flushPromises()
    expect(wrapper.get('img').attributes('src')).toBe('http://localhost:8000/api/v1/production-tasks/task-2/business-files/new-image/')
  })

  it('只切换产品明细时清除旧图，旧请求失败不覆盖新结果', async () => {
    let rejectOld!: (reason: unknown) => void
    getTask.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectOld = reject })).mockResolvedValueOnce(response([product('line-2', [image('new-image')])]))
    const wrapper = open()
    await wrapper.setProps({ productLineId: 'line-2' })
    await flushPromises()
    expect(wrapper.find('img').exists()).toBe(true)
    rejectOld({ isAxiosError: true, response: { status: 403 } })
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('img').attributes('src')).toContain('/business-files/new-image/')
  })

  it('已有图片切换到缺失来源时立即移除旧图片', async () => {
    getTask.mockResolvedValue(response([product('line-1', [image('main-image')])]))
    const wrapper = open()
    await flushPromises()
    await wrapper.setProps({ taskId: '' })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.get('[role="alert"]').text()).toContain('未关联生产任务')
  })

  it('图片文件读取失败时可重试，不继续展示损坏图片', async () => {
    getTask.mockResolvedValue(response([product('line-1', [image('main-image')])]))
    const wrapper = open()
    await flushPromises()
    await wrapper.get('img').trigger('error')
    expect(wrapper.get('[role="alert"]').text()).toContain('图片文件加载失败')
    expect(wrapper.find('img').exists()).toBe(false)
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.get('img').attributes('src')).toContain('/business-files/main-image/')
  })
})
