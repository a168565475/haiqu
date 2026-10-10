import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WageSchemeFormView from './WageSchemeFormView.vue'

const api = vi.hoisted(() => ({
  create: vi.fn(),
  createChange: vi.fn(),
  context: vi.fn(),
  detail: vi.fn(),
  history: vi.fn(),
  submit: vi.fn(),
  update: vi.fn(),
}))
const router = vi.hoisted(() => ({ back: vi.fn(), push: vi.fn(), replace: vi.fn() }))

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: {}, query: {} }),
  useRouter: () => router,
}))
vi.mock('@/api/workshopReporting', () => ({
  createWageScheme: api.create,
  createWageSchemeChange: api.createChange,
  fetchReportingContext: api.context,
  fetchWageScheme: api.detail,
  fetchWageSchemeHistory: api.history,
  submitWageScheme: api.submit,
  updateWageScheme: api.update,
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { is_superuser: true }, hasPermission: () => true }),
}))

const wrappers: ReturnType<typeof mount>[] = []

function reportingContext(productIds: string[]) {
  const scheduleProducts = productIds.map(id => ({
    id,
    task_number: `TASK-${id}`,
    order_number: `ORDER-${id}`,
    product_name: `产品-${id}`,
    product_number: id,
    product_line_id: `line-${id}`,
    order_quantity: '100',
  }))
  return {
    schedule_product: scheduleProducts[0] || null,
    schedule_products: scheduleProducts,
    workshops: [{ id: 'workshop-1', name: '装配车间' }],
    crafts: [{ id: 'craft-1', name: '装配', workshop_id: 'workshop-1', plan_category: null as string | null }],
    operations: [{
      id: 'operation-1', operation_number: 'GX-001', product_name: '标准工序品名',
      name: '切管', craft_id: 'craft-1', unit_id: 'unit-1' as string | null, unit_name: '件' as string | null,
    }],
  }
}

function metalReportingContext(productIds: string[]) {
  const context = reportingContext(productIds)
  context.workshops[0] = { id: 'workshop-1', name: '金工车间' }
  context.crafts[0] = { ...context.crafts[0]!, name: '管材加工', plan_category: null }
  context.operations.push({
    id: 'operation-2', operation_number: 'GX-002', product_name: '另一个目录品名',
    name: '弯管', craft_id: 'craft-1', unit_id: null, unit_name: null,
  })
  return {
    ...context,
    bom_items: [{
      id: 'bom-line-1', component_identity: 'component-1', name: '前脚管', material: '铁', specification: '20*1.0*500',
      label: '前脚管-铁-20*1.0*500', source_type: 'METAL', pieces_per_product: 2,
      cutting_sets_per_product: null, cutting_pieces_per_set: null,
    }],
  }
}

