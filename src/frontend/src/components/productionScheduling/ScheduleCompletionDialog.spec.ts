import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it } from 'vitest'
import ScheduleCompletionDialog from './ScheduleCompletionDialog.vue'
import type { CompleteScheduleResult, ScheduleCompletionPreview } from '@/types/productionScheduling'

function preview(): ScheduleCompletionPreview {
  return {
    schedule_id: 'schedule-1', schedule_number: 'PC-001', schedule_etag: '"schedule-v1"',
    task: { id: 'task-1', task_number: 'HT-001', status: 'IN_PRODUCTION', status_display: '生产中', etag: '"task-v1"' },
    progress: {
      MATERIAL: { status: 'READY', percentage: 100, display: '100%' }, METAL: { status: 'READY', percentage: 100, display: '100%' },
      SEWING: { status: 'READY', percentage: 100, display: '100%' }, ASSEMBLY: { status: 'READY', percentage: 100, display: '100%' },
    },
    products: [
      { schedule_product_id: 'product-1', product_name: '导演椅', specification: '47×55×79 cm', color: '酒红', material: 'PE', required_quantity: 1200, received_quantity: 1189.5, unit_name: '套' },
      { schedule_product_id: 'product-2', product_name: '面料', specification: '', color: '', material: '', required_quantity: 100, received_quantity: 0, unit_name: '米' },
    ],
    sales_order: { id: 'sales-1', order_number: 'SO-001', status: 'FULFILLING', status_display: '履约中', etag: '"sales-v1"', can_sync: true, reason: '' },
  }
}
function result(sales: Partial<CompleteScheduleResult['sales_sync']> = {}): CompleteScheduleResult {
  return {
    schedule_id: 'schedule-1', production_task_id: 'task-1', production_task_status: 'COMPLETED', progress: preview().progress,
    production_sync: { before_status: 'IN_PRODUCTION', after_status: 'COMPLETED' },
    sales_sync: { status: 'COMPLETED', reason: '销售订单已同步完成。', before_status: 'FULFILLING', after_status: 'COMPLETED', ...sales },
  }
}
const wrappers: ReturnType<typeof mount>[] = []
async function createView(overrides: Partial<InstanceType<typeof ScheduleCompletionDialog>['$props']> = {}) {
  const wrapper = mount(ScheduleCompletionDialog, {
    props: { modelValue: true, preview: preview(), submitting: false, result: null, error: '', uncertain: false, ...overrides },
    global: { plugins: [ElementPlus], stubs: { teleport: true } },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('排产完成确认弹窗', () => {
  it('展示任务、销售、四项进度及每产品单行的独立字段和单位，不生成混合合计', async () => {
    const wrapper = await createView()
    expect(wrapper.text()).toContain('HT-001')
    expect(wrapper.text()).toContain('SO-001')
    expect(wrapper.get('[data-testid="completion-task-status"]').text()).toBe('生产中')
    expect(wrapper.get('[data-testid="completion-sales-status"]').text()).toBe('履约中')
    expect(wrapper.findAll('[data-progress]')).toHaveLength(4)
    expect(wrapper.get('[data-progress="METAL"]').text()).toContain('达到完成条件')
    const table = wrapper.get('[data-testid="completion-products"]')
    expect(table.findAll('thead th').map(cell => cell.text())).toEqual(['产品', '规格', '颜色', '材质', '订单要求（本任务）', '累计成品入库', '单位'])
    expect(table.findAll('tbody tr')).toHaveLength(2)
    expect(table.get('[data-product-id="product-1"]').findAll('td').map(cell => cell.text())).toEqual(['导演椅', '47×55×79 cm', '酒红', 'PE', '1,200', '1,189.5', '套'])
    expect(table.get('[data-product-id="product-2"]').findAll('td').map(cell => cell.text())).toEqual(['面料', '—', '—', '—', '100', '0', '米'])
    expect(table.text()).not.toContain('合计')
    expect(table.text()).not.toContain('¥')
    expect(wrapper.text()).toContain('订单要求按本生产任务产品数量；入库量含已出库数量。')
  })

  it('无法读取销售订单时展示原因且不编造销售号或状态', async () => {
    const value = preview()
    value.sales_order = { id: 'sales-1', order_number: null, status: null, status_display: null, etag: null, can_sync: false, reason: '没有销售订单查看范围，本次不自动同步。' }
    const wrapper = await createView({ preview: value })
    expect(wrapper.text()).toContain('没有销售订单查看范围，本次不自动同步。')
    expect(wrapper.get('[data-testid="completion-sales-status"]').text()).toBe('—')
    expect(wrapper.text()).not.toContain('SO-001')
  })

  it('完成说明必填、限制500字，确认只发送说明并保留窗口', async () => {
    const wrapper = await createView()
    const input = wrapper.get('[data-testid="completion-reason"]')
    expect(input.attributes('maxlength')).toBe('500')
    await input.setValue('   ')
    await wrapper.get('[data-testid="completion-submit"]').trigger('click')
    await expect.poll(() => wrapper.text()).toContain('请填写完成说明')
    expect(wrapper.emitted('confirm')).toBeUndefined()
    await wrapper.get('[data-testid="completion-reason"]').setValue('  全部进度核对完成  ')
    const submit = wrapper.get<HTMLButtonElement>('[data-testid="completion-submit"]').element
    submit.click()
    submit.click()
    await flushPromises()
    expect(wrapper.emitted('confirm')).toEqual([['全部进度核对完成']])
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('父组件同步拒绝且错误保持原值时，下一次渲染恢复编辑和提交', async () => {
    const wrapper = await createView({ error: '完成权限已被撤销。' })
    await wrapper.get('[data-testid="completion-reason"]').setValue('核对完成')
    await wrapper.get('[data-testid="completion-submit"]').trigger('click')
    await flushPromises()
    expect(wrapper.emitted('confirm')).toEqual([['核对完成']])
    expect(wrapper.get('[data-testid="completion-reason"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-testid="completion-close"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-testid="completion-submit"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="completion-reason"]').setValue('修正说明')
    await wrapper.get('[data-testid="completion-submit"]').trigger('click')
    expect(wrapper.emitted('confirm')).toEqual([['核对完成'], ['修正说明']])
  })

  it('提交中只显示等待状态，禁止编辑、关闭及重复确认', async () => {
    const wrapper = await createView()
    await wrapper.get('[data-testid="completion-reason"]').setValue('生产完成')
    await wrapper.get('[data-testid="completion-submit"]').trigger('click')
    await wrapper.setProps({ submitting: true })
    const process = wrapper.get('[data-testid="completion-process"]')
    expect(process.get('[data-step="validation"]').text()).toContain('核验并提交中')
    expect(process.get('[data-step="production"]').text()).toContain('等待更新结果')
    expect(process.get('[data-step="sales"]').text()).toContain('等待同步结果')
    expect(process.text()).not.toContain('校验通过')
    expect(process.findAll('.erp-list-tag--success')).toHaveLength(0)
    expect(wrapper.get('[data-testid="completion-reason"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="completion-close"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('button[aria-label="关闭"]').exists()).toBe(false)
    await wrapper.get('[data-testid="completion-close"]').trigger('click')
    await wrapper.get('.app-window-overlay').trigger('mousedown')
    await wrapper.get('.app-window-overlay').trigger('keydown', { key: 'Escape' })
    await wrapper.get('[data-testid="completion-submit"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(wrapper.emitted('confirm')).toHaveLength(1)
  })

  it('完成后展示真实前后状态，保留弹窗且仅能关闭', async () => {
    const wrapper = await createView()
    await wrapper.get('[data-testid="completion-reason"]').setValue('生产完成')
    await wrapper.get('[data-testid="completion-submit"]').trigger('click')
    await wrapper.setProps({ submitting: true })
    await wrapper.setProps({ submitting: false, result: result() })
    const process = wrapper.get('[data-testid="completion-process"]')
    expect(process.get('[data-step="validation"]').text()).toContain('校验通过')
    expect(process.get('[data-step="production"]').text()).toContain('生产中 → 已完成')
    expect(process.get('[data-step="sales"]').text()).toContain('履约中 → 已完成')
    expect(process.get('[data-step="sales"]').text()).toContain('销售订单已同步完成。')
    expect(wrapper.get('[data-testid="completion-task-status"]').text()).toBe('已完成')
    expect(wrapper.find('[data-testid="completion-submit"]').exists()).toBe(false)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(wrapper.get('[data-testid="completion-close"]').text()).toBe('关闭')
    await wrapper.get('[data-testid="completion-close"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })

  it('销售跳过时显示警告原因，状态缺失不沿用预览状态', async () => {
    const wrapper = await createView({ result: result({ status: 'SKIPPED', reason: '销售订单余款未结清，未同步完成。', before_status: null, after_status: null }) })
    const sales = wrapper.get('[data-step="sales"]')
    expect(sales.get('.erp-list-tag--warning').text()).toBe('未同步')
    expect(sales.text()).toContain('销售订单余款未结清，未同步完成。')
    expect(sales.text()).toContain('— → —')
    expect(sales.text()).not.toContain('履约中')
    expect(wrapper.get('[data-testid="completion-sales-status"]').text()).toBe('—')
  })

  it.each([
    ['ALREADY_COMPLETED', '已是完成状态', 'success'],
    ['NOT_APPLICABLE', '无需同步', 'info'],
  ] as const)('销售结果%s按实际状态展示', async (status, label, tone) => {
    const wrapper = await createView({ result: result({ status, reason: status === 'NOT_APPLICABLE' ? '未关联销售订单。' : '销售订单此前已完成。', before_status: null, after_status: null }) })
    expect(wrapper.get('[data-step="sales"] .erp-list-tag').text()).toBe(label)
    expect(wrapper.get('[data-step="sales"] .erp-list-tag').classes()).toContain(`erp-list-tag--${tone}`)
    expect(wrapper.find('[data-testid="completion-submit"]').exists()).toBe(false)
  })

  it('结果待核实时不允许重试，提示关闭后刷新核实', async () => {
    const wrapper = await createView({ error: '连接中断，未收到响应。', uncertain: true })
    expect(wrapper.text()).toContain('更新结果待核实')
    expect(wrapper.text()).toContain('刷新列表核实')
    expect(wrapper.find('[data-testid="completion-submit"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="completion-reason"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-step="production"]').text()).not.toContain('未更新')
    expect(wrapper.emitted('confirm')).toBeUndefined()
    await wrapper.get('[data-testid="completion-close"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })

  it('普通提交错误保留说明，明确未更新并允许修正重试', async () => {
    const wrapper = await createView()
    await wrapper.get('[data-testid="completion-reason"]').setValue('原说明')
    await wrapper.get('[data-testid="completion-submit"]').trigger('click')
    await wrapper.setProps({ submitting: true })
    await wrapper.setProps({ submitting: false, error: '排产版本已变化，请刷新后重试。' })
    expect(wrapper.get<HTMLTextAreaElement>('[data-testid="completion-reason"]').element.value).toBe('原说明')
    expect(wrapper.get('[data-testid="completion-error"]').text()).toContain('生产任务和销售订单未更新')
    expect(wrapper.get('[data-step="production"]').text()).toContain('未更新')
    await wrapper.get('[data-testid="completion-reason"]').setValue('修正后的说明')
    await wrapper.get('[data-testid="completion-submit"]').trigger('click')
    expect(wrapper.emitted('confirm')).toEqual([['原说明'], ['修正后的说明']])
  })

  it('缺少预览时不允许提交，空产品表显示明确信息', async () => {
    const wrapper = await createView({ preview: null })
    expect(wrapper.get('[data-testid="completion-submit"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('暂无可确认的排产信息')
    const value = preview()
    value.products = []
    await wrapper.setProps({ preview: value })
    expect(wrapper.get('[data-testid="completion-products"]').text()).toContain('暂无产品数量信息')
  })
})
