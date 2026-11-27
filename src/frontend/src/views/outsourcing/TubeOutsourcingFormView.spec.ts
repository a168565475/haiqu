import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElSelect } from 'element-plus'
import { AxiosError, CanceledError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/tubeOutsourcing'
import * as printApi from '@/api/cutPiecePrinting'
import type { TubeOptions, TubeOrderInput, TubePendingOrderInput, TubeOrderResult, TubeSourceContext, TubeSourceRow } from '@/types/tubeOutsourcing'
import TubeOutsourcingFormView from './TubeOutsourcingFormView.vue'
import ProductImage from '@/components/products/ProductImage.vue'

const routing = vi.hoisted(() => ({ push: vi.fn(), name: '', query: { schedule_product_id: 'schedule-product' } as Record<string, string> }))
vi.mock('vue-router', () => ({ useRoute: () => routing, useRouter: () => routing }))
vi.mock('@/stores/auth', async () => {
  const { reactive } = await import('vue')
  const state = reactive({ user: { id: 7, is_superuser: true }, initialized: true, identityReady: true, identityGeneration: 1, identityRequestGeneration: 1, hasPermission: () => true })
  return { useAuthStore: () => state }
})
const auth = useAuthStore()
function resetIdentity() { Object.assign(auth, { user: { id: 7, is_superuser: true }, initialized: true, identityReady: true, identityGeneration: 1, identityRequestGeneration: 1 }) }
vi.mock('@/api/tubeOutsourcing', () => ({ fetchTubeOptions: vi.fn(), fetchTubeSource: vi.fn(), createTubeOrder: vi.fn(), findTubeOrder: vi.fn() }))
vi.mock('element-plus', async original => ({ ...await original<typeof import('element-plus')>(), ElMessage: { warning: vi.fn(), success: vi.fn() } }))

const key = 'tube-outsourcing-pending:v1:7'
const planHeaderFields = ['生产任务单', '产品', '计划发出日期', '预计回货日期']
const productDisplay = { specification: '47*55*79 红色 PE', specification_display: '47*55*79', material: 'PE', image_file_id: 'product-image', image_url: '/api/v1/tube-outsourcing-orders/product-images/schedule-product/product-image/' }
const options: TubeOptions = {
  tasks: [{ id: 'task', task_number: 'SC-test', order_number: 'DD-test', products: [{ id: 'product', schedule_product_id: 'schedule-product', schedule_number: 'PC-test', product_number: 'CP-test', item_number: 'HT-test', product_name: '测试椅', quantity: '1000', unit: '把', color: '黑色', ...productDisplay }] }],
  factories: [{ id: 'factory', name: '测试加工厂' }, { id: 'hardware-factory', name: '五金加工厂' }],
  zones: [
    { id: 'zone', name: 'A区', warehouse_id: 'warehouse', warehouse_name: '材料仓', warehouse_type: 'MATERIAL' },
    { id: 'zone-other', name: 'B区', warehouse_id: 'other', warehouse_name: '另一材料仓', warehouse_type: 'MATERIAL' },
    { id: 'semi-empty', name: '无库存区', warehouse_id: 'semi-warehouse', warehouse_name: '半成品仓', warehouse_type: 'SEMI_FINISHED' },
    { id: 'semi-ready', name: '有库存区', warehouse_id: 'semi-warehouse-2', warehouse_name: '半成品备用仓', warehouse_type: 'SEMI_FINISHED' },
  ],
  source_kinds: [{ value: 'RAW_PIPE', label: '公共原管材' }, { value: 'PUBLIC_SEMI', label: '公共未喷塑半成品' }, { value: 'METAL', label: '厂内已加工件' }],
}
const row: TubeSourceRow = { component_identity: 'front', bom_line_id: 'bom-front', part_name: '前腿管', material: 'Q195', specification: 'Φ22', thickness: '0.8', cutting_length_mm: '650', raw_color: '原料本色', spray_color: '黑色', unit_area_sqm: '0.1250', order_required: '2000', stock_quantity: '200', stock_unit: '根', max_quantity: '1200', pieces_per_bar: '6', raw_bar_length_m: '3.95', blockers: [], purchase_reference: { quantity: '3000', unit: '支', purchased_quantity: '500', purchase_unit: '根', conversion_note: '采购实际入库500根 × BOM每根6支 = 3000支。' } }
const context: TubeSourceContext = { source_revision: 'revision-1', source_kind: 'RAW_PIPE', schedule_product_id: 'schedule-product', product_line_id: 'product', task_id: 'task', task_number: 'SC-test', order_number: 'DD-test', schedule_number: 'PC-test', product_number: 'CP-test', item_number: 'HT-test', product_name: '测试椅', quantity: '1000', unit: '把', color: '黑色', ...productDisplay, craft_name: '喷塑', zone_id: 'zone', ready: true, blockers: [], tasks: options.tasks, factories: options.factories, zones: options.zones, rows: [row] }
const hardware = { bom_line_id: 'hardware', material_number: 'WJ-test', name: '铁垫片', specification: 'M8', material: '铁', color: '黑色', unit: 'kg', required_quantity: '50', order_remaining: '30', available_stock: '20', max_quantity: '20', blockers: [], zones: [{ zone_id: 'hardware-zone', zone_name: '五金区', warehouse_id: 'hardware-warehouse', warehouse_name: '五金仓', available_quantity: '20' }] }
const result = (payload: TubePendingOrderInput): TubeOrderResult => ({ ...payload, schedule_product_id: payload.schedule_product_id ?? null, id: 'saved-order', order_number: 'WF-real-response', status: 'PENDING_DISPATCH', version: 1, etag: 'saved', created: true, product_line_id: 'product', total_quantity: '600', total_stock_quantity: '100', total_meters: '395.00', total_area_sqm: '75.0000', planned_amount: '11.25' })
const httpError = (status: number) => Object.assign(new AxiosError('接口错误'), { response: { status, data: { error: { message: `状态 ${status}` } } } })
interface ViewModel {
  rows: Array<TubeSourceRow & { quantity: string; factoryId: string; priceUnit: 'PIECE' | 'SQUARE_METER'; unitPrice: string }>; returnDate: string
  dialog: string; pending: TubePendingOrderInput | null; error: string; sourceHint: string; warehouseId: string; zoneId: string
  context: TubeSourceContext | null
  materialRows: Array<typeof hardware & { quantity: string; factoryId: string; zoneId: string }>
  plannedAmount: string | null; totalArea: string | null
  checkDispatch: () => void; save: () => Promise<void>; loadSource: (preserve?: boolean) => Promise<void>
  requestChange: (kind: string, value: string) => void; applyChange: () => Promise<void>
}
async function mountPage(renderInputs = false) {
  const wrapper = shallowMount(TubeOutsourcingFormView, { global: { plugins: [ElementPlus], stubs: renderInputs ? {
    ElInput: false, ComponentSourceMaterials: false,
    AppWindowDialog: { props: ['modelValue'], template: '<section v-if="modelValue"><slot /></section>' },
  } : {} } })
  await flushPromises()
  const vm = wrapper.vm as unknown as ViewModel
  vm.returnDate = '2099-10-14'
  return { wrapper, vm }
}
function fill(vm: ViewModel) { vm.rows[0]!.quantity = '600'; vm.rows[0]!.factoryId = 'factory'; vm.rows[0]!.unitPrice = '0.15' }
afterEach(() => vi.restoreAllMocks())

describe('管材建单与异常恢复', () => {
  beforeEach(() => {
    vi.resetAllMocks(); localStorage.clear(); resetIdentity()
    routing.query = { schedule_product_id: 'schedule-product', source_kind: 'RAW_PIPE' }
    vi.mocked(api.fetchTubeOptions).mockResolvedValue(structuredClone(options))
    vi.mocked(api.fetchTubeSource).mockResolvedValue(structuredClone(context))
    vi.mocked(api.findTubeOrder).mockRejectedValue(httpError(404))
    vi.mocked(api.createTubeOrder).mockImplementation(async payload => result(payload))
  })
  it('普通新建只请求需求计划，不让用户选择材料来源和库区', async () => {
    delete routing.query.source_kind
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), source_kind: 'METAL', zone_id: null })
    const { wrapper } = await mountPage()
    expect(api.fetchTubeSource).toHaveBeenLastCalledWith({ schedule_product_id: 'schedule-product', category: 'tube', is_plan: true })
    for (const name of ['材料来源', '来源仓库', '库区']) expect(wrapper.find(`[aria-label="${name}"]`).exists()).toBe(false)
    expect(wrapper.find('.status').exists()).toBe(false)
    wrapper.unmount()
  })
  it('没有仓库库区仍可加载并保存管材需求，旧链接来源不绑定计划', async () => {
    routing.query.zone_id = 'old-zone'
    vi.mocked(api.fetchTubeOptions).mockResolvedValue({ ...structuredClone(options), zones: [] })
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), source_kind: 'METAL', zone_id: null })
    const { wrapper, vm } = await mountPage()
    fill(vm); await vm.save()
    expect(api.fetchTubeSource).toHaveBeenLastCalledWith({ schedule_product_id: 'schedule-product', category: 'tube', is_plan: true })
    expect(api.createTubeOrder).toHaveBeenCalledWith(expect.objectContaining({ is_plan: true, source_kind: 'METAL', zone_id: null }))
    wrapper.unmount()
  })
  it.each(['uid', 'generation', 'request', 'ready'] as const)('POST在%s边界后迟到成功不清记录、不导航、不提示', async boundary => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    let resolve!: (value: TubeOrderResult) => void
    vi.mocked(api.createTubeOrder).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const submitting = vm.save(); const raw = localStorage.getItem(key)!
    if (boundary === 'uid') auth.user!.id = 8
    else if (boundary === 'generation') auth.identityGeneration += 1
    else if (boundary === 'request') auth.identityRequestGeneration += 1
    else Object.assign(auth, { identityReady: false })
    resolve(result(JSON.parse(raw) as TubePendingOrderInput)); await submitting; await flushPromises()
    expect(localStorage.getItem(key)).toBe(raw); expect(vm.pending).not.toBeNull()
    expect(api.findTubeOrder).not.toHaveBeenCalled(); expect(routing.push).not.toHaveBeenCalled()
    expect(ElMessage.success).not.toHaveBeenCalled(); expect(ElMessage.warning).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it.each([new AxiosError('超时'), httpError(403), new CanceledError('取消')])('旧POST拒绝或取消不从catch发起原UUID查询', async cause => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    let reject!: (cause: unknown) => void
    vi.mocked(api.createTubeOrder).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
    const submitting = vm.save(); const raw = localStorage.getItem(key)!
    if (!('code' in cause) || cause.code !== 'ERR_CANCELED') auth.identityRequestGeneration += 1
    reject(cause); await submitting; await flushPromises()
    expect(localStorage.getItem(key)).toBe(raw); expect(api.findTubeOrder).not.toHaveBeenCalled()
    expect(api.createTubeOrder).toHaveBeenCalledTimes(1); expect(routing.push).not.toHaveBeenCalled()
    expect(ElMessage.warning).not.toHaveBeenCalled(); wrapper.unmount()
  })
  it('卸载后迟到POST不清原记录或导航', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    let resolve!: (value: TubeOrderResult) => void
    vi.mocked(api.createTubeOrder).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const submitting = vm.save(); const raw = localStorage.getItem(key)!
    wrapper.unmount(); resolve(result(JSON.parse(raw) as TubePendingOrderInput)); await submitting
    expect(localStorage.getItem(key)).toBe(raw); expect(routing.push).not.toHaveBeenCalled(); expect(ElMessage.success).not.toHaveBeenCalled()
  })
  it.each(['', '{broken', '{"client_request_id":"unknown"}'])('unknown历史记录原样隔离：%s', async raw => {
    const unknownKey = 'tube-outsourcing-pending:v1:unknown'; localStorage.setItem(unknownKey, raw)
    const { wrapper, vm } = await mountPage(); await vm.save()
    expect(localStorage.getItem(unknownKey)).toBe(raw); expect(localStorage.getItem(key)).toBeNull()
    expect(api.fetchTubeOptions).not.toHaveBeenCalled(); expect(api.findTubeOrder).not.toHaveBeenCalled(); expect(api.createTubeOrder).not.toHaveBeenCalled()
    expect(wrapper.findAllComponents({ name: 'ElAlert' }).some(alert => String(alert.props('title')).includes('身份不明'))).toBe(true)
    wrapper.unmount()
  })
  it('未核验身份不访问存储、不加载API并可见阻断原因', async () => {
    Object.assign(auth, { identityReady: false })
    const storage = vi.spyOn(Storage.prototype, 'getItem')
    const { wrapper, vm } = await mountPage(); await vm.save()
    expect(storage).not.toHaveBeenCalled(); expect(api.fetchTubeOptions).not.toHaveBeenCalled(); expect(api.createTubeOrder).not.toHaveBeenCalled()
    expect(wrapper.findAllComponents({ name: 'ElAlert' }).some(alert => String(alert.props('title')).includes('身份尚未核验'))).toBe(true)
    wrapper.unmount(); storage.mockRestore()
  })
  it('存储不可用时不创建请求且显示恢复存储原因', async () => {
    const storage = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('存储禁用') })
    const { wrapper, vm } = await mountPage(); await vm.save()
    expect(api.fetchTubeOptions).not.toHaveBeenCalled(); expect(api.createTubeOrder).not.toHaveBeenCalled()
    expect(wrapper.findAllComponents({ name: 'ElAlert' }).some(alert => String(alert.props('title')).includes('存储不可用'))).toBe(true)
    wrapper.unmount(); storage.mockRestore()
  })
  it('同身份普通重新核验不改变代次，原请求可正常确认', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    let resolve!: (value: TubeOrderResult) => void
    vi.mocked(api.createTubeOrder).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const submitting = vm.save(); const raw = localStorage.getItem(key)!
    auth.user = { ...auth.user! }
    resolve(result(JSON.parse(raw) as TubePendingOrderInput)); await submitting
    expect(localStorage.getItem(key)).toBeNull(); expect(routing.push).toHaveBeenCalledTimes(1); wrapper.unmount()
  })
  it('清理只删除本页读到的原raw，不覆盖另一页面新记录', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    let resolve!: (value: TubeOrderResult) => void
    vi.mocked(api.createTubeOrder).mockImplementationOnce(() => new Promise(done => { resolve = done }))
    const submitting = vm.save(); const original = localStorage.getItem(key)!
    const newer = '{"client_request_id":"new-page-request"}'; localStorage.setItem(key, newer)
    resolve(result(JSON.parse(original) as TubePendingOrderInput)); await submitting
    expect(localStorage.getItem(key)).toBe(newer); expect(vm.pending).not.toBeNull(); expect(routing.push).not.toHaveBeenCalled(); expect(ElMessage.success).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('保存请求编号失败时显示阻断，不发送无持久化UUID的POST', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('存储禁用') }); await vm.save()
    expect(api.createTubeOrder).not.toHaveBeenCalled(); expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull()
    expect(wrapper.findAllComponents({ name: 'ElAlert' }).length).toBeGreaterThan(0); wrapper.unmount()
  })
  it('清理存储抛错时保留原请求，不能成功提示或导航', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('存储禁用') }); await vm.save()
    expect(localStorage.getItem(key)).not.toBeNull(); expect(vm.pending).not.toBeNull(); expect(ElMessage.success).not.toHaveBeenCalled(); expect(routing.push).not.toHaveBeenCalled(); wrapper.unmount()
  })
  it.each(['', '{broken'])('当前账号损坏或空raw原样保留且不加载API：%s', async raw => {
    localStorage.setItem(key, raw); const { wrapper, vm } = await mountPage(); await vm.save()
    expect(localStorage.getItem(key)).toBe(raw); expect(api.fetchTubeOptions).not.toHaveBeenCalled(); expect(api.createTubeOrder).not.toHaveBeenCalled(); expect(vm.error).toContain('无法读取'); wrapper.unmount()
  })
  it.each([403, 404])('首次同身份可信%s明确拒绝仍按既有语义清记录', async status => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    vi.mocked(api.createTubeOrder).mockRejectedValueOnce(httpError(status)); await vm.save()
    expect(localStorage.getItem(key)).toBeNull(); expect(vm.pending).toBeNull(); expect(api.findTubeOrder).not.toHaveBeenCalled(); wrapper.unmount()
  })
  it.each([403, 404])('未知请求历史重放收到%s保留原UUID、payload和revision', async status => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    vi.mocked(api.createTubeOrder).mockRejectedValueOnce(new AxiosError('超时')); await vm.save()
    const raw = localStorage.getItem(key)!
    vi.mocked(api.createTubeOrder).mockRejectedValueOnce(httpError(status)); await vm.save()
    expect(localStorage.getItem(key)).toBe(raw); expect(JSON.stringify(vm.pending)).toBe(raw)
    expect(api.createTubeOrder).toHaveBeenLastCalledWith(JSON.parse(raw)); wrapper.unmount()
  })
  it.each([httpError(404), new CanceledError('取消')])('原UUID迟到404或取消不在catch重放POST', async cause => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    vi.mocked(api.createTubeOrder).mockRejectedValueOnce(new AxiosError('超时')); await vm.save()
    const raw = localStorage.getItem(key)!
    let reject!: (cause: unknown) => void
    vi.mocked(api.findTubeOrder).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
    vi.mocked(api.createTubeOrder).mockClear(); vi.mocked(ElMessage.warning).mockClear()
    const recovering = vm.save(); if (cause.code !== 'ERR_CANCELED') auth.identityRequestGeneration += 1
    reject(cause); await recovering
    expect(api.createTubeOrder).not.toHaveBeenCalled(); expect(localStorage.getItem(key)).toBe(raw); expect(ElMessage.warning).not.toHaveBeenCalled(); wrapper.unmount()
  })
  it('沿用原表单新建委外总单，管材不再选择或提交五金', async () => {
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), material_rows: [structuredClone(hardware)], material_source_revision: 'material-revision' })
    const { wrapper, vm } = await mountPage()
    expect(wrapper.findAll('.field-grid > label').map(field => field.attributes('title'))).toEqual(planHeaderFields)
    expect(api.fetchTubeSource).toHaveBeenCalledWith({ schedule_product_id: 'schedule-product', category: 'tube', is_plan: true })
    expect(vm.rows[0]!.quantity).toBe('2000')
    expect(vm.materialRows).toEqual([])
    expect(wrapper.find('[aria-controls="hardware-items"]').exists()).toBe(false)
    expect(wrapper.find('#hardware-items').exists()).toBe(false)
    fill(vm); await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledWith(expect.objectContaining({ is_plan: true, schedule_product_id: 'schedule-product', lines: [{ component_identity: 'front', quantity: '600', factory_id: 'factory', price_unit: 'SQUARE_METER', unit_price: '0.15' }] }))
    expect(vi.mocked(api.createTubeOrder).mock.calls[0]![0]).not.toHaveProperty('materials')
    wrapper.unmount()
  })
  it('采购入库参考只显示折合支数，默认计划数量仍取BOM', async () => {
    const reference = { quantity: '2400', unit: '支' as const, purchased_quantity: '400', purchase_unit: '根', conversion_note: '采购实际入库400根 × BOM每根6支 = 2400支。' }
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), rows: [{ ...row, purchase_reference: reference }] })
    const { wrapper, vm } = await mountPage()
    expect(wrapper.findAll('#tube-items th').map(item => item.text())).toContain('采购入库参考（支）')
    expect(wrapper.get('.purchase-reference b').text()).toBe('2,400')
    expect(wrapper.find('.purchase-reference small').exists()).toBe(false)
    expect(wrapper.get('.purchase-reference').attributes('title')).toBe(reference.conversion_note)
    expect(vm.rows[0]!.quantity).toBe('2000')
    vm.rows[0]!.purchase_reference = { ...reference, quantity: null, purchased_quantity: null, conversion_note: '采购根数缺失，无法换算。' }
    await flushPromises()
    expect(wrapper.get('.purchase-reference b').text()).toBe('—')
    expect(wrapper.find('.purchase-reference small').exists()).toBe(false)
    wrapper.unmount()
  })
  it('需求计划可超过BOM和当前库存，建单不要求整根数量', async () => {
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), rows: [{ ...row, stock_quantity: '0', max_quantity: '0' }] })
    const { wrapper, vm } = await mountPage()
    expect(api.fetchTubeSource).toHaveBeenCalledWith(expect.objectContaining({ is_plan: true }))
    expect(vm.rows[0]!.quantity).toBe('2000')
    fill(vm); vm.rows[0]!.quantity = '2501'
    vm.checkDispatch(); expect(vm.dialog).toBe('confirm')
    await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledWith(expect.objectContaining({ lines: [{ component_identity: 'front', quantity: '2501', factory_id: 'factory', price_unit: 'SQUARE_METER', unit_price: '0.15' }] }))
    wrapper.unmount()
  })
  it.each(['600', '0', null])('管材采购入库参考%s支不限制需求计划，数量可填写并超过参考保存', async quantity => {
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), rows: [{ ...row, purchase_reference: { ...row.purchase_reference!, quantity } }] })
    const { wrapper, vm } = await mountPage()
    expect(vm.rows[0]!.quantity).toBe('2000')
    const input = wrapper.findAllComponents({ name: 'ElInput' }).find(item => item.attributes('aria-label') === '前腿管外发支数')!
    expect(input.props('disabled')).toBe(false)
    vm.rows[0]!.factoryId = 'factory'; vm.rows[0]!.unitPrice = '0.15'; vm.checkDispatch(); expect(vm.dialog).toBe('confirm')
    input.vm.$emit('update:modelValue', '2500'); await flushPromises(); expect(vm.rows[0]!.quantity).toBe('2500')
    await vm.loadSource(true); expect(vm.rows[0]!.quantity).toBe('2500'); await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledWith(expect.objectContaining({ lines: [expect.objectContaining({ quantity: '2500' })] }))
    expect(ElMessage.warning).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('计划数量拒绝负数小数文字，刷新保留人工改量和空白', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    for (const value of ['-1', '1.5', '1e3', 'invalid']) {
      vm.rows[0]!.quantity = value; vm.checkDispatch(); expect(vm.dialog).toBe('')
    }
    vm.rows[0]!.quantity = '2100'; await vm.loadSource(true)
    expect(vm.rows[0]!.quantity).toBe('2100')
    vm.rows[0]!.quantity = ''; await vm.loadSource(true)
    expect(vm.rows[0]!.quantity).toBe('')
    expect(api.createTubeOrder).not.toHaveBeenCalled(); wrapper.unmount()
  })
  it('计划保存确认仍显示管材材质、加工厂和单价', async () => {
    const wrapper = shallowMount(TubeOutsourcingFormView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true, stubs: { AppWindowDialog: { props: ['modelValue'], template: '<section v-if="modelValue"><slot /></section>' } } } })
    await flushPromises()
    const vm = wrapper.vm as unknown as ViewModel
    vm.returnDate = '2099-10-14'; fill(vm); vm.rows[0]!.quantity = '601'; vm.checkDispatch(); await flushPromises()
    expect(wrapper.get('.confirm-table').text()).toContain('Q195')
    expect(wrapper.get('.confirm-table').text()).toContain('测试加工厂')
    expect(wrapper.get('.confirm-table').text()).not.toContain('折合')
    expect(wrapper.text()).not.toContain('材料来源')
    expect(wrapper.text()).toContain('空白或0不纳入本单')
    expect(wrapper.text()).toContain('刷新BOM')
    expect(wrapper.text()).toContain('后续可分次外发、独立分次入库')
    expect(wrapper.text()).not.toContain('整单只登记一次')
    wrapper.unmount()
  })
  it('未入库直发建计划不要求主库区，不加载管材五金', async () => {
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), source_kind: 'METAL', zone_id: null, material_rows: [structuredClone(hardware)] })
    const { wrapper, vm } = await mountPage()
    vm.requestChange('source', 'METAL'); await flushPromises()
    expect(api.fetchTubeSource).toHaveBeenLastCalledWith({ schedule_product_id: 'schedule-product', category: 'tube', is_plan: true })
    expect(vm.context?.source_kind).toBe('METAL'); expect(vm.materialRows).toEqual([])
    wrapper.unmount()
  })
  it('产品资料显示产品属性和图片，不混用管材明细属性', async () => {
    const { wrapper, vm } = await mountPage()
    expect(wrapper.get('.product-overview').text()).toContain('47*55*79')
    expect(wrapper.get('.product-overview').text()).toContain('PE')
    expect(wrapper.get('.product-overview').text()).toContain('CP-test')
    expect(wrapper.get('.product-overview').text()).not.toContain('Q195')
    expect(wrapper.findComponent(ProductImage).props('src')).toBe(productDisplay.image_url)
    vm.requestChange('product', '')
    await flushPromises()
    expect(wrapper.get('.product-overview').text()).toContain('选择产品后显示图片')
    expect(wrapper.get('.product-overview').text()).not.toContain('CP-test')
    expect(wrapper.findComponent(ProductImage).exists()).toBe(false)
    wrapper.unmount()
  })
  it('缺图时明确提示，规格缺展示值时保留原规格', async () => {
    const noImageOptions = structuredClone(options)
    Object.assign(noImageOptions.tasks[0]!.products[0]!, { image_url: '', image_file_id: null, specification_display: '', specification: '47*55*79' })
    vi.mocked(api.fetchTubeOptions).mockResolvedValue(noImageOptions)
    const { wrapper } = await mountPage()
    expect(wrapper.get('.product-overview').text()).toContain('暂无产品图片')
    expect(wrapper.get('.product-overview').text()).toContain('47*55*79')
    wrapper.unmount()
  })
  it('图片失败给出提示，重新选择产品后恢复图片展示', async () => {
    const { wrapper, vm } = await mountPage()
    await wrapper.get('.product-overview__image').trigger('error')
    expect(wrapper.get('.product-overview').text()).toContain('图片加载失败')
    vm.requestChange('product', '')
    await flushPromises()
    vm.requestChange('product', 'product')
    await flushPromises()
    expect(wrapper.findComponent(ProductImage).props('src')).toBe(productDisplay.image_url)
    expect(wrapper.get('.product-overview').text()).not.toContain('图片加载失败')
    wrapper.unmount()
  })
  it('全空或全零不能进入保存确认，正数必须填写厂家', async () => {
    const { wrapper, vm } = await mountPage()
    vm.checkDispatch(); expect(vm.dialog).toBe('')
    vm.rows[0]!.quantity = '0'; vm.checkDispatch(); expect(vm.dialog).toBe('')
    vm.rows[0]!.quantity = '600'; vm.checkDispatch(); expect(vm.dialog).toBe('')
    vm.rows[0]!.factoryId = 'factory'; vm.rows[0]!.unitPrice = '0'; vm.checkDispatch(); expect(vm.dialog).toBe('confirm')
    expect(api.createTubeOrder).not.toHaveBeenCalled(); wrapper.unmount()
  })
  it('换来源在确认前保留输入，确认后清空', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    vm.requestChange('source', 'METAL')
    expect(vm.dialog).toBe('change'); expect(vm.rows[0]!.quantity).toBe('600')
    await vm.applyChange(); expect(vm.rows[0]!.quantity).toBe('2000'); expect(vm.rows[0]!.factoryId).toBe('')
    expect(api.createTubeOrder).not.toHaveBeenCalled(); wrapper.unmount()
  })
  it('超时后锁定原请求，回查未找到时也只使用原内容重试', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    vi.mocked(api.createTubeOrder).mockRejectedValueOnce(new AxiosError('超时', 'ECONNABORTED'))
    await vm.save()
    const first = JSON.parse(JSON.stringify(vi.mocked(api.createTubeOrder).mock.calls[0]![0])) as TubeOrderInput
    expect(vm.pending?.client_request_id).toBe(first.client_request_id)
    expect(JSON.parse(localStorage.getItem(key)!)).toEqual(first)
    expect(api.findTubeOrder).toHaveBeenCalledWith(first.client_request_id)
    await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledTimes(2)
    expect(vi.mocked(api.createTubeOrder).mock.calls[1]![0]).toEqual(first)
    expect(localStorage.getItem(key)).toBeNull(); expect(vm.pending).toBeNull()
    expect(vm.rows[0]!.quantity).toBe(''); wrapper.unmount()
  })
  it('超时后查到成功单据时不再次POST', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    vi.mocked(api.createTubeOrder).mockImplementationOnce(async payload => {
      vi.mocked(api.findTubeOrder).mockResolvedValue(result(payload))
      throw new AxiosError('超时', 'ECONNABORTED')
    })
    await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledTimes(1)
    expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull(); wrapper.unmount()
  })
  it('412刷新额度并保留输入，下一次复核生成新编号', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    vi.mocked(api.createTubeOrder).mockRejectedValueOnce(httpError(412))
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...context, source_revision: 'revision-2' })
    await vm.save()
    const first = vi.mocked(api.createTubeOrder).mock.calls[0]![0]
    expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull()
    expect(vm.rows[0]!.quantity).toBe('600'); expect(vm.error).toBe('')
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('重新核对') }))
    await vm.save()
    const next = vi.mocked(api.createTubeOrder).mock.calls[1]![0]
    expect(next.client_request_id).not.toBe(first.client_request_id); expect(next.source_revision).toBe('revision-2')
    wrapper.unmount()
  })
  it('服务端400校验仅显示气泡，不在页面顶部重复展示', async () => {
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), source_kind: 'METAL', zone_id: null })
    const { wrapper, vm } = await mountPage(); fill(vm)
    vi.mocked(api.createTubeOrder).mockRejectedValueOnce(httpError(400))
    await vm.save(); await flushPromises()
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: '状态 400' }))
    expect(vm.error).toBe(''); expect(wrapper.findComponent({ name: 'ElAlert' }).exists()).toBe(false)
    expect(vm.rows[0]!.quantity).toBe('600'); expect(vm.rows[0]!.factoryId).toBe('factory')
    expect(vm.pending).toBeNull(); expect(localStorage.getItem(key)).toBeNull()
    wrapper.unmount()
  })
  it('旧额度响应不覆盖较新响应', async () => {
    const { wrapper, vm } = await mountPage()
    let finish!: (value: TubeSourceContext) => void
    vi.mocked(api.fetchTubeSource).mockReturnValueOnce(new Promise(resolve => { finish = resolve })).mockResolvedValueOnce({ ...context, source_revision: 'latest', rows: [{ ...row, max_quantity: '600' }] })
    const old = vm.loadSource(); await vm.loadSource()
    finish(context); await old
    expect(vm.context?.source_revision).toBe('latest'); expect(vm.rows[0]!.max_quantity).toBe('600')
    wrapper.unmount()
  })
  it('半成品库存为0仍可按BOM建计划，不为找库存自动切换库区', async () => {
    const empty = { ...context, source_kind: 'METAL' as const, zone_id: null, rows: [{ ...row, max_quantity: '0' }] }
    const { wrapper, vm } = await mountPage()
    vi.mocked(api.fetchTubeSource).mockReset(); vi.mocked(api.fetchTubeSource).mockResolvedValue(empty)
    await vm.loadSource(false); await flushPromises()
    expect(api.fetchTubeSource).toHaveBeenCalledExactlyOnceWith({ schedule_product_id: 'schedule-product', category: 'tube', is_plan: true })
    expect(vm.zoneId).toBe(''); expect(vm.sourceHint).toBe('')
    expect(vm.rows[0]!.quantity).toBe('2000')
    wrapper.unmount()
  })
  it('刷新恢复待核对请求及原库区所属仓库，自动回查不自动再写', async () => {
    const payload: TubePendingOrderInput = { client_request_id: 'existing-request', source_revision: 'old-revision', schedule_product_id: 'schedule-product', source_kind: 'RAW_PIPE', zone_id: 'zone-other', planned_dispatch_date: '2026-09-29', expected_return_date: '2026-10-14', remark: '', lines: [{ component_identity: 'front', quantity: '600', factory_id: 'factory' }] }
    localStorage.setItem(key, JSON.stringify(payload))
    const { wrapper, vm } = await mountPage()
    expect(vm.pending).toEqual(payload); expect(vm.warehouseId).toBe('other'); expect(vm.zoneId).toBe('zone-other')
    expect(vm.rows[0]!.priceUnit).toBe('PIECE')
    expect(api.createTubeOrder).not.toHaveBeenCalled(); expect(api.findTubeOrder).toHaveBeenCalledWith('existing-request')
    wrapper.unmount()
  })
  it('管材默认按平方米显示面积并精确计算金额，切换按支后保留选择', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    await flushPromises()
    expect(vm.rows[0]!.priceUnit).toBe('SQUARE_METER')
    expect(vm.totalArea).toBe('75.0000')
    expect(wrapper.get('#tube-items').text()).not.toContain('单支')
    expect(wrapper.get('#tube-items').text()).toContain('75㎡')
    for (const value of ['', '-1', '1e2', '0.151']) {
      vm.rows[0]!.unitPrice = value; vm.checkDispatch(); expect(vm.dialog).toBe('')
    }
    expect(api.createTubeOrder).not.toHaveBeenCalled()
    vm.rows[0]!.unitPrice = '0'; vm.checkDispatch(); expect(vm.dialog).toBe('confirm')
    vm.rows[0]!.unitPrice = '0.15'; await flushPromises()
    expect(vm.plannedAmount).toBe('11.25')
    expect(wrapper.get('.planned-amount').text()).toContain('11.25 元')
    expect(wrapper.get('#tube-items').text()).toContain('计价方式')
    vm.rows[0]!.priceUnit = 'PIECE'; await flushPromises()
    expect(vm.plannedAmount).toBe('90.00')
    await vm.loadSource(true)
    expect(vm.rows[0]!.unitPrice).toBe('0.15'); expect(vm.rows[0]!.priceUnit).toBe('PIECE')
    wrapper.unmount()
  })
  it('各部位可独立选择按支或按平方米计价', async () => {
    const second = { ...structuredClone(row), component_identity: 'back', bom_line_id: 'bom-back', part_name: '后腿管', unit_area_sqm: '0.2500' }
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), rows: [structuredClone(row), second] })
    const { wrapper, vm } = await mountPage()
    Object.assign(vm.rows[0]!, { quantity: '600', factoryId: 'factory', unitPrice: '0.15', priceUnit: 'PIECE' })
    Object.assign(vm.rows[1]!, { quantity: '20', factoryId: 'factory', unitPrice: '2.00', priceUnit: 'SQUARE_METER' })
    await flushPromises()
    expect(vm.plannedAmount).toBe('100.00')
    wrapper.unmount()
  })
  it('缺少有效面积时默认按平方米并阻止保存，改按支后可继续', async () => {
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), rows: [{ ...structuredClone(row), unit_area_sqm: null }] })
    const { wrapper, vm } = await mountPage(); fill(vm)
    expect(vm.rows[0]!.priceUnit).toBe('SQUARE_METER')
    vm.checkDispatch(); expect(vm.dialog).toBe('')
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('改为按支') }))
    vm.rows[0]!.priceUnit = 'PIECE'; vm.checkDispatch(); expect(vm.dialog).toBe('confirm')
    wrapper.unmount()
  })
  it('管材新请求提交逐部位计价方式', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledWith(expect.objectContaining({
      lines: [expect.objectContaining({ component_identity: 'front', price_unit: 'SQUARE_METER', unit_price: '0.15' })],
    }))
    wrapper.unmount()
  })
  it('旧缺价和绑定部位请求恢复后只重放原始内容，不补价或改五金工厂字段', async () => {
    const payload: TubePendingOrderInput = { client_request_id: 'legacy-request', source_revision: 'old-revision', schedule_product_id: 'schedule-product', source_kind: 'RAW_PIPE', zone_id: 'zone', planned_dispatch_date: '2026-09-29', expected_return_date: '2026-10-14', remark: '', lines: [{ component_identity: 'front', quantity: '600', factory_id: 'factory' }], material_source_revision: 'old-material', materials: [{ bom_line_id: 'hardware', component_identity: 'front', quantity: '2.5', zone_id: 'hardware-zone' }] }
    localStorage.setItem(key, JSON.stringify(payload))
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), material_rows: [structuredClone(hardware)], material_source_revision: 'new-material' })
    const { wrapper, vm } = await mountPage()
    expect(vm.pending).toEqual(payload); expect(vm.rows[0]!.unitPrice).toBe('')
    expect(vm.materialRows[0]!.factoryId).toBe('')
    expect(api.createTubeOrder).not.toHaveBeenCalled()
    await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledExactlyOnceWith(payload)
    wrapper.unmount()
  })
  it('不覆盖其他页面留下的未确认请求', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    localStorage.setItem(key, 'existing-record')
    await vm.save()
    expect(api.createTubeOrder).not.toHaveBeenCalled()
    expect(localStorage.getItem(key)).toBe('existing-record')
    wrapper.unmount()
  })
  it('旧请求重放被400拒绝后明确要求重新选厂和填价，不自动生成新请求', async () => {
    const payload: TubePendingOrderInput = { client_request_id: 'legacy-rejected', source_revision: 'old-revision', schedule_product_id: 'schedule-product', source_kind: 'RAW_PIPE', zone_id: 'zone', planned_dispatch_date: '2026-09-29', expected_return_date: '2026-10-14', remark: '', lines: [{ component_identity: 'front', quantity: '600', factory_id: 'factory' }] }
    localStorage.setItem(key, JSON.stringify(payload))
    const { wrapper, vm } = await mountPage()
    vi.mocked(api.createTubeOrder).mockRejectedValueOnce(httpError(400))
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), source_kind: 'METAL', zone_id: null })
    await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledExactlyOnceWith(payload)
    expect(api.fetchTubeSource).toHaveBeenLastCalledWith({ schedule_product_id: 'schedule-product', category: 'tube', is_plan: true })
    expect(vm.context?.source_kind).toBe('METAL')
    expect(vm.pending).toBeNull(); expect(vm.rows[0]!.unitPrice).toBe('')
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('请重新填写加工单价并核对加工厂') }))
    wrapper.unmount()
  })
  it('损坏的本地待核对记录阻止新写入并给出错误', async () => {
    localStorage.setItem(key, JSON.stringify({ client_request_id: 'existing', lines: [{ quantity: 600 }] }))
    const { wrapper, vm } = await mountPage()
    expect(vm.error).toContain('待核对请求记录无法读取')
    await vm.save(); expect(api.createTubeOrder).not.toHaveBeenCalled()
    expect(localStorage.getItem(key)).not.toBeNull()
    wrapper.unmount()
  })
})