async function render() {
  const wrapper = mount(WageSchemeFormView, { global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

function productSelect(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAllComponents(ElSelect)[0]!
}

function selectByTestId(wrapper: ReturnType<typeof mount>, testId: string) {
  const select = wrapper.findAllComponents(ElSelect).find(item => item.attributes('data-testid') === testId)
  if (!select) throw new Error(`找不到下拉框：${testId}`)
  return select
}

function declaredPriceInput(wrapper: ReturnType<typeof mount>) {
  const input = wrapper.findAllComponents({ name: 'ElInput' }).find(item => (
    (item.props('inputmode') === 'decimal' || item.attributes('inputmode') === 'decimal')
    && item.props('modelValue') === ''
  ))
  if (!input) throw new Error('找不到申报工价输入框')
  return input
}

function inputByTestId(wrapper: ReturnType<typeof mount>, testId: string) {
  const marker = wrapper.find(`[data-testid="${testId}"]`)
  if (!marker.exists()) throw new Error(`找不到输入框：${testId}`)
  return marker
}

beforeEach(() => {
  vi.clearAllMocks()
  api.context.mockResolvedValue(reportingContext(['product-a', 'product-b']))
})

afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  vi.restoreAllMocks()
})

describe('工价方案产品上下文切换', () => {
  it('新增页从未选择到首次选择产品时重新请求对应上下文', async () => {
    const wrapper = await render()

    productSelect(wrapper).vm.$emit('update:modelValue', 'product-a')
    await flushPromises()

    expect(api.context).toHaveBeenNthCalledWith(1, undefined)
    expect(api.context).toHaveBeenNthCalledWith(2, 'product-a')
    const orderInput = wrapper.findAllComponents({ name: 'ElInput' })[0]!
    expect(orderInput.props('readonly')).toBe(true)
    expect(orderInput.props('modelValue')).toBe('ORDER-product-a')
  })

  it('快速连续切换产品时忽略较早请求的迟到响应', async () => {
    const wrapper = await render()
    let resolveFirst!: (value: ReturnType<typeof reportingContext>) => void
    let resolveLatest!: (value: ReturnType<typeof reportingContext>) => void
    api.context
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveLatest = resolve }))

    productSelect(wrapper).vm.$emit('update:modelValue', 'product-a')
    await nextTick()
    productSelect(wrapper).vm.$emit('update:modelValue', 'product-b')
    await nextTick()

    resolveLatest(reportingContext(['latest-product']))
    await flushPromises()
    resolveFirst(reportingContext(['stale-product']))
    await flushPromises()

    const productIds = wrapper.findAllComponents({ name: 'ElOption' }).map(option => option.props('value'))
    expect(api.context).toHaveBeenCalledWith('product-a')
    expect(api.context).toHaveBeenCalledWith('product-b')
    expect(productIds).toContain('latest-product')
    expect(productIds).not.toContain('stale-product')
  })

  it('隐藏冗余说明和顶部按钮，并在底部展示原型操作区', async () => {
    const wrapper = await render()

    expect(wrapper.find('.wr-heading').findAll('button')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('工价按具体生产任务产品、车间、工艺和稳定工作项保存')
    expect(wrapper.text()).not.toContain('以往工价、修改工价和申报工价互不联动')
    expect(wrapper.find('.wr-form-actions').text()).toContain('返回')
    expect(wrapper.find('.wr-form-actions').text()).not.toContain('保存草稿')
    expect(wrapper.find('.wr-form-actions').text()).toContain('提交厂长审批')
    const columns = wrapper.findAllComponents({ name: 'ElTableColumn' }).map(column => column.props('label'))
    expect(columns).toEqual([
      '名称 / 部位', '申报工序', '需完成次数', '制作工序描述', '申报工价', '状态',
      '以往工价', '修改工价', '备注', '操作',
    ])
    expect(columns).not.toContain('工艺')
    expect(wrapper.findAllComponents(ElSelect)[2]!.props('multiple')).not.toBe(true)
  })

  it('工价合计最多显示三位小数并去掉末尾零', async () => {
    const wrapper = await render()
    productSelect(wrapper).vm.$emit('update:modelValue', 'product-a')
    await flushPromises()
    wrapper.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'workshop-1')
    await nextTick()
    await wrapper.find('.wr-card--wide .el-button--primary').trigger('click')
    await nextTick()
    expect(wrapper.findAll('.wr-wage-line-table .el-table__row')).toHaveLength(1)

    const priceInput = declaredPriceInput(wrapper)
    priceInput.vm.$emit('update:modelValue', '1.1000')
    await nextTick()
    expect(wrapper.find('.wr-total').text()).toContain('¥1.1')

    priceInput.vm.$emit('update:modelValue', '1.1236')
    await nextTick()
    expect(wrapper.find('.wr-total').text()).toContain('¥1.124')
  })

  it('金工单工艺自动选中，隐藏工序品名并使用全部管材工序和 BOM 部件材质规格', async () => {
    api.context.mockResolvedValue(metalReportingContext(['product-a']))
    const wrapper = await render()

    wrapper.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'workshop-1')
    await flushPromises()

    const craftSelect = selectByTestId(wrapper, 'wage-craft-select')
    expect(craftSelect.props('modelValue')).toBe('craft-1')
    expect(wrapper.find('[data-testid="operation-product-name-field"]').exists()).toBe(false)

    await wrapper.find('.wr-card--wide .el-button--primary').trigger('click')
    await nextTick()

    const operationSelect = selectByTestId(wrapper, 'wage-operation-select')
    const operationValues = operationSelect.findAllComponents({ name: 'ElOption' }).map(option => option.props('value'))
    expect(operationValues).toEqual(['operation-1', 'operation-2'])
    const unitlessOperation = operationSelect.findAllComponents({ name: 'ElOption' })[1]!
    expect(unitlessOperation.props('disabled')).not.toBe(true)
    expect(unitlessOperation.props('label')).toBe('弯管')
    const bomSelect = selectByTestId(wrapper, 'metal-bom-display-select')
    expect(bomSelect.exists()).toBe(true)
    expect(bomSelect.findAllComponents({ name: 'ElOption' }).map(option => option.props('label')))
      .toEqual(['前脚管-铁-20*1.0*500'])
    expect(bomSelect.props('placeholder')).toBe('选择部件、材质和规格')
  })

  it('非金工工序同时按车间、工艺和工序品名过滤', async () => {
    const context = reportingContext(['product-a'])
    context.operations.push({
      id: 'operation-other-product', operation_number: 'GX-009', product_name: '其他工序品名',
      name: '其他工序', craft_id: 'craft-1', unit_id: 'unit-1', unit_name: '件',
    })
    api.context.mockResolvedValue(context)
    const wrapper = await render()

    wrapper.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'workshop-1')
    await flushPromises()
    wrapper.find('[data-testid="operation-product-name-field"]').findComponent(ElSelect)
      .vm.$emit('update:modelValue', '标准工序品名')
    await nextTick()
    await wrapper.find('.wr-card--wide .el-button--primary').trigger('click')
    await nextTick()

    const operationValues = selectByTestId(wrapper, 'wage-operation-select')
      .findAllComponents({ name: 'ElOption' }).map(option => option.props('value'))
    expect(operationValues).toEqual(['operation-1'])
  })

  it('金工工艺未绑定计划分类时仍按金工规则提交', async () => {
    const context = metalReportingContext(['product-a'])
    api.context.mockResolvedValue(context)
    api.create.mockResolvedValue({ data: { id: 'scheme-metal' }, etag: '"1"' })
    api.submit.mockResolvedValue({ data: { id: 'scheme-metal' }, etag: '"2"' })
    const wrapper = await render()

    productSelect(wrapper).vm.$emit('update:modelValue', 'product-a')
    await flushPromises()
    wrapper.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'workshop-1')
    await nextTick()
    expect(selectByTestId(wrapper, 'wage-craft-select').props('modelValue')).toBe('craft-1')
    expect(wrapper.find('[data-testid="operation-product-name-field"]').exists()).toBe(false)
    await wrapper.find('.wr-card--wide .el-button--primary').trigger('click')
    await nextTick()
    selectByTestId(wrapper, 'wage-operation-select').vm.$emit('update:modelValue', 'operation-2')
    const bomSelect = selectByTestId(wrapper, 'metal-bom-display-select')
    bomSelect.vm.$emit('update:modelValue', 'bom-line-1')
    bomSelect.vm.$emit('change', 'bom-line-1')
    declaredPriceInput(wrapper).vm.$emit('update:modelValue', '1.0000')
    await nextTick()
    await wrapper.findAll('.wr-form-actions button').at(-1)!.trigger('click')
    await flushPromises()

    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({
      craft_ids: ['craft-1'],
    }))
    expect(api.create.mock.calls[0]![0]).not.toHaveProperty('operation_product_name')
  })

  it('底部提交按钮创建方案后直接使用返回的版本提交审批', async () => {
    api.create.mockResolvedValue({ data: { id: 'scheme-1' }, etag: '"1"' })
    api.submit.mockResolvedValue({ data: { id: 'scheme-1' }, etag: '"2"' })
    const wrapper = await render()

    productSelect(wrapper).vm.$emit('update:modelValue', 'product-a')
    await flushPromises()
    const scopeSelects = wrapper.findAllComponents(ElSelect)
    scopeSelects[1]!.vm.$emit('update:modelValue', 'workshop-1')
    scopeSelects[2]!.vm.$emit('update:modelValue', 'craft-1')
    scopeSelects[3]!.vm.$emit('update:modelValue', '标准工序品名')
    await nextTick()
    await wrapper.find('.wr-card--wide .el-button--primary').trigger('click')
    await nextTick()

    const rowSelects = wrapper.findAllComponents(ElSelect)
    rowSelects[4]!.vm.$emit('update:modelValue', 'operation-1')
    await nextTick()
    rowSelects[4]!.vm.$emit('change', 'operation-1')
    await nextTick()
    await inputByTestId(wrapper, 'wage-production-description-input').setValue('按定位线精准下料')
    await inputByTestId(wrapper, 'wage-line-note-input').setValue('首件确认后批量制作')
    declaredPriceInput(wrapper).vm.$emit('update:modelValue', '1.0000')
    await nextTick()
    await wrapper.findAll('.wr-form-actions button').at(-1)!.trigger('click')
    await flushPromises()

    expect(api.create).toHaveBeenCalledTimes(1)
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({
      lines: [expect.objectContaining({
        production_description: '按定位线精准下料',
        note: '首件确认后批量制作',
      })],
    }))
    expect(api.submit).toHaveBeenCalledWith('scheme-1', '"1"')
  })

  it('提交前阻止科学计数法金额，避免合计与后端保存值不一致', async () => {
    const wrapper = await render()

    productSelect(wrapper).vm.$emit('update:modelValue', 'product-a')
    await flushPromises()
    const scopeSelects = wrapper.findAllComponents(ElSelect)
    scopeSelects[1]!.vm.$emit('update:modelValue', 'workshop-1')
    scopeSelects[2]!.vm.$emit('update:modelValue', 'craft-1')
    scopeSelects[3]!.vm.$emit('update:modelValue', '标准工序品名')
    await nextTick()
    await wrapper.find('.wr-card--wide .el-button--primary').trigger('click')
    await nextTick()

    const rowSelects = wrapper.findAllComponents(ElSelect)
    rowSelects[4]!.vm.$emit('update:modelValue', 'operation-1')
    await nextTick()
    rowSelects[4]!.vm.$emit('change', 'operation-1')
    await nextTick()
    declaredPriceInput(wrapper).vm.$emit('update:modelValue', '1E-1')
    await nextTick()
    await wrapper.findAll('.wr-form-actions button').at(-1)!.trigger('click')
    await flushPromises()

    expect(api.create).not.toHaveBeenCalled()
    expect(api.submit).not.toHaveBeenCalled()
  })

  it('提交响应丢失时重新读取状态，不重复创建或更新方案', async () => {
    api.create.mockResolvedValue({ data: { id: 'scheme-1' }, etag: '"1"' })
    api.submit.mockRejectedValue({ response: { data: { error: { message: '网络中断' } } } })
    api.detail.mockResolvedValue({ data: { id: 'scheme-1', status: 'PENDING_APPROVAL' }, etag: '"2"' })
    const wrapper = await render()

    productSelect(wrapper).vm.$emit('update:modelValue', 'product-a')
    await flushPromises()
    const scopeSelects = wrapper.findAllComponents(ElSelect)
    scopeSelects[1]!.vm.$emit('update:modelValue', 'workshop-1')
    scopeSelects[2]!.vm.$emit('update:modelValue', 'craft-1')
    scopeSelects[3]!.vm.$emit('update:modelValue', '标准工序品名')
    await nextTick()
    await wrapper.find('.wr-card--wide .el-button--primary').trigger('click')
    await nextTick()

    const rowSelects = wrapper.findAllComponents(ElSelect)
    rowSelects[4]!.vm.$emit('update:modelValue', 'operation-1')
    await nextTick()
    rowSelects[4]!.vm.$emit('change', 'operation-1')
    await nextTick()
    declaredPriceInput(wrapper).vm.$emit('update:modelValue', '1.0000')
    await nextTick()
    await wrapper.findAll('.wr-form-actions button').at(-1)!.trigger('click')
    await flushPromises()

    expect(api.create).toHaveBeenCalledTimes(1)
    expect(api.update).not.toHaveBeenCalled()
    expect(api.detail).toHaveBeenCalledWith('scheme-1')
    expect(router.replace).toHaveBeenCalledWith({ name: 'wage-schemes', query: { detail: 'scheme-1' } })
  })
})
