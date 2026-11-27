import { DOMWrapper, flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElSelect } from 'element-plus'
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
    product_code: `CODE-${id}`,
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
      label: '前脚管-铁-20*1.0*500', display_label: '前脚管-铁-20*1.0*500-500mm', source_type: 'METAL', pieces_per_product: 2,
      component_kind: '', parts_per_product: null, pieces_per_part: null,
      unit: '支',
      cutting_sets_per_product: null, cutting_pieces_per_set: null,
    }],
  }
}

function componentReportingContext(category: 'CUTTING' | 'SEWING') {
  const context = reportingContext(['product-a'])
  context.workshops[0] = { id: 'workshop-1', name: category === 'CUTTING' ? '裁剪车间' : '车缝车间' }
  context.crafts[0] = {
    ...context.crafts[0]!, name: category === 'CUTTING' ? '裁剪' : '车缝', plan_category: category,
  }
  context.operations[0] = {
    ...context.operations[0]!, name: category === 'CUTTING' ? '裁片裁剪' : '整套车缝',
  }
  return {
    ...context,
    bom_items: [
      {
        id: 'cut-piece-1', component_identity: 'cut-piece-identity', name: '椅面裁片', material: '布', specification: 'A款',
        label: '椅面裁片-A款', source_type: 'CUTTING', component_kind: 'CUT_PIECE',
        pieces_per_product: null, parts_per_product: 2, pieces_per_part: 3,
        unit: '片',
        cutting_sets_per_product: null, cutting_pieces_per_set: null,
      },
      {
        id: 'sewn-part-1', component_identity: 'sewn-part-identity', name: '椅面部位', material: '布', specification: 'A款',
        label: '椅面部位-A款', source_type: 'CUTTING', component_kind: 'SEWN_PART',
        pieces_per_product: null, parts_per_product: 2, pieces_per_part: null,
        unit: '套',
        cutting_sets_per_product: null, cutting_pieces_per_set: null,
      },
    ],
  }
}

function historyScheme() {
  return {
    id: 'history-1', scheme_number: 'GJ-HISTORY', workshop: { id: 'workshop-1', name: '金工车间' },
    crafts: [{ id: 'craft-1', name: '管材加工' }], operation_product_name: '管材加工',
    production_task: { task_number: 'TASK-HISTORY' }, product: { name: '历史产品', code: 'ERP-001', number: 'ITEM-001', specification: '60×40cm' },
    effective_from: '2026-10-01', effective_to: null,
    created_at: '2026-11-04T01:23:45Z', declared_total: '1.2500',
    lines: [{
      bom_component_identity: 'other-product-component', display_name: '前脚管-铁-20*1.0*500',
      craft_id: 'craft-1', operation_id: 'operation-1', counting_mode: 'PIECE',
      production_description: '历史制作说明', declared_price: '1.25', note: '历史备注', status: 'ACTIVE',
    }],
  }
}

async function openMetalHistory(context = metalReportingContext(['product-a'])) {
  api.context.mockResolvedValue(context)
  const wrapper = await render()
  productSelect(wrapper).vm.$emit('update:modelValue', 'product-a')
  await flushPromises()
  wrapper.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'workshop-1')
  await flushPromises()
  await wrapper.find('.wr-history-button').trigger('click')
  await flushPromises()
  return wrapper
}

async function applyFirstHistory(wrapper: ReturnType<typeof mount>) {
  const button = wrapper.findAllComponents({ name: 'ElButton' }).find(item => item.text() === '引用')
  if (!button) throw new Error('找不到历史引用按钮')
  button.vm.$emit('click', new MouseEvent('click'))
  await flushPromises()
}

