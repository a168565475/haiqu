import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ProductionTaskOptions } from '@/types/productionTask'
import AiImportTaskForm from './AiImportTaskForm.vue'
import { applyTaskOptions, extractedText, restoreTaskDraft, taskDraftFromResult, taskPayload, validateTaskDraft } from './AiImportTaskFormData'

const api = vi.hoisted(() => ({ options: vi.fn(), reserve: vi.fn() }))
vi.mock('@/api/productionTasks', () => ({ fetchProductionTaskOptions: api.options, reserveProductionTaskContractNumber: api.reserve }))
const options: ProductionTaskOptions = {
  order_sources: [], delivery_methods: [], statuses: [], boolean_options: [], customers: [],
  salespeople: [{ id: 'seller', employee_code: 'S1', display_name: '张三' }],
  employees: [{ id: 'follower', employee_code: 'F1', display_name: '李四' }],
  currencies: [{ id: 'cny', code: 'CNY', name: '人民币', symbol: '¥' }, { id: 'usd', code: 'USD', name: '美元', symbol: '$' }],
  units: [{ id: 'piece', unit_code: 'PCS', unit_name: '个' }], colors: [],
  products: [{ id: 'master', product_code: 'P1', product_number: '001', item_number: '', product_name: '扶手椅', specification: '60×80', default_unit_id: 'piece' }],
  detail_template: [{ key: 'quality', type: '品质', category: '检查要求' }],
}
const field = (value: unknown, status = 'EXTRACTED') => ({ value, status, source_ids: ['r1'], note: '' })
const result = (): Record<string, unknown> => ({
  task: { task_number: field('HT26149'), order_date: field('2026-11-01'), delivery_date: field('2026-12-01'),
    salesperson: field('张三'), followers: field('李四'), includes_tax: field(false), order_tolerance_percent: field('0'),
    is_repeat_order: field(false), preproduction_sample_required: field(false), delivery_method: field('SINGLE') },
  products: [{ product_key: 'p1', name: field('扶手椅'), specification: field('60×80'), color: field('黑色'), quantity: field('300'), unit: field('个'), currency: field('CNY'), unit_price: field('0'),
    details: [{ template_key: 'quality', is_selected: field(false), description: field('不需要额外检查') }] }],
})
const validDraft = () => { const draft = taskDraftFromResult(result()); applyTaskOptions(draft, result(), options); return draft }
const wrappers: ReturnType<typeof mount>[] = []
async function render(saved: Record<string, unknown> | null = null, source = result()) {
  const wrapper = mount(AiImportTaskForm, { props: { result: source, modelValue: saved }, global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
beforeEach(() => { vi.clearAllMocks(); api.options.mockResolvedValue(options); api.reserve.mockResolvedValue({ contract_number: 'HT20261113001', token: 'reserved-token' }) })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('AI 任务字段映射（单元测试）', () => {
  it('缺失/冲突不伪造日期、数量、价格、人员和布尔值', () => {
    const source = { task: { order_date: field('2026-11-01', 'CONFLICT') }, products: [{ name: field('椅子'), quantity: field('300', 'CONFLICT') }] }
    const draft = taskDraftFromResult(source)
    expect(draft.order_date).toBe(''); expect(draft.includes_tax).toBeNull()
    expect(draft.products[0]?.quantity).toBe(''); expect(draft.products[0]?.unit_price).toBe('')
    expect(draft.products[0]?.product_id).toBeNull(); expect(draft.salesperson_id).toBe('')
    expect(extractedText(field(0))).toBe('0')
  })
  it('明确的零价格和 false 保留；唯一人员/单位/完整产品规格才关联', () => {
    const draft = validDraft()
    expect(draft.products[0]?.unit_price).toBe('0'); expect(draft.includes_tax).toBe(false)
    expect(draft.salesperson_id).toBe('seller'); expect(draft.follower_ids).toEqual(['follower'])
    expect(draft.products[0]?.product_id).toBe('master'); expect(draft.products[0]?.unit_id).toBe('piece')
    expect(draft.products[0]?.details[0]?.is_selected).toBe(false)
    expect(() => validateTaskDraft(draft, options)).not.toThrow()
    const duplicate = { ...options, salespeople: [...options.salespeople, { ...options.salespeople[0]!, id: 'seller2' }] }
    applyTaskOptions(draft, result(), duplicate)
    expect(draft.salesperson_id).toBe('')
  })
  it('外币原价不能直接当人民币单价', () => {
    const source = result(); (source.products as Record<string, unknown>[])[0]!.currency = field('USD')
    const draft = taskDraftFromResult(source); applyTaskOptions(draft, source, options)
    expect(draft.products[0]?.unit_price).toBe('0')
    expect(draft.products[0]?.currency_id).toBe('usd'); expect(draft.products[0]?.exchange_rate).toBe('')
    expect(taskPayload(draft, options).products[0]?.exchange_rate).toBeNull()
  })
  it('已核对值覆盖原识别，重载不重置；生成载荷不修改原编辑值', () => {
    const original = validDraft(); original.products[0]!.quantity = '450'; original.includes_tax = true; original.tax_rate = 5
    const draft = restoreTaskDraft(result(), original as unknown as Record<string, unknown>)
    expect(draft.products[0]?.quantity).toBe('450'); expect(draft.tax_rate).toBe(5)
    const payload = taskPayload(draft, options)
    expect(payload.products[0]?.exchange_rate).toBe('1.00000000'); expect(payload.freight_amount).toBeNull()
    expect(draft.freight_amount).toBe('')
  })
  it('无效日期、数量和金额阻止建单', () => {
    const draft = validDraft(); draft.order_date = '2026-02-30'
    expect(() => validateTaskDraft(draft, options)).toThrow('有效下单日期')
    draft.order_date = '2026-11-01'; draft.products[0]!.quantity = '0'
    expect(() => validateTaskDraft(draft, options)).toThrow('大于 0')
    draft.products[0]!.quantity = '300'; draft.products[0]!.unit_price = '-1'
    expect(() => validateTaskDraft(draft, options)).toThrow('非负金额')
  })
  it('未知价税、费用和币种保留为空，不伪造零和人民币', () => {
    const source = result(); const task = source.task as Record<string, unknown>; const product = (source.products as Record<string, unknown>[])[0]!
    task.includes_tax = field(null, 'MISSING'); product.currency = field(null, 'MISSING'); product.unit_price = field(null, 'MISSING')
    const draft = taskDraftFromResult(source); applyTaskOptions(draft, source, options)
    const payload = taskPayload(draft, options)
    expect(payload.includes_tax).toBeNull(); expect(payload.freight_amount).toBeNull(); expect(payload.other_fee_amount).toBeNull()
    expect(payload.currency_id).toBeNull(); expect(payload.products[0]).toMatchObject({ currency_id: null, unit_price: null, exchange_rate: null })
  })
  it('仅接收明确默认结果，旧MISSING和未读不自行套默认', () => {
    const source = result(); const task = source.task as Record<string, unknown>
    task.order_tolerance_percent = { ...field(0, 'DEFAULTED'), note: 'D16 原表未填写' }
    task.is_repeat_order = field(false, 'MISSING'); task.preproduction_sample_required = field(false, 'UNREADABLE')
    const draft = taskDraftFromResult(source)
    expect(draft.order_tolerance_percent).toBe('0'); expect(draft.is_repeat_order).toBeNull(); expect(draft.preproduction_sample_required).toBeNull()
    expect(extractedText(field('无需产前样', 'UNREADABLE'))).toBe('')
  })
  it('生产明细保留明确是、明确否、待确认和原说明，不能按非空文字勾选', () => {
    const source = result(); const product = (source.products as Record<string, unknown>[])[0]!
    product.details = [
      { template_key: 'quality', is_selected: field(true), description: field('不得有油污') },
      { template_key: 'print', is_selected: field(false), description: field('不需要丝印') },
      { template_key: 'bag', is_selected: { ...field(null, 'UNREADABLE'), note: '勾选无法读取' }, description: field('按样品') },
    ]
    const expanded = { ...options, detail_template: [...options.detail_template, { key: 'print', type: '丝印', category: '' }, { key: 'bag', type: '外袋', category: '' }, { key: 'tag', type: '吊卡', category: '' }] }
    const draft = taskDraftFromResult(source); applyTaskOptions(draft, source, expanded)
    expect(draft.products[0]?.details.map(row => row.is_selected)).toEqual([true, false, null, null])
    expect(draft.products[0]?.details[1]?.description).toBe('不需要丝印')
    expect(draft.products[0]?.details[2]?.source_note).toBe('勾选无法读取')
    expect(taskPayload(draft, expanded).products[0]?.details[2]?.is_selected).toBeNull()
  })
  it('客户货号按item_number匹配，不能借同号ERP编码猜配', () => {
    const source = result(); const product = (source.products as Record<string, unknown>[])[0]!
    product.item_number = field('P1')
    const draft = taskDraftFromResult(source); applyTaskOptions(draft, source, options)
    expect(draft.products[0]?.source_item_number).toBe('P1'); expect(draft.products[0]?.product_id).toBeNull()
    applyTaskOptions(draft, source, { ...options, products: [{ ...options.products[0]!, item_number: 'P1' }] })
    expect(draft.products[0]?.product_id).toBe('master')
  })
  it('色卡色号与颜色分别保留，主档颜色须同时匹配已有依据', () => {
    const source = result(); const product = (source.products as Record<string, unknown>[])[0]!
    product.color_card = field('2026卡'); product.color_code = field('23#')
    const draft = taskDraftFromResult(source)
    applyTaskOptions(draft, source, { ...options, colors: [{ id: 'wrong', color_card: '其他卡', color_code: '23#', color_name: '黑色' }, { id: 'right', color_card: '2026卡', color_code: '23#', color_name: '黑色' }] })
    expect(draft.products[0]).toMatchObject({ source_color_card: '2026卡', color_code: '23#', customer_color: '黑色', product_color_id: 'right' })
  })
  it('分批交货预填并保留产品颜色包装箱数关系，恢复保留人工修改', () => {
    const source = result(); const task = source.task as Record<string, unknown>
    task.delivery_method = field('SPLIT')
    task.delivery_batches = [{ batch_key: 'b1', product_key: 'p1', quantity: field('300'), carton_quantity: field('150'), color: field('黑色'),
      packaging_method: field('2件/箱'), delivery_date: field('2026-12-01'), notes: field('按此批次发货') }]
    const draft = taskDraftFromResult(source); applyTaskOptions(draft, source, options)
    expect(draft.delivery_batches[0]).toMatchObject({ product_key: 'p1', quantity: '300', carton_quantity: '150', packaging_method: '2件/箱' })
    draft.delivery_batches[0]!.note = '人工核对包装'
    const restored = restoreTaskDraft(source, draft as unknown as Record<string, unknown>)
    const payload = taskPayload(restored, options)
    expect(payload.delivery_batches[0]?.note).toContain('产品：扶手椅（p1）；颜色：黑色；包装：2件/箱；箱数：150；人工核对包装')
    expect(restored.delivery_batches[0]?.note).toBe('人工核对包装')
  })
  it('带坐宽背高名称的成品规格原样预填，不拼成普通长宽高', () => {
    const source = result(); (source.products as Record<string, unknown>[])[0]!.specification = field('长52、坐宽52、背高87 cm')
    expect(taskDraftFromResult(source).products[0]?.customer_specification).toBe('长52、坐宽52、背高87 cm')
  })
})

describe('AI 任务表单（模拟 API 的组件测试）', () => {
  it('展示表单及产品内容，加载选项不预留合同号', async () => {
    const wrapper = await render()
    expect(wrapper.text()).toContain('生产任务单'); expect(wrapper.text()).toContain('待补与未对应内容')
    expect(wrapper.find('button[aria-label^="按原表币种填写"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('原表识别内容')
    expect(api.options).toHaveBeenCalledWith({ timeout: 30_000 }); expect(api.reserve).not.toHaveBeenCalled()
    const payload = await wrapper.vm.buildPayload()
    expect(payload.contract_number_token).toBe('reserved-token'); expect(api.reserve).toHaveBeenCalledWith('2026-11-01')
    await wrapper.vm.buildPayload(); expect(api.reserve).toHaveBeenCalledTimes(1)
  })
  it('不完整结果在编号预留之前被拦截', async () => {
    const wrapper = await render(null, { task: {}, products: [] })
    await expect(wrapper.vm.buildPayload()).rejects.toThrow('请补齐')
    expect(api.reserve).not.toHaveBeenCalled()
  })
  it('折叠后仍可编辑补充资料和完整生产明细，核对值进入原有载荷', async () => {
    const wrapper = await render()
    expect(wrapper.get('[aria-label="任务信息"]').findAll('.field-grid > label')).toHaveLength(12)
    expect((wrapper.get('[aria-label="更多任务信息"]').element as HTMLElement).style.display).toBe('none')
    expect((wrapper.get('[aria-label="全部生产明细"]').element as HTMLElement).style.display).toBe('none')
    expect((wrapper.get('[aria-label="扶手椅补充资料"]').element as HTMLElement).style.display).toBe('none')

    await wrapper.findAll('button').find(item => item.text().startsWith('更多任务信息'))!.trigger('click')
    expect((wrapper.get('[aria-label="更多任务信息"]').element as HTMLElement).style.display).toBe('')
    await wrapper.get('input[aria-label="生产批号"]').setValue('B-001')
    await wrapper.get('input[aria-label="运费"]').setValue('25')
    await wrapper.get('button[aria-label="编辑扶手椅资料"]').trigger('click')
    expect((wrapper.get('[aria-label="扶手椅补充资料"]').element as HTMLElement).style.display).toBe('')
    await wrapper.get('input[aria-label="产品材质"]').setValue('钢')
    await wrapper.findAll('button').find(item => item.text().startsWith('生产明细'))!.trigger('click')
    expect((wrapper.get('[aria-label="全部生产明细"]').element as HTMLElement).style.display).toBe('')
    await wrapper.get('textarea[aria-label="产品生产要求"]').setValue('按确认样生产')
    await wrapper.get('textarea[aria-label="完整包装要求"]').setValue('2 件/箱')
    await wrapper.get('.el-collapse-item__header').trigger('click')
    await wrapper.get('input[aria-label="生产明细描述"]').setValue('核对完成')
    const payload = await wrapper.vm.buildPayload()
    expect(payload).toMatchObject({ production_batch_number: 'B-001', freight_amount: '25' })
    expect((payload.products as Record<string, unknown>[])[0]).toMatchObject({ material: '钢', special_requirements: '按确认样生产', packaging_method: '2 件/箱' })
    expect(((payload.products as Record<string, unknown>[])[0]!.details as Record<string, unknown>[])[0]?.description).toBe('核对完成')
  })
  it('字段来源改为可聚焦提示，并在集中核对区保留原说明', async () => {
    const source = result()
    const task = source.task as Record<string, unknown>
    task.order_date = { ...field('2026-11-01', 'CONFLICT'), note: '日期冲突' }
    task.order_tolerance_percent = { ...field('0', 'DEFAULTED'), note: 'D16 原表未填写' }
    const wrapper = await render(null, source)
    expect(wrapper.findAll('[aria-label="任务信息"] small')).toHaveLength(0)
    expect(wrapper.get('button[aria-label="下单日期：原表有冲突：2026-11-01"]').attributes('type')).toBe('button')
    expect(wrapper.find('button[aria-label="订单误差（%）：D16 原表未填写"]').exists()).toBe(true)
    expect(wrapper.get('.pending-content').text()).toContain('下单日期：待补充')
    expect(wrapper.get('.pending-content').text()).toContain('D16 原表未填写')
    expect(api.reserve).not.toHaveBeenCalled()
  })
  it('创建中锁定用户编辑后，父流程仍能完成载荷校验', async () => {
    const wrapper = await render()
    await wrapper.setProps({ disabled: true })
    expect(wrapper.get('input[aria-label="生产任务单号"]').attributes('disabled')).toBeDefined()
    const payload = await wrapper.vm.buildPayload()
    expect(payload.task_number).toBe('HT26149')
    expect(api.reserve).toHaveBeenCalledTimes(1)
  })
  it('刷新识别来源也保留已有核对稿', async () => {
    const draft = validDraft(); draft.products[0]!.quantity = '450'
    const wrapper = await render(draft as unknown as Record<string, unknown>)
    await wrapper.setProps({ result: { task: {}, products: [] } })
    const payload = await wrapper.vm.buildPayload()
    expect((payload.products as Array<{ quantity: string }>)[0]?.quantity).toBe('450')
    expect(payload.order_date).toBe('2026-11-01')
  })
  it('基础资料失败明确阻止建单并保留输入', async () => {
    api.options.mockRejectedValue(new Error('连接失败'))
    const wrapper = await render()
    expect(wrapper.text()).toContain('基础资料加载失败')
    await expect(wrapper.vm.buildPayload()).rejects.toThrow('加载基础资料')
    expect(api.reserve).not.toHaveBeenCalled()
  })
  it('基础资料超时显示中文；重试不覆盖等待期间的人工修改', async () => {
    api.options.mockRejectedValueOnce(new AxiosError('timeout of 5000ms exceeded', 'ECONNABORTED')).mockResolvedValue(options)
    const wrapper = await render()
    expect(wrapper.text()).toContain('基础资料加载超时')
    expect(wrapper.text()).not.toContain('timeout of')
    await wrapper.get('input[aria-label="生产任务单号"]').setValue('HT26149-9')
    await wrapper.get('input[aria-label="产品数量"]').setValue('450')
    const retry = wrapper.findAll('button').find(item => item.text() === '重新加载')!
    await retry.trigger('click'); await flushPromises()
    expect(api.options).toHaveBeenCalledTimes(2)
    expect((wrapper.get('input[aria-label="生产任务单号"]').element as HTMLInputElement).value).toBe('HT26149-9')
    expect((wrapper.get('input[aria-label="产品数量"]').element as HTMLInputElement).value).toBe('450')
    expect(wrapper.text()).not.toContain('基础资料加载超时')
    expect(api.reserve).not.toHaveBeenCalled()
  })
})
