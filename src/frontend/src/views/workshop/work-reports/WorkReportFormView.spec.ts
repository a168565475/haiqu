import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElDatePicker, ElInput, ElMessage, ElMessageBox, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WorkReportFormView from './WorkReportFormView.vue'

const mocks = vi.hoisted(() => ({
  context: vi.fn(),
  create: vi.fn(),
  price: vi.fn(),
  report: vi.fn(),
  update: vi.fn(),
  push: vi.fn(),
}))
const route = vi.hoisted(() => ({
  params: { reportId: 'report-1' } as Record<string, string>,
  query: {} as Record<string, string>,
}))

vi.mock('vue-router', () => ({
  useRoute: () => route,
  useRouter: () => ({ back: vi.fn(), push: mocks.push }),
}))
vi.mock('@/api/workshopReporting', () => ({
  createWorkReport: mocks.create,
  fetchPriceContext: mocks.price,
  fetchReportingContext: mocks.context,
  fetchWorkReport: mocks.report,
  updateWorkReport: mocks.update,
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { username: 'admin', display_name: '超级管理员' } }),
}))

const wrappers: ReturnType<typeof mount>[] = []
const scheme = {
  id: 'scheme-1', scheme_number: 'GJ-001', status: 'APPROVED', status_display: '已批准', version: 1, revision: 3,
  can_create_change: true, parent_scheme: null, product_line_id: 'line-1', schedule_product_id: 'product-1',
  production_task: { id: 'task-1', task_number: 'TASK-1', order_number: 'ORDER-1' },
  product: { name: '折叠椅', number: 'P-1', specification: '' }, workshop: { id: 'workshop-1', name: '金工车间' },
  scope_craft: { id: 'craft-1', name: '管材加工', plan_category: 'METAL' },
  crafts: [], operation_product_name: '折叠椅', effective_from: '2026-09-01', effective_to: null, remark: '',
  line_count: 1, declared_total: '2.3450', events: [], approved_by: '厂长', approved_at: '2026-09-01T00:00:00Z',
  created_by_id: 'employee-1', created_by: '负责人', created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
  lines: [{
    id: 'scheme-line-1', line_number: 1, work_item_id: 'work-item-1', craft_id: 'craft-1', operation_id: 'operation-1',
    display_name: '前脚切管', craft_name: '管材加工', operation_name: '切管', operation_number: 'OP-1', unit_name: '',
    previous_price: null, revised_price: null, declared_price: '2.3450', status: 'ACTIVE', note: '',
    bom_component_identity: 'component-1', counting_mode: 'PIECE', counting_mode_display: '按片',
    order_quantity: '100', required_quantity: '200.0000',
    production_description: '按定位线切割', production_date_quantity: '1.0000', cumulative_quantity: '5.0000',
    last_workshop_employee_id: 'worker-1',
  }],
}

beforeEach(() => {
  vi.clearAllMocks()
  route.params = { reportId: 'report-1' }
  route.query = {}
  mocks.report.mockResolvedValue({
    etag: '"report-etag"',
    data: {
      id: 'report-1', report_number: 'BG-001', production_date: '2026-09-16',
      production_task: { id: 'task-1', task_number: 'TASK-1', order_number: 'ORDER-1' },
      product: { name: '折叠椅', number: 'P-1' }, product_line_id: 'line-1', schedule_product_id: 'product-1',
      workshop: { id: 'workshop-1', name: '金工车间' }, scheme_id: 'scheme-1', scheme_version: 1, revision: 1,
      scope_craft: { id: 'craft-1', name: '管材加工', plan_category: 'METAL' }, completed_plan: false,
      recorder: '负责人', updated_by: '负责人', total_amount: '4.69', line_count: 1,
      created_at: '2026-09-16T00:00:00Z', updated_at: '2026-09-16T00:00:00Z',
      lines: [{
        id: 'report-line-1', line_number: 1, scheme_line_id: 'scheme-line-1', work_item_id: 'work-item-1',
        workshop_employee_id: 'worker-1', employee_name: '员工甲', production_line: null,
        display_name: '前脚切管', craft_name: '管材加工', operation_name: '切管', unit_name: '',
        quantity: '2.0000', order_quantity_snapshot: 100, unit_price: '2.3450', amount: '4.69',
      }],
    },
  })
  mocks.context.mockResolvedValue({
    schedule_product: null,
    schedule_products: [{ id: 'product-1', product_line_id: 'line-1', production_task_id: 'task-1', task_number: 'TASK-1', product_name: '折叠椅', product_number: 'P-1', planned_quantity: '100', order_quantity: '100', unit_name: '件' }],
    workshops: [{ id: 'workshop-1', name: '金工车间' }], crafts: [{ id: 'craft-1', name: '管材加工', workshop_id: 'workshop-1', plan_category: 'METAL' }], operations: [],
    bom_items: [{ id: 'bom-line-1', component_identity: 'component-1', name: '前脚切管', material: '铁', specification: '', label: '前脚切管-铁', source_type: 'METAL', pieces_per_product: 2, cutting_sets_per_product: null, cutting_pieces_per_set: null }],
    employees: [{ id: 'worker-1', name: '员工甲', workshop_id: 'workshop-1' }],
  })
  mocks.price.mockResolvedValue(scheme)
  mocks.update.mockResolvedValue({ data: {}, etag: '"next-etag"' })
})

afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('报工直接编辑', () => {
  it.each([
    ['task-1', { production_task_id: 'task-1', workshop_id: 'workshop-1' }],
    ['other-task', { schedule_product_id: 'product-1', workshop_id: 'workshop-1', craft_id: 'craft-1' }],
  ])('编辑保存时仅保留与当前报工一致的任务范围：%s', async (taskId, expectedQuery) => {
    route.query = { production_task_id: taskId }
    const wrapper = mount(WorkReportFormView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('保存修改'))!.trigger('click')
    await flushPromises()
    expect(mocks.update).toHaveBeenCalledTimes(1)
    expect(mocks.push).toHaveBeenCalledWith({ name: 'work-report-days', query: expectedQuery })
  })

  it('回填原单并携带 ETag 保存修改', async () => {
    const wrapper = mount(WorkReportFormView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    expect(mocks.report).toHaveBeenCalledWith('report-1')
    expect(mocks.context).toHaveBeenCalledWith('product-1', 'work_report')
    expect(mocks.price).toHaveBeenCalledWith({ product_line_id: 'line-1', schedule_product_id: 'product-1', workshop_id: 'workshop-1', craft_id: 'craft-1', production_date: '2026-09-16' })
    expect(wrapper.text()).toContain('编辑报工')
    expect(wrapper.text()).toContain('本次报工')
    expect(wrapper.text()).toContain('订单数量')
    expect(wrapper.text()).toContain('需完成次数')
    expect(wrapper.text()).toContain('累计报工')
    expect(wrapper.text()).not.toContain('当日 / 累计')
    expect(wrapper.find('.wr-work-report-table').text()).toContain('200')
    expect(wrapper.find('.wr-work-report-table').text()).toContain('5')
    expect(wrapper.text()).not.toContain('未配置单位')
    expect(wrapper.find('.el-input-group__append').exists()).toBe(false)
    const quantityInput = wrapper.findAllComponents(ElInput).find(input => input.props('modelValue') === '2.0000')!
    expect(quantityInput.exists()).toBe(true)
    expect(wrapper.find('.wr-work-report-table').text()).toContain('切管')
    expect(wrapper.findAllComponents(ElSelect).some(select => select.props('modelValue') === 'scheme-line-1')).toBe(false)

    quantityInput.vm.$emit('update:modelValue', '4.0000')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('保存修改'))!.trigger('click')
    await flushPromises()

    expect(mocks.update).toHaveBeenCalledWith(
      'report-1',
      expect.objectContaining({
        production_date: '2026-09-16', schedule_product_id: 'product-1', scheme_id: 'scheme-1', scheme_revision: 3,
        lines: [{ scheme_line_id: 'scheme-line-1', workshop_employee_id: 'worker-1', production_line: null, quantity: '4.0000' }],
      }),
      '"report-etag"',
    )
    expect(mocks.create).not.toHaveBeenCalled()
    expect(mocks.push).toHaveBeenCalledWith({ name: 'work-report-days', query: { schedule_product_id: 'product-1', workshop_id: 'workshop-1', craft_id: 'craft-1' } })
  })

  it('修改生产日期后使用新日期匹配的方案提交', async () => {
    const nextScheme = {
      ...scheme,
      id: 'scheme-2', scheme_number: 'GJ-002', version: 2, revision: 4,
      lines: [{ ...scheme.lines[0], id: 'scheme-line-2', declared_price: '3.0000' }],
    }
    mocks.price.mockReset()
    mocks.price.mockResolvedValueOnce(scheme).mockResolvedValueOnce(nextScheme)
    const wrapper = mount(WorkReportFormView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    wrapper.findComponent(ElDatePicker).vm.$emit('update:modelValue', '2026-09-17')
    await flushPromises()

    expect(mocks.price).toHaveBeenLastCalledWith({ product_line_id: 'line-1', schedule_product_id: 'product-1', workshop_id: 'workshop-1', craft_id: 'craft-1', production_date: '2026-09-17' })
    expect(wrapper.find('.wr-work-report-table').text()).toContain('¥3')
    expect(wrapper.find('.wr-report-basic-card').text()).not.toContain('工价方案')
    expect(wrapper.findAllComponents(ElSelect).some(select => select.props('modelValue') === 'worker-1')).toBe(true)
    const quantityInput = wrapper.findAllComponents(ElInput).find(input => input.props('modelValue') === '')!
    quantityInput.vm.$emit('update:modelValue', '2.0000')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('保存修改'))!.trigger('click')
    await flushPromises()

    expect(mocks.update).toHaveBeenCalledWith(
      'report-1',
      expect.objectContaining({
        production_date: '2026-09-17', scheme_id: 'scheme-2', scheme_revision: 4,
        lines: [{ scheme_line_id: 'scheme-line-2', workshop_employee_id: 'worker-1', production_line: null, quantity: '2.0000' }],
      }),
      '"report-etag"',
    )
  })

  it('完成次数为小数时不提交', async () => {
    const wrapper = mount(WorkReportFormView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    const quantityInput = wrapper.findAllComponents(ElInput).find(input => input.props('modelValue') === '2.0000')!
    expect(quantityInput.props('inputmode')).toBe('numeric')
    quantityInput.vm.$emit('update:modelValue', '0.5')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('保存修改'))!.trigger('click')
    await flushPromises()

    expect(mocks.update).not.toHaveBeenCalled()
  })

  it('完成次数超过剩余可报数量时输入框变红并显示当前上限', async () => {
    const wrapper = mount(WorkReportFormView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    const quantityInput = wrapper.findAllComponents(ElInput).find(input => input.props('modelValue') === '2.0000')!
    quantityInput.vm.$emit('update:modelValue', '198')
    await flushPromises()

    const field = wrapper.find('.wr-quantity-field')
    expect(field.classes()).toContain('is-error')
    expect(field.text()).toContain('当前最多可报 197')
  })

  it('金工缺少员工时只提示员工，不出现装配线文案', async () => {
    route.params = {}
    route.query = { schedule_product_id: 'product-1', workshop_id: 'workshop-1', craft_id: 'craft-1' }
    mocks.price.mockResolvedValue({
      ...scheme,
      lines: scheme.lines.map(line => ({ ...line, last_workshop_employee_id: null })),
    })
    const warning = vi.spyOn(ElMessage, 'warning')
    const wrapper = mount(WorkReportFormView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    const quantityInput = wrapper.findAllComponents(ElInput).find(input => input.props('inputmode') === 'numeric')!
    quantityInput.vm.$emit('update:modelValue', '1')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('提交报工'))!.trigger('click')
    await flushPromises()

    expect(warning).toHaveBeenCalledWith('请选择员工。')
    expect(warning.mock.calls.flat().join('')).not.toContain('装配线')
    expect(mocks.create).not.toHaveBeenCalled()
  })

  it('从计划带入产品和车间时自动匹配工价方案并生成工序行', async () => {
    route.params = {}
    route.query = { schedule_product_id: 'product-1', workshop_id: 'workshop-1', craft_id: 'craft-1' }
    const wrapper = mount(WorkReportFormView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    expect(mocks.context).toHaveBeenCalledWith('product-1', 'work_report')
    expect(mocks.price).toHaveBeenCalledWith({
      product_line_id: 'line-1', schedule_product_id: 'product-1', workshop_id: 'workshop-1', craft_id: 'craft-1', production_date: expect.any(String),
    })
    expect(wrapper.text()).toContain('新增报工')
    expect(wrapper.find('.wr-report-basic-card').text()).not.toContain('工价方案')
    expect(wrapper.find('.wr-report-basic-card').text()).not.toContain('报工类别')
    expect(wrapper.findAll('.wr-work-report-table .el-table__row')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('添加工序')
    expect(wrapper.find('.wr-work-report-table').text()).not.toContain('删除')
    expect(wrapper.findAllComponents(ElSelect).some(select => select.props('modelValue') === 'scheme-line-1')).toBe(false)
    expect(wrapper.find('.wr-heading').findAll('button')).toHaveLength(0)
    expect(wrapper.find('.wr-report-actions').text()).toContain('返回')
    expect(wrapper.find('.wr-report-actions').text()).toContain('提交报工')
  })

  it('新一次报工默认带出同一工作项上次的员工', async () => {
    route.params = {}
    route.query = { schedule_product_id: 'product-1', workshop_id: 'workshop-1', craft_id: 'craft-1' }
    const wrapper = mount(WorkReportFormView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    expect(mocks.price).toHaveBeenCalledWith(expect.objectContaining({ schedule_product_id: 'product-1' }))
    expect(wrapper.findAllComponents(ElSelect).some(select => select.props('modelValue') === 'worker-1')).toBe(true)
  })

  it('本次数量为空或零的行不校验员工且不提交', async () => {
    route.params = {}
    route.query = { schedule_product_id: 'product-1', workshop_id: 'workshop-1', craft_id: 'craft-1' }
    const schemeWithSkippedLines = {
      ...scheme,
      lines: [
        { ...scheme.lines[0], id: 'scheme-line-1', work_item_id: 'work-item-1', last_workshop_employee_id: 'worker-1' },
        { ...scheme.lines[0], id: 'scheme-line-2', work_item_id: 'work-item-2', operation_name: '打磨', last_workshop_employee_id: null },
        { ...scheme.lines[0], id: 'scheme-line-3', work_item_id: 'work-item-3', operation_name: '冲孔', last_workshop_employee_id: null },
      ],
    }
    mocks.price.mockResolvedValue(schemeWithSkippedLines)
    mocks.create.mockResolvedValue({})
    const warning = vi.spyOn(ElMessage, 'warning')
    const wrapper = mount(WorkReportFormView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    const quantityInputs = wrapper.findAllComponents(ElInput).filter(input => input.props('inputmode') === 'numeric')
    quantityInputs[0]!.vm.$emit('update:modelValue', '2')
    quantityInputs[1]!.vm.$emit('update:modelValue', '0')
    quantityInputs[2]!.vm.$emit('update:modelValue', '')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('提交报工'))!.trigger('click')
    await flushPromises()

    expect(warning).not.toHaveBeenCalledWith('请选择员工。')
    expect(warning).not.toHaveBeenCalledWith('请输入正整数完成次数。')
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      lines: [{ scheme_line_id: 'scheme-line-1', workshop_employee_id: 'worker-1', production_line: null, quantity: '2' }],
    }))
  })

  it('完成计划确认弹窗使用报工规范主按钮', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue(
      'confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>,
    )
    const wrapper = mount(WorkReportFormView, { global: { plugins: [ElementPlus] } })
    wrappers.push(wrapper)
    await flushPromises()

    const quantityInput = wrapper.findAllComponents(ElInput).find(input => input.props('modelValue') === '2.0000')!
    quantityInput.vm.$emit('update:modelValue', '197')
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('保存修改'))!.trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalledWith(
      expect.any(String),
      '确认完成生产计划',
      expect.objectContaining({
        confirmButtonText: '确认完成并提交',
        cancelButtonText: '取消',
        customClass: 'wr-confirm-message-box',
      }),
    )
    confirm.mockRestore()
  })
})