async function render(attachTo?: HTMLElement) {
  const wrapper = mount(WageSchemeFormView, {
    attachTo,
    global: {
      plugins: [ElementPlus],
      stubs: {
        WorkshopConfigManager: {
          props: ['kind', 'initialWorkshop', 'initialCraft', 'initialSchemeName', 'selectableSchemeNames'],
          emits: ['saved', 'select-scheme', 'schemes-changed'],
          template: `
            <div data-testid="operation-manager-stub" :data-initial-workshop="initialWorkshop" :data-initial-craft="initialCraft" :data-initial-scheme="initialSchemeName">
              <button v-for="name in selectableSchemeNames" :key="name" data-testid="stub-select-scheme" @click="$emit('select-scheme', name)">{{ name }}</button>
              <button data-testid="stub-schemes-changed" @click="$emit('schemes-changed')">刷新方案</button>
              <button data-testid="stub-operation-saved" @click="$emit('saved')">保存工序</button>
            </div>
          `,
        },
      },
    },
  })
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

async function pickOperationScheme(wrapper: ReturnType<typeof mount>, name = '标准工序品名') {
  await wrapper.get('[data-testid="choose-operation-scheme"]').trigger('click')
  await flushPromises()
  const button = [...document.body.querySelectorAll<HTMLButtonElement>('[data-testid="stub-select-scheme"]')]
    .find(item => item.textContent?.trim() === name)
  if (!button) throw new Error(`找不到可选方案：${name}`)
  button.click()
  await flushPromises()
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
  it('向下键聚焦下一行同列的申报工价输入框', async () => {
    const wrapper = await render(document.body)
    wrapper.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'workshop-1')
    await flushPromises()
    await pickOperationScheme(wrapper)
    await wrapper.get('.wr-add-line-button').trigger('click')
    const prices = wrapper.findAll('.wr-wage-line-table .el-table__row')
      .map(row => row.get<HTMLInputElement>('input[inputmode="decimal"]'))
    expect(prices).toHaveLength(2)
    prices[0]!.element.focus()
    await prices[0]!.trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement).toBe(prices[1]!.element)
  })

  it('管理工序在添加明细左侧，选择车间和工艺后才可打开', async () => {
    const wrapper = await render()
    const warning = vi.spyOn(ElMessage, 'warning')
    const manageOperations = wrapper.get('[data-testid="add-operation-button"]')
    const addLine = wrapper.get('.wr-wage-lines-heading .wr-add-line-button')

    expect(manageOperations.text()).toBe('管理工序')
    expect(manageOperations.element.nextElementSibling).toBe(addLine.element)
    await manageOperations.trigger('click')

    expect(warning).toHaveBeenCalledWith('请先选择车间和工艺。')
    expect(wrapper.find('[data-testid="stub-operation-saved"]').exists()).toBe(false)
  })

  it('管理工序使用当前范围并刷新上下文但保留已有明细', async () => {
    const wrapper = await render()
    wrapper.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'workshop-1')
    await nextTick()
    selectByTestId(wrapper, 'wage-craft-select').vm.$emit('update:modelValue', 'craft-1')
    await nextTick()
    await wrapper.find('.wr-card--wide .el-button--primary').trigger('click')
    await nextTick()
    await wrapper.find('[data-testid="add-operation-button"]').trigger('click')
    await nextTick()

    const manager = document.body.querySelector<HTMLElement>('[data-testid="operation-manager-stub"]')
    expect(manager).not.toBeNull()
    expect(manager?.closest('[role="dialog"]')?.textContent).toContain('工序信息管理')
    expect(manager?.closest('[role="dialog"]')?.classList.contains('is-maximized')).toBe(true)
    expect(manager?.dataset.initialWorkshop).toBe('workshop-1')
    expect(manager?.dataset.initialCraft).toBe('craft-1')
    expect(manager?.dataset.initialScheme).toBe('')

    document.body.querySelector<HTMLButtonElement>('[data-testid="stub-operation-saved"]')?.click()
    await flushPromises()
    expect(api.context).toHaveBeenCalledTimes(2)
    expect(document.body.querySelector('[data-testid="operation-manager-stub"]')).toBeNull()
    expect(wrapper.findAll('.wr-wage-line-table .el-table__row')).toHaveLength(1)
  })

  it('卡片选用回填工价表单，重新打开定位已选方案', async () => {
    const wrapper = await render()
    wrapper.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'workshop-1')
    await flushPromises()
    await pickOperationScheme(wrapper)
    expect(wrapper.get('[data-testid="choose-operation-scheme"]').text().trim()).toBe('标准工序品名')
    expect(wrapper.find('[data-testid="choose-metal-operations"]').exists()).toBe(false)
    expect(document.body.querySelector('[data-testid="operation-manager-stub"]')).toBeNull()
    await wrapper.get('[data-testid="add-operation-button"]').trigger('click')
    await nextTick()

    const manager = document.body.querySelector<HTMLElement>('[data-testid="operation-manager-stub"]')
    expect(manager?.dataset.initialScheme).toBe('标准工序品名')

    const refreshed = reportingContext(['product-a'])
    refreshed.operations.push({ ...refreshed.operations[0]!, id: 'operation-copied', product_name: '复制的方案' })
    api.context.mockResolvedValueOnce(refreshed)
    document.body.querySelector<HTMLButtonElement>('[data-testid="stub-schemes-changed"]')?.click()
    await flushPromises()
    const options = [...document.body.querySelectorAll('[data-testid="stub-select-scheme"]')].map(item => item.textContent?.trim())
    expect(options).toContain('复制的方案')
    expect(document.body.querySelector('[data-testid="operation-manager-stub"]')).not.toBeNull()
  })

  it('排产产品选项显示产品编码', async () => {
    const wrapper = await render()
    const option = productSelect(wrapper).findAllComponents({ name: 'ElOption' })[0]!
    expect(option.props('label')).toBe('TASK-product-a · 产品-product-a（CODE-product-a）')
  })

  it('选择车间前不查询历史，历史请求及列表只保留当前车间', async () => {
    const first = await render()
    await first.find('.wr-history-button').trigger('click')
    expect(api.history).not.toHaveBeenCalled()
    const source = historyScheme()
    api.history.mockResolvedValue({ data: [source, { ...source, id: 'other', workshop: { id: 'workshop-other', name: '其他车间' } }] })
    const wrapper = await openMetalHistory()
    expect(api.history).toHaveBeenCalledWith({ workshop_id: 'workshop-1', page: 1, page_size: 100 })
    const table = wrapper.findAllComponents({ name: 'ElTable' }).find(item => item.props('height') === '540')!
    expect(table.props('data')).toEqual([source])
  })

  it('跨产品引用时按唯一完整名称对应当前 BOM，并提交当前部件与历史工价', async () => {
    api.history.mockResolvedValue({ data: [historyScheme()] })
    api.create.mockResolvedValue({ data: { id: 'scheme-new' }, etag: '"1"' })
    api.submit.mockResolvedValue({ data: { id: 'scheme-new' }, etag: '"2"' })
    const wrapper = await openMetalHistory()
    await applyFirstHistory(wrapper)
    expect(selectByTestId(wrapper, 'metal-bom-display-select').props('modelValue')).toBe('bom-line-1')
    expect(wrapper.text()).toContain('200')
    await wrapper.findAll('.wr-form-actions button').at(-1)!.trigger('click')
    await flushPromises()
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({
      history_source_scheme_id: 'history-1',
      lines: [expect.objectContaining({ bom_line_id: 'bom-line-1', display_name: '前脚管-铁-20*1.0*500', declared_price: '1.25', production_description: '历史制作说明' })],
    }))
  })

  it('同部件编号优先匹配，并使用当前 BOM 已更新的名称', async () => {
    const source = historyScheme()
    source.lines[0]!.bom_component_identity = 'component-1'
    source.lines[0]!.display_name = '旧名称'
    api.history.mockResolvedValue({ data: [source] })
    const wrapper = await openMetalHistory()
    await applyFirstHistory(wrapper)
    expect(selectByTestId(wrapper, 'metal-bom-display-select').props('modelValue')).toBe('bom-line-1')
    expect(selectByTestId(wrapper, 'metal-bom-display-select').text()).toContain('前脚管-铁-20*1.0*500')
  })

  it('历史数据用生产任务单号开头，展示产品标识、创建时间、工价和启用工序数', async () => {
    const source = historyScheme()
    const line = source.lines[0]!
    source.lines.push({ ...line, display_name: '同工序的另一个部件' }, { ...line, operation_id: 'operation-disabled', status: 'INACTIVE' })
    source.declared_total = '2.5000'
    api.history.mockResolvedValue({ data: [source] })
    await openMetalHistory()

    const dialog = document.body.querySelector('[role="dialog"][aria-label="引用历史批准工价"]')
    expect(dialog).not.toBeNull()
    const headers = [...dialog!.querySelectorAll('.el-table__header th .cell')].map(cell => cell.textContent?.trim())
    expect(headers).toEqual(['生产任务单号', '产品', '产品编码', '货号', '规格', '创建时间', '工价合计', '工序数', '操作'])
    const cells = [...dialog!.querySelectorAll('.el-table__row td .cell')].map(cell => cell.textContent?.trim())
    expect(cells).toEqual(['TASK-HISTORY', '历史产品', 'ERP-001', 'ITEM-001', '60×40cm', '2026-11-04 09:23', '¥2.5', '1 道', '引用'])
  })

  it.each(['duplicate', 'different-spec'])('BOM 匹配不唯一或规格不同时不自动套用：%s', async kind => {
    const context = metalReportingContext(['product-a'])
    if (kind === 'duplicate') context.bom_items.push({ ...context.bom_items[0]!, id: 'duplicate', component_identity: 'duplicate' })
    else context.bom_items[0]!.label = '前脚管-铁-20*1.0*600'
    api.history.mockResolvedValue({ data: [historyScheme()] })
    const warning = vi.spyOn(ElMessage, 'warning')
    const wrapper = await openMetalHistory(context)
    await applyFirstHistory(wrapper)
    const select = selectByTestId(wrapper, 'metal-bom-display-select')
    expect(select.props('modelValue')).toBeNull()
    expect(select.props('placeholder')).toContain('未匹配：前脚管-铁-20*1.0*500')
    expect(warning).toHaveBeenCalledWith(expect.stringContaining('1 条名称 / 部位未能唯一对应'))
    await wrapper.findAll('.wr-form-actions button').at(-1)!.trigger('click')
    await flushPromises()
    expect(api.create).not.toHaveBeenCalled()
  })

  it('切换车间后丢弃旧车间的迟到历史响应', async () => {
    let resolve!: (value: unknown) => void
    api.history.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const wrapper = await openMetalHistory()
    wrapper.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'other-workshop')
    await flushPromises()
    resolve({ data: [historyScheme()] })
    await flushPromises()
    const dialog = wrapper.findComponent({ name: 'AppWindowDialog' })
    expect(dialog.props('modelValue')).toBe(false)
    expect(wrapper.findAllComponents({ name: 'ElButton' }).some(item => item.text() === '引用')).toBe(false)
  })

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
    expect(wrapper.find('.wr-form-actions').findAll('button').map(button => button.text())).toEqual(['返回', '提交'])
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
    expect(wrapper.find('[data-testid="choose-operation-scheme"]').exists()).toBe(false)

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
      .toEqual(['前脚管-铁-20*1.0*500-500mm'])
    expect(bomSelect.props('placeholder')).toBe('选择部件、材质和规格')
  })

  it('金工按各根管材的工序标签追加明细，保留原有部位和工价', async () => {
    const context = metalReportingContext(['product-a'])
    const frontPipe = context.bom_items[0]!
    context.bom_items.push(
      { ...frontPipe, id: 'bom-line-2', component_identity: 'component-2', label: '后脚管-铁-22*1.0*600', display_label: '后脚管-铁-22*1.0*600-600mm' },
      { ...frontPipe, id: 'bom-line-3', component_identity: 'component-3', label: '横管-铁-20*1.0*300', display_label: '横管-铁-20*1.0*300-300mm' },
    )
    context.workshops.push({ id: 'another-workshop', name: '装配车间' })
    context.crafts.push({ id: 'another-craft', workshop_id: 'another-workshop', name: '装配', plan_category: 'ASSEMBLY' })
    context.operations.push({ ...context.operations[0]!, id: 'another-operation', craft_id: 'another-craft', name: '包装' })
    api.context.mockResolvedValue(context)
    const wrapper = await render(document.body)
    productSelect(wrapper).vm.$emit('update:modelValue', 'product-a')
    await flushPromises()
    wrapper.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'workshop-1')
    await flushPromises()

    await wrapper.get('.wr-add-line-button').trigger('click')
    selectByTestId(wrapper, 'metal-bom-display-select').vm.$emit('update:modelValue', 'bom-line-3')
    selectByTestId(wrapper, 'metal-bom-display-select').vm.$emit('change', 'bom-line-3')
    selectByTestId(wrapper, 'wage-operation-select').vm.$emit('update:modelValue', 'operation-1')
    declaredPriceInput(wrapper).vm.$emit('update:modelValue', '0.75')
    await nextTick()
    const entry = wrapper.get('[data-testid="choose-metal-operations"]')
    expect(entry.element.previousElementSibling).toBe(wrapper.get('.wr-add-line-button').element)
    const operationIds = () => wrapper.findAllComponents(ElSelect)
      .filter(select => select.attributes('data-testid') === 'wage-operation-select')
      .map(select => select.props('modelValue'))
    const dialog = () => new DOMWrapper(document.body).get('[role="dialog"]')
    const pipeGroups = () => dialog().findAll('.wr-metal-operation-pipe')
    const tagsForPipe = (index: number) => pipeGroups()[index]!.findAll('.wr-metal-operation-tag')

    await entry.trigger('click')
    await flushPromises()
    expect(pipeGroups().map(group => group.get('h3').text())).toEqual(context.bom_items.map(pipe => pipe.display_label))
    expect(tagsForPipe(0).map(tag => tag.text())).toEqual(['切管', '弯管'])
    expect(tagsForPipe(2)[0]!.attributes('disabled')).toBeDefined()
    const generate = dialog().findAll('button').find(button => button.text() === '生成明细')!
    expect(generate.attributes('disabled')).toBeDefined()
    await tagsForPipe(0)[0]!.trigger('click')
    expect(tagsForPipe(0)[0]!.attributes('aria-pressed')).toBe('true')
    expect(tagsForPipe(1)[0]!.attributes('aria-pressed')).toBe('false')
    await dialog().findAll('button').find(button => button.text() === '取消')!.trigger('click')
    await flushPromises()
    expect(operationIds()).toEqual(['operation-1'])

    await entry.trigger('click')
    await flushPromises()
    expect(tagsForPipe(0).map(tag => tag.attributes('aria-pressed'))).toEqual(['false', 'false'])
    await tagsForPipe(0)[0]!.trigger('click')
    await tagsForPipe(0)[1]!.trigger('click')
    await tagsForPipe(1)[0]!.trigger('click')
    await dialog().findAll('button').find(button => button.text() === '生成明细')!.trigger('click')
    await flushPromises()
    expect(operationIds()).toEqual(['operation-1', 'operation-1', 'operation-2', 'operation-1'])
    expect(wrapper.findAllComponents(ElSelect).filter(select => select.attributes('data-testid') === 'metal-bom-display-select')
      .map(select => select.props('modelValue'))).toEqual(['bom-line-3', 'bom-line-1', 'bom-line-1', 'bom-line-2'])
    const table = wrapper.get('.wr-wage-line-table')
    const priceColumn = table.findAll('thead th').findIndex(cell => cell.text() === '申报工价')
    const declaredPrices = table.findAll('tbody tr').map(row => row.findAll('td')[priceColumn]!.get<HTMLInputElement>('input').element.value)
    expect(declaredPrices).toEqual(['0.75', '', '', ''])
    expect(api.create).not.toHaveBeenCalled()
    expect(api.submit).not.toHaveBeenCalled()
  })

  it.each([
    ['CUTTING', 'cut-piece-1', '椅面裁片-A款', '100'],
    ['SEWING', 'sewn-part-1', '椅面部位-A款', '200'],
  ] as const)('%s 工价只使用对应 BOM 对象并按 BOM 配比计算', async (category, expectedId, expectedLabel, expectedQuantity) => {
    api.context.mockResolvedValue(componentReportingContext(category))
    const wrapper = await render()
    productSelect(wrapper).vm.$emit('update:modelValue', 'product-a')
    await flushPromises()
    wrapper.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'workshop-1')
    await flushPromises()
    selectByTestId(wrapper, 'wage-craft-select').vm.$emit('update:modelValue', 'craft-1')
    await flushPromises()
    await pickOperationScheme(wrapper)

    const bomSelect = selectByTestId(wrapper, category === 'CUTTING' ? 'cutting-group-select' : 'bom-display-select')
    expect(bomSelect.findAllComponents({ name: 'ElOption' }).map(option => [option.props('value'), option.props('label')]))
      .toEqual([[expectedId, expectedLabel]])
    bomSelect.vm.$emit('update:modelValue', category === 'CUTTING' ? [expectedId] : expectedId)
    bomSelect.vm.$emit('change', expectedId)
    await nextTick()
    expect(wrapper.text()).toContain(expectedQuantity)
    expect(wrapper.get('.wr-fixed-counting-mode').text()).toBe('按套')
    if (category === 'SEWING') expect(wrapper.findAllComponents({ name: 'ElSelect' }).some(item => item.text().includes('按片'))).toBe(false)
  })

  it('裁片多选折叠多余标签，保留三个已选裁片', async () => {
    const context = componentReportingContext('CUTTING')
    const piece = context.bom_items[0]!
    context.bom_items.push(
      { ...piece, id: 'cut-piece-2', component_identity: 'cut-piece-identity-2', label: '侧片-A款' },
      { ...piece, id: 'cut-piece-3', component_identity: 'cut-piece-identity-3', label: '底片-A款' },
    )
    api.context.mockResolvedValue(context)
    const wrapper = await render()
    productSelect(wrapper).vm.$emit('update:modelValue', 'product-a')
    await flushPromises()
    wrapper.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'workshop-1')
    await flushPromises()
    await pickOperationScheme(wrapper)

    const select = selectByTestId(wrapper, 'cutting-group-select')
    const selectedIds = ['cut-piece-1', 'cut-piece-2', 'cut-piece-3']
    select.vm.$emit('update:modelValue', selectedIds)
    await flushPromises()
    expect(select.props('modelValue')).toEqual(selectedIds)
    expect(select.props('collapseTagsTooltip')).toBe(true)
    expect(select.findAll('.el-select__selection .el-select__tags-text').map(tag => tag.text()))
      .toEqual(['椅面裁片-A款', '+ 2'])
  })

  it('新建时工价方案在历史数据右侧，并按当前车间与工艺过滤工序', async () => {
    const context = reportingContext(['product-a'])
    context.operations.push({
      id: 'operation-other-product', operation_number: 'GX-009', product_name: '其他工序品名',
      name: '其他工序', craft_id: 'craft-1', unit_id: 'unit-1', unit_name: '件',
    })
    api.context.mockResolvedValue(context)
    const wrapper = await render()

    wrapper.findAllComponents(ElSelect)[1]!.vm.$emit('update:modelValue', 'workshop-1')
    await flushPromises()
    const toolbar = wrapper.get('.wr-card--wide .wr-card-title')
    const picker = toolbar.get('[data-testid="choose-operation-scheme"]')
    expect(picker.element.previousElementSibling).toBe(toolbar.get('.wr-history-button').element)
    expect(picker.text()).toBe('选择方案')
    expect(toolbar.find('[data-testid="operation-product-name-field"]').exists()).toBe(false)
    await pickOperationScheme(wrapper)
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
    expect(wrapper.find('[data-testid="choose-operation-scheme"]').exists()).toBe(false)
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
    await pickOperationScheme(wrapper)

    const operationSelect = selectByTestId(wrapper, 'wage-operation-select')
    operationSelect.vm.$emit('update:modelValue', 'operation-1')
    await nextTick()
    operationSelect.vm.$emit('change', 'operation-1')
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
    await pickOperationScheme(wrapper)

    const operationSelect = selectByTestId(wrapper, 'wage-operation-select')
    operationSelect.vm.$emit('update:modelValue', 'operation-1')
    await nextTick()
    operationSelect.vm.$emit('change', 'operation-1')
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
    await pickOperationScheme(wrapper)

    const operationSelect = selectByTestId(wrapper, 'wage-operation-select')
    operationSelect.vm.$emit('update:modelValue', 'operation-1')
    await nextTick()
    operationSelect.vm.$emit('change', 'operation-1')
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
