import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/api/productionTasks'
import type { ProductionTask } from '@/types/productionTask'
import ProductionTaskEditView from './ProductionTaskEditView.vue'

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { taskId: 'task-1' } }),
  useRouter: () => router,
  onBeforeRouteLeave: vi.fn(),
}))
vi.mock('@/components/InquiryWangEditor.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/api/productionTasks', () => ({
  fetchProductionTask: vi.fn(),
  fetchProductionTaskOptions: vi.fn(),
  updateProductionTask: vi.fn(),
}))

interface EditPage {
  form: { delivery_date: string; follower_ids: string[]; special_requirements_html: string }
  products: Array<{ quantity: string }>
  dirty: boolean
  save: () => Promise<void>
}

function legacyTask(): ProductionTask {
  return {
    id: 'task-1', task_number: 'HT-TEST', status: 'READY', status_display: '已确认',
    contract_number: 'HT-TEST', order_source: 'NEW', order_source_display: '新订单',
    customer_id: 'customer-1', delivery_method: 'SINGLE', delivery_method_display: '一次交付',
    customer_code: 'CUSTOMER-TEST', customer_name: '测试客户', order_number: 'ORDER-TEST',
    order_date: '2026-09-01', delivery_date: '2026-09-20',
    salesperson: { id: 'salesperson-1', employee_code: 'EMP-1', display_name: '业务员' },
    followers: [], special_requirements_html: '',
    products: [{
      id: 'product-line-1', line_number: 1, product_id: 'product-1', product_code: 'PRODUCT-TEST',
      product_number: 'PRODUCT-TEST', item_number: '', color_card: '', image_name: null,
      product_name: '测试产品', specification: '测试规格', product_color_id: null,
      color_name: '', color_code: '', quantity: 100, unit_id: 'unit-1', unit_name: '件', unit_code: 'PCS',
      currency_id: 'currency-1', currency_code: 'CNY', unit_price: '1.0000', exchange_rate: '1.0000',
      total_amount: '100.0000', local_unit_price: '1.0000', local_total_amount: '100.0000',
      special_requirements: '', packaging_method: '', source_sales_order_line_id: null,
      source_delivery_batch_line_id: null, images: [], details: [],
    }],
    delivery_batches: [{ id: 'batch-1', line_number: 1, quantity: '100', delivery_date: '2026-09-20', note: '' }],
    freight_amount: '0', other_fee_amount: '0', product_total_amount: '100.0000', total_amount: '100.0000',
    total_quantity: '100', batch_total_quantity: '100', quantity_difference: '0',
    created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z', current_boms: [],
  }
}