describe('原管材表单复用裁片模式', () => {
  const cuttingCrafts: NonNullable<TubeOptions['crafts']> = [
    { id: 'embroidery', name: '刺绣', outsourcing_code: 'EMBROIDERY' },
    { id: 'printing', name: '丝印', outsourcing_code: 'SCREEN_PRINTING' },
    { id: 'cutting-craft', name: '裁剪', outsourcing_code: 'CUTTING' },
    { id: 'sewing-craft', name: '车缝', outsourcing_code: 'SEWING' },
  ]
  const cuttingOptions = (): TubeOptions => ({ ...structuredClone(options),
    crafts: structuredClone(cuttingCrafts),
    tasks: options.tasks.map(task => ({ ...task, products: task.products.map(product => ({ ...product, craft_ids: cuttingCrafts.map(craft => craft.id) })) })),
    source_kinds: [{ value: 'PUBLIC_CUTTING', label: '已入库裁片半成品' }, { value: 'SEWING', label: '车缝完成未入库直发' }],
  })
  const cuttingContext = (): TubeSourceContext => ({ ...structuredClone(context), source_kind: 'SEWING', category: 'cutting', craft_id: 'sewing-craft', craft_name: '车缝',
    rows: [{ ...row, part_name: '座布', fabric_material: '涤纶', specification: '420×380', fabric_specification: '600D', fabric_color: '蓝色', pieces_per_set: '2', completed_craft_name: '车缝完成', pieces_per_bar: null, raw_bar_length_m: null, stock_unit: '套', max_quantity: '100', current_reported_minimum: '200', purchase_reference: { quantity: '3000', unit: '套', purchased_quantity: '1500', purchase_unit: '米', conversion_note: '采购实际入库1500米 ÷ 每成品0.5米 = 3000套。' } }],
    material_rows: [{ ...structuredClone(hardware), name: '织唛', unit: '个' }], material_source_revision: 'cutting-material-revision',
  })
  beforeEach(() => {
    vi.resetAllMocks(); localStorage.clear(); resetIdentity()
    routing.query = { schedule_product_id: 'schedule-product', category: 'cutting' }
    vi.mocked(api.fetchTubeOptions).mockResolvedValue(cuttingOptions())
    vi.mocked(api.fetchTubeSource).mockImplementation(async params => ({ ...cuttingContext(), source_kind: params.source_kind || 'SEWING', zone_id: params.zone_id || null, craft_id: params.craft_id }))
    vi.mocked(api.createTubeOrder).mockImplementation(async payload => result(payload))
    vi.mocked(api.findTubeOrder).mockRejectedValue(httpError(404))
  })
  it('跟单只勾选裁片，按整单需求建丝印计划，不能手输部分需求', async () => {
    routing.name = 'cut-piece-printing-new'
    const config = cuttingOptions()
    config.tasks[0]!.products[0]!.schedule_product_id = null
    routing.query = { product_line_id: 'product' }
    vi.spyOn(printApi, 'fetchPrintOptions').mockResolvedValue(config)
    vi.spyOn(printApi, 'fetchPrintSource').mockResolvedValue({ ...cuttingContext(), part_flow: true, screen_print_pieces: true,
      source_kind: 'CUTTING', craft_id: 'printing', fees_deferred: false, material_rows: [], rows: [
        { ...row, unit: '片', part_name: '面片', parent_name: '靠背', order_required: '200' },
        { ...row, unit: '片', component_identity: 'edge', part_name: '围条', order_required: '100' },
      ] })
    vi.spyOn(printApi, 'createPrintOrder').mockImplementation(async payload => result(payload))
    const { wrapper, vm } = await mountPage(true)
    try {
      expect(printApi.fetchPrintSource).toHaveBeenCalledWith('product', 'printing')
      expect(wrapper.findAll('.field-grid > label').map(field => field.attributes('title'))).toEqual(planHeaderFields)
      expect(wrapper.find('input[aria-label="面片外发片数"]').exists()).toBe(false)
      expect(vm.rows.map(item => item.quantity)).toEqual(['', ''])
      await wrapper.get('input[aria-label="选择面片丝印"]').setValue(true)
      expect(vm.rows[0]!.quantity).toBe('200')
      vm.rows[0]!.factoryId = 'factory'
      vm.rows[0]!.unitPrice = '0.8'
      await vm.save()
      expect(printApi.createPrintOrder).toHaveBeenCalledWith(expect.objectContaining({ product_line_id: 'product', source_kind: 'CUTTING', craft_id: 'printing',
        lines: [{ component_identity: 'front', quantity: '200', factory_id: 'factory', unit_price: '0.8' }] }))
      expect(api.createTubeOrder).not.toHaveBeenCalled()
      expect(routing.push).toHaveBeenCalledWith({ name: 'cut-piece-printing-detail', params: { id: 'saved-order' } })
    } finally { routing.name = ''; wrapper.unmount() }
  })
  it.each(['product_line_id', 'schedule_product_id'] as const)('丝印按 %s 恢复已提交请求，按原内容核对', async field => {
    routing.name = 'cut-piece-printing-new'
    routing.query = {}
    const config = cuttingOptions()
    if (field === 'product_line_id') config.tasks[0]!.products[0]!.schedule_product_id = null
    const frozen = { [field]: field === 'product_line_id' ? 'product' : 'schedule-product',
      client_request_id: 'print-retry', source_revision: 'print-version', source_kind: 'CUTTING', is_plan: true,
      craft_id: 'printing', zone_id: null, planned_dispatch_date: '2026-11-01', expected_return_date: '2026-11-02', remark: '',
      lines: [{ component_identity: 'front', factory_id: 'factory', quantity: '100', unit_price: '2' }] }
    localStorage.setItem(key + ':cut-piece-printing', JSON.stringify(frozen))
    vi.spyOn(printApi, 'fetchPrintOptions').mockResolvedValue(config)
    vi.spyOn(printApi, 'fetchPrintSource').mockResolvedValue(cuttingContext())
    vi.spyOn(printApi, 'findPrintOrder').mockRejectedValue(httpError(404))
    vi.spyOn(printApi, 'createPrintOrder').mockImplementation(async payload => result(payload))
    const { wrapper, vm } = await mountPage()
    try {
      expect(printApi.fetchPrintSource).toHaveBeenCalledWith('product', 'printing')
      expect(printApi.findPrintOrder).toHaveBeenCalledWith('print-retry')
      expect(vm.pending).toEqual(frozen)
      expect(vm.error).toContain('暂未查到这笔外发单')
      expect(printApi.createPrintOrder).not.toHaveBeenCalled()
      await vm.save()
      expect(printApi.createPrintOrder).toHaveBeenCalledExactlyOnceWith(frozen)
    } finally { routing.name = ''; wrapper.unmount() }
  })
  it('选本厂自动带回整部位数量，本厂记录单价不计入计划加工金额', async () => {
    const config = cuttingOptions()
    config.crafts = [{ id: 'sewing-craft', name: '车缝', outsourcing_code: 'SEWING' }]
    vi.mocked(api.fetchTubeOptions).mockResolvedValue(config)
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...cuttingContext(), part_flow: true,
      sewing_inputs: true, source_kind: 'CUTTING', craft_id: 'sewing-craft', fees_deferred: false,
      internal_sewing_factory_id: 'own', factories: [{ id: 'own', name: '本厂' }, { id: 'factory', name: '外厂' }],
      rows: [{ ...row, part_name: '床面', order_required: '10', unit: '个' },
        { ...row, component_identity: 'bag', part_name: '外袋', order_required: '20', unit: '个' }] })
    const { wrapper, vm } = await mountPage(true)
    try {
      vm.rows[0]!.quantity = '2'; vm.rows[0]!.unitPrice = '9'
      vm.rows[1]!.factoryId = 'factory'; vm.rows[1]!.unitPrice = '1.50'
      wrapper.findAllComponents(ElSelect).find(select => select.attributes('aria-label') === '床面加工厂')!
        .vm.$emit('update:modelValue', 'own')
      await flushPromises()
      expect(vm.rows[0]!.quantity).toBe('10')
      expect(wrapper.get('input[aria-label="床面外发个数"]').attributes('disabled')).toBeDefined()
      expect(Number(vm.plannedAmount)).toBe(30)
    } finally { wrapper.unmount() }
  })
  it('新车缝主表和保存确认拆分多来源列，部位规格独立且单价计算和保存不变', async () => {
    routing.query.source_kind = 'CUTTING'
    const config = cuttingOptions()
    config.source_kinds = [{ value: 'CUTTING', label: '车间裁片直发' }]
    config.crafts = [{ id: 'sewing-craft', name: '车缝', outsourcing_code: 'SEWING' }]
    vi.mocked(api.fetchTubeOptions).mockResolvedValue(config)
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...cuttingContext(), source_kind: 'CUTTING',
      part_flow: true, sewing_inputs: true, fees_deferred: false, craft_id: 'sewing-craft', craft_name: '车缝', zone_id: null,
      rows: [{ ...row, part_name: '椅面', unit: '个', order_required: '10', material: '错误父材质',
        component_source_materials: [
          { source_bom_line_id: 'fabric', name: '面布', material: '涤纶', color: '蓝色', color_code: 'B1', fabric_spec: '600D', width: '150', unit: '米' },
          { source_bom_line_id: 'lining', name: '底布', material: '棉', color: '', color_code: '', fabric_spec: '300D', width: '140', unit: '米' },
        ] },
        { ...row, component_identity: 'bag', part_name: '外袋', unit: '件', order_required: '20' }] })
    const { wrapper, vm } = await mountPage(true)
    try {
      vm.rows[0]!.quantity = '10'; vm.rows[0]!.factoryId = 'factory'; vm.rows[0]!.unitPrice = '1.20'
      vm.rows[1]!.quantity = '20'; vm.rows[1]!.factoryId = 'factory'; vm.rows[1]!.unitPrice = '2.50'
      await flushPromises()
      expect(wrapper.findAll('#tube-items th').map(item => item.text())).toContain('目标部位')
      expect(wrapper.findAll('#tube-items th').map(item => item.text())).not.toContain('加工单价（元/套）')
      expect(wrapper.get('.footer-bar').text()).toContain('10 个、20 件')
      expect(wrapper.findAll('#tube-items th').map(item => item.text())).toContain('部位单价')
      expect(wrapper.get('#tube-items').text()).toContain('元/个')
      expect(wrapper.get('#tube-items').text()).toContain('元/件')
      expect(wrapper.get('#tube-items').text()).not.toContain('错误父材质')
      expect(vm.plannedAmount).toBe('62.00')
      vm.checkDispatch(); await flushPromises()
      for (const table of [wrapper.get('#tube-items table'), wrapper.get('.confirm-table')]) {
        const headers = table.findAll('thead th').map(item => item.text())
        const cells = table.findAll('tbody tr')[0]!.findAll('td')
        for (const [label, values] of Object.entries({ 来源布料: ['面布', '底布'], 材质: ['涤纶', '棉'], 颜色: ['蓝色', '未记录'], 面料规格: ['600D', '300D'] })) {
          expect(headers.filter(value => value === label)).toHaveLength(1)
          expect(cells[headers.indexOf(label)]!.findAll('.component-source-value').map(item => item.text())).toEqual(values)
        }
        expect(cells[headers.indexOf('规格')]!.text()).toBe('Φ22')
        expect(cells[headers.indexOf('规格')]!.find('.component-source-value').exists()).toBe(false)
        const width = table.findAll('col').reduce((sum, col) => sum + parseFloat((col.element as HTMLTableColElement).style.width), 0)
        expect((table.element as HTMLTableElement).style.minWidth).toBe(`${width}px`)
        expect(table.element.parentElement!.classList.contains('tube-table-wrap')).toBe(true)
      }
      expect(wrapper.get('.confirm-table').text()).not.toContain('错误父材质')
      await vm.save()
      expect(api.createTubeOrder).toHaveBeenCalledWith(expect.objectContaining({ source_kind: 'CUTTING', zone_id: null,
        lines: [{ component_identity: 'front', quantity: '10', factory_id: 'factory', unit_price: '1.20' },
          { component_identity: 'bag', quantity: '20', factory_id: 'factory', unit_price: '2.50' }] }))
    } finally { wrapper.unmount() }
  })
  it('裁片采购入库参考显示套数并悬浮说明面料换算，不改默认计划套数', async () => {
    const current = cuttingContext()
    current.rows[0]!.purchase_reference = { quantity: '1000', unit: '套', purchased_quantity: '500', purchase_unit: '米', conversion_note: '采购实际入库500米 ÷ BOM每成品0.5米 × 每成品1套 = 1000套。' }
    vi.mocked(api.fetchTubeSource).mockResolvedValue(current)
    const { wrapper, vm } = await mountPage()
    expect(wrapper.findAll('#tube-items th').map(item => item.text())).toContain('采购入库参考（套）')
    expect(wrapper.get('.purchase-reference b').text()).toBe('1,000')
    expect(wrapper.get('.purchase-reference').attributes('title')).toContain('采购实际入库500米')
    expect(wrapper.find('.purchase-reference small').exists()).toBe(false)
    expect(vm.rows[0]!.quantity).toBe('2000')
    wrapper.unmount()
  })
  it.each(['600', '0', null])('裁片采购入库参考%s套不限制需求计划，数量可填写并超过参考保存', async quantity => {
    const current = cuttingContext(); current.rows[0]!.purchase_reference!.quantity = quantity
    vi.mocked(api.fetchTubeSource).mockResolvedValue(current)
    const { wrapper, vm } = await mountPage()
    expect(vm.rows[0]!.quantity).toBe('2000')
    const input = wrapper.findAllComponents({ name: 'ElInput' }).find(item => item.attributes('aria-label') === '座布外发套数')!
    expect(input.props('disabled')).toBe(false)
    vm.rows[0]!.factoryId = 'factory'; vm.rows[0]!.unitPrice = '0.15'; vm.checkDispatch(); expect(vm.dialog).toBe('confirm')
    input.vm.$emit('update:modelValue', '2500'); await flushPromises(); expect(vm.rows[0]!.quantity).toBe('2500')
    await vm.loadSource(true); expect(vm.rows[0]!.quantity).toBe('2500'); await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledWith(expect.objectContaining({ lines: [expect.objectContaining({ quantity: '2500' })] }))
    expect(ElMessage.warning).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('车缝四个表头字段固定，建单和保存确认只处理部位，无需填写任何辅料', async () => {
    localStorage.setItem(key, '管材页未确认记录')
    const current = cuttingContext()
    current.material_rows!.push({ ...current.material_rows![0]!, bom_line_id: 'external', name: '外供织带', external_supply: true })
    vi.mocked(api.fetchTubeSource).mockResolvedValue(current)
    const { wrapper, vm } = await mountPage(true)
    expect(api.fetchTubeOptions).toHaveBeenCalledWith('cutting')
    expect(api.fetchTubeSource).toHaveBeenCalledWith({ schedule_product_id: 'schedule-product', category: 'cutting', craft_id: 'sewing-craft', is_plan: true })
    expect(wrapper.get('h1').text()).toBe('新建车缝外发单')
    expect(wrapper.findAll('.field-grid > label').map(item => item.attributes('title'))).toEqual(planHeaderFields)
    expect(wrapper.find('#hardware-items').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('辅料')
    expect(wrapper.text()).toContain('420×380')
    expect(wrapper.text()).not.toContain('切割长度 mm')
    vm.rows[0]!.quantity = '40'; vm.rows[0]!.factoryId = 'factory'; vm.rows[0]!.unitPrice = '0'
    vm.checkDispatch(); await flushPromises()
    expect(vm.dialog).toBe('confirm')
    expect(wrapper.find('.confirm-material-table').exists()).toBe(false)
    await vm.save()
    const request = vi.mocked(api.createTubeOrder).mock.calls[0]![0]
    expect(request).toMatchObject({ source_kind: 'SEWING', craft_id: 'sewing-craft', zone_id: null,
      lines: [{ component_identity: 'front', quantity: '40', factory_id: 'factory', unit_price: '0' }] })
    expect(request).not.toHaveProperty('materials')
    expect(request).not.toHaveProperty('material_source_revision')
    expect(localStorage.getItem(key)).toBe('管材页未确认记录')
    wrapper.unmount()
  })
  it('待发原请求回读时外供行不回填数量、厂家和库区，保留原编号核对', async () => {
    const current = cuttingContext()
    current.material_rows![0]!.external_supply = true
    vi.mocked(api.fetchTubeSource).mockResolvedValue(current)
    const original = JSON.stringify({
      client_request_id: 'pending-cutting', schedule_product_id: 'schedule-product', source_revision: 'revision',
      source_kind: 'SEWING', craft_id: 'embroidery', zone_id: null, planned_dispatch_date: '2026-10-01', expected_return_date: '2026-10-02', remark: '',
      lines: [{ component_identity: 'front', quantity: '1', factory_id: 'factory', unit_price: '0' }],
      material_source_revision: 'old-revision', materials: [{ bom_line_id: 'hardware', quantity: '2', factory_id: 'factory', zone_id: 'hardware-zone' }],
    })
    localStorage.setItem(key + ':cutting', original)
    const { wrapper, vm } = await mountPage(true)
    const row = wrapper.get('#hardware-items tbody tr')
    expect(row.text()).toContain('外供')
    expect(row.find('input,select,textarea,el-input-stub,el-select-stub,[role="combobox"]').exists()).toBe(false)
    expect(vm.materialRows[0]).toMatchObject({ quantity: '', factoryId: '', zoneId: '' })
    expect(api.findTubeOrder).toHaveBeenCalledWith('pending-cutting')
    expect(api.createTubeOrder).not.toHaveBeenCalled()
    expect(localStorage.getItem(key + ':cutting')).toBe(original)
    wrapper.unmount()
  })
  it('车缝提交超时后按原编号恢复', async () => {
    vi.mocked(api.createTubeOrder).mockRejectedValue(new AxiosError('超时'))
    const { wrapper, vm } = await mountPage()
    fill(vm); await vm.save()
    const request = vi.mocked(api.createTubeOrder).mock.calls[0]![0]
    wrapper.unmount()
    const restored = await mountPage()
    expect(restored.vm.pending).toEqual(request)
    expect(api.findTubeOrder).toHaveBeenLastCalledWith(request.client_request_id)
    expect(api.createTubeOrder).toHaveBeenCalledTimes(1)
    restored.wrapper.unmount()
  })
  it('车缝未关联加工厂时显示提示并阻止提交', async () => {
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...cuttingContext(), factories: [] })
    const { wrapper, vm } = await mountPage()
    const factory = wrapper.findAllComponents(ElSelect).find(select => select.attributes('aria-label') === '座布加工厂')!
    expect(factory.props('noDataText')).toContain('请先添加加工厂并关联该工艺')
    vm.rows[0]!.quantity = '1'; vm.rows[0]!.unitPrice = '0'
    await vm.save()
    expect(api.createTubeOrder).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: '座布：请选择一家加工厂。' }))
    wrapper.unmount()
  })
  it.each(['PUBLIC_CUTTING', 'SEWING'])('旧链接含来源 %s 和其他工艺时仍按车缝建单', async source => {
    routing.query.source_kind = source
    routing.query.craft_id = 'printing'
    const { wrapper, vm } = await mountPage()
    expect(api.fetchTubeSource).toHaveBeenLastCalledWith({ schedule_product_id: 'schedule-product', category: 'cutting', craft_id: 'sewing-craft', is_plan: true })
    expect(wrapper.find('[aria-label="外发工艺"]').exists()).toBe(false)
    fill(vm); await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledWith(expect.objectContaining({ craft_id: 'sewing-craft', zone_id: null }))
    wrapper.unmount()
  })
  it('计划套数须为非负整数，正数量单价不能为空', async () => {
    const { wrapper, vm } = await mountPage()
    vm.rows[0]!.factoryId = 'factory'; vm.rows[0]!.unitPrice = '1'
    for (const quantity of ['1.5', '-1']) { vm.rows[0]!.quantity = quantity; await vm.save() }
    expect(api.createTubeOrder).not.toHaveBeenCalled()
    vm.rows[0]!.quantity = '1'; vm.rows[0]!.unitPrice = ''; await vm.save()
    expect(api.createTubeOrder).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('车缝计划可超过当前库存与BOM数量', async () => {
    const current = cuttingContext()
    current.rows[0]!.max_quantity = '0'
    vi.mocked(api.fetchTubeSource).mockResolvedValue(current)
    const { wrapper, vm } = await mountPage()
    vm.rows[0]!.quantity = '2500'; vm.rows[0]!.factoryId = 'factory'; vm.rows[0]!.unitPrice = '1'
    await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledWith(expect.objectContaining({ is_plan: true, lines: [expect.objectContaining({ quantity: '2500' })] }))
    wrapper.unmount()
  })
  it('车缝入口只能选择有车缝工艺的产品和任务', async () => {
    const config = cuttingOptions()
    const task = config.tasks[0]!
    task.products.push({ ...task.products[0]!, id: 'not-sewing', craft_ids: ['embroidery'] })
    config.tasks.push({ ...task, id: 'other-task', products: [task.products[1]!] })
    vi.mocked(api.fetchTubeOptions).mockResolvedValue(config)
    const wrapper = shallowMount(TubeOutsourcingFormView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
    await flushPromises()
    const values = (label: string) => wrapper.findAllComponents(ElSelect).find(select => select.attributes('aria-label') === label)!
      .findAll('el-option-stub').map(option => option.attributes('value'))
    expect(values('生产任务单')).toEqual(['task'])
    expect(values('产品')).toEqual(['product'])
    wrapper.unmount()
  })
})