async function mountPage() {
  const wrapper = shallowMount(ProductionTaskEditView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  return { wrapper, page: wrapper.vm as unknown as EditPage }
}

describe('生产任务编辑页精确保存', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.clearAllMocks()
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: legacyTask(), etag: '"task-v1"' })
    vi.mocked(api.fetchProductionTaskOptions).mockResolvedValue({ employees: [] } as never)
    vi.mocked(api.updateProductionTask).mockResolvedValue({ data: legacyTask(), etag: '"task-v2"' })
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
    vi.spyOn(ElMessage, 'info').mockImplementation(() => ({ close: vi.fn() }))
    vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: vi.fn() }))
  })

  it('旧产品缺颜色和明细时只改头日期仍仅提交日期与当前 ETag', async () => {
    const { wrapper, page } = await mountPage()
    page.form.delivery_date = '2026-09-30'

    await page.save()

    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', { delivery_date: '2026-09-30' }, {}, {}, '"task-v1"')
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      '保存后，待确认或已确认的任务将回到草稿，需要重新提交 PMC。',
      '确认保存修改', expect.any(Object),
    )
    expect(router.replace).toHaveBeenCalledWith({ name: 'production-task-detail', params: { taskId: 'task-1' } })
    wrapper.unmount()
  })

  it('没有修改时不发请求，改日期再还原也不保存', async () => {
    const { wrapper, page } = await mountPage()
    expect(page.dirty).toBe(false)
    await page.save()
    page.form.delivery_date = '2026-09-30'
    expect(page.dirty).toBe(true)
    page.form.delivery_date = '2026-09-20'
    expect(page.dirty).toBe(false)
    await page.save()

    expect(api.updateProductionTask).not.toHaveBeenCalled()
    expect(ElMessageBox.confirm).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('富文本编辑器初始化空段落不应误判为生产要求修改', async () => {
    const { wrapper, page } = await mountPage()
    page.form.special_requirements_html = '<p><br></p>'

    expect(page.dirty).toBe(false)
    await page.save()
    expect(api.updateProductionTask).not.toHaveBeenCalled()

    page.form.delivery_date = '2026-09-30'
    await page.save()
    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', { delivery_date: '2026-09-30' }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it('清空已有生产要求时仍提交空值', async () => {
    const task = legacyTask()
    task.special_requirements_html = '<p>已有生产要求</p>'
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    page.form.special_requirements_html = '<p><br></p>'

    expect(page.dirty).toBe(true)
    await page.save()
    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', { special_requirements_html: '' }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it('只有勾选项的生产要求不应被当成空白', async () => {
    const { wrapper, page } = await mountPage()
    page.form.special_requirements_html = '<p><input type="checkbox"></p>'

    expect(page.dirty).toBe(true)
    await page.save()
    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', {
      special_requirements_html: '<p><input type="checkbox"></p>',
    }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it('旧纯文本被编辑器包成段落不算修改，加粗后仍能保存', async () => {
    const task = legacyTask()
    task.special_requirements_html = '原有生产要求'
    vi.mocked(api.fetchProductionTask).mockResolvedValue({ data: task, etag: '"task-v1"' })
    const { wrapper, page } = await mountPage()
    page.form.special_requirements_html = '<p>原有生产要求</p>'

    expect(page.dirty).toBe(false)
    await page.save()
    expect(api.updateProductionTask).not.toHaveBeenCalled()

    page.form.special_requirements_html = '<p style="text-align:center">原有生产要求</p>'
    expect(page.dirty).toBe(true)
    await page.save()
    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', {
      special_requirements_html: '<p style="text-align:center">原有生产要求</p>',
    }, {}, {}, '"task-v1"')

    page.form.special_requirements_html = '<p><strong>原有生产要求</strong></p>'
    expect(page.dirty).toBe(true)
    await page.save()
    expect(api.updateProductionTask).toHaveBeenLastCalledWith('task-1', {
      special_requirements_html: '<p><strong>原有生产要求</strong></p>',
    }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it('日期与跟单员和生产要求同时改变时保留全部修改', async () => {
    const { wrapper, page } = await mountPage()
    page.form.delivery_date = '2026-09-30'
    page.form.follower_ids = ['follower-1']
    page.form.special_requirements_html = '<p>新的生产要求</p>'

    await page.save()

    expect(api.updateProductionTask).toHaveBeenCalledWith('task-1', {
      delivery_date: '2026-09-30', follower_ids: ['follower-1'],
      special_requirements_html: '<p>新的生产要求</p>',
    }, {}, {}, '"task-v1"')
    wrapper.unmount()
  })

  it('旧产品缺颜色时日期与数量混合修改仍受产品校验约束', async () => {
    const { wrapper, page } = await mountPage()
    page.form.delivery_date = '2026-09-30'
    page.products[0].quantity = '101'

    await page.save()

    expect(api.updateProductionTask).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith('存在缺少有效颜色的历史产品行，暂不能批量修改数量。')
    expect(page.products[0].quantity).toBe('101')
    wrapper.unmount()
  })

  it.each(['', '2026-08-31'])('空日期或早于下单日期不能保存：%s', async (date) => {
    const { wrapper, page } = await mountPage()
    page.form.delivery_date = date

    await page.save()

    expect(api.updateProductionTask).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('请求失败时保留未保存修改，不跳走', async () => {
    vi.mocked(api.updateProductionTask).mockRejectedValueOnce(new Error('保存失败'))
    const { wrapper, page } = await mountPage()
    page.form.delivery_date = '2026-09-30'

    await page.save()

    expect(ElMessage.error).toHaveBeenCalledWith('保存失败')
    expect(page.dirty).toBe(true)
    expect(router.replace).not.toHaveBeenCalled()
    wrapper.unmount()
  })

})
