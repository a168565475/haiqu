import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessage, ElSelect } from 'element-plus'
import { AxiosError } from 'axios'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/tubeOutsourcing'
import type { TubeOptions, TubeOrderInput, TubePendingOrderInput, TubeOrderResult, TubeSourceContext, TubeSourceRow } from '@/types/tubeOutsourcing'
import TubeOutsourcingFormView from './TubeOutsourcingFormView.vue'
import ProductImage from '@/components/products/ProductImage.vue'

const routing = vi.hoisted(() => ({ query: { schedule_product_id: 'schedule-product' } as Record<string, string> }))
vi.mock('vue-router', () => ({ useRoute: () => routing, useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 'actor', is_superuser: true }, hasPermission: () => true }) }))
vi.mock('@/api/tubeOutsourcing', () => ({ fetchTubeOptions: vi.fn(), fetchTubeSource: vi.fn(), createTubeOrder: vi.fn(), findTubeOrder: vi.fn() }))
vi.mock('element-plus', async original => ({ ...await original<typeof import('element-plus')>(), ElMessage: { warning: vi.fn(), success: vi.fn() } }))

const key = 'tube-outsourcing-pending:v1:actor'
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
const row: TubeSourceRow = { component_identity: 'front', bom_line_id: 'bom-front', part_name: '前腿管', material: 'Q195', specification: 'Φ22', thickness: '0.8', cutting_length_mm: '650', raw_color: '原料本色', spray_color: '黑色', order_required: '2000', stock_quantity: '200', stock_unit: '根', max_quantity: '1200', pieces_per_bar: '6', raw_bar_length_m: '3.95', blockers: [] }
const context: TubeSourceContext = { source_revision: 'revision-1', source_kind: 'RAW_PIPE', schedule_product_id: 'schedule-product', product_line_id: 'product', task_id: 'task', task_number: 'SC-test', order_number: 'DD-test', schedule_number: 'PC-test', product_number: 'CP-test', item_number: 'HT-test', product_name: '测试椅', quantity: '1000', unit: '把', color: '黑色', ...productDisplay, craft_name: '喷塑', zone_id: 'zone', ready: true, blockers: [], tasks: options.tasks, factories: options.factories, zones: options.zones, rows: [row] }
const hardware = { bom_line_id: 'hardware', material_number: 'WJ-test', name: '铁垫片', specification: 'M8', material: '铁', color: '黑色', unit: 'kg', required_quantity: '50', order_remaining: '30', available_stock: '20', max_quantity: '20', blockers: [], zones: [{ zone_id: 'hardware-zone', zone_name: '五金区', warehouse_id: 'hardware-warehouse', warehouse_name: '五金仓', available_quantity: '20' }] }
const result = (payload: TubePendingOrderInput): TubeOrderResult => ({ ...payload, id: 'saved-order', order_number: 'WF-real-response', status: 'PENDING_DISPATCH', version: 1, etag: 'saved', created: true, product_line_id: 'product', total_quantity: '600', total_stock_quantity: '100', total_meters: '395.00', planned_amount: '90.00' })
const httpError = (status: number) => Object.assign(new AxiosError('接口错误'), { response: { status, data: { error: { message: `状态 ${status}` } } } })
interface ViewModel {
  rows: Array<TubeSourceRow & { quantity: string; factoryId: string; unitPrice: string }>; returnDate: string
  dialog: string; pending: TubePendingOrderInput | null; error: string; sourceHint: string; warehouseId: string; zoneId: string
  context: TubeSourceContext | null
  materialRows: Array<typeof hardware & { quantity: string; factoryId: string; zoneId: string }>
  plannedAmount: string | null
  checkDispatch: () => void; save: () => Promise<void>; loadSource: (preserve?: boolean) => Promise<void>
  requestChange: (kind: string, value: string) => void; applyChange: () => Promise<void>
}
async function mountPage() {
  const wrapper = shallowMount(TubeOutsourcingFormView, { global: { plugins: [ElementPlus] } })
  await flushPromises()
  const vm = wrapper.vm as unknown as ViewModel
  vm.returnDate = '2099-10-14'
  return { wrapper, vm }
}
function fill(vm: ViewModel) { vm.rows[0]!.quantity = '600'; vm.rows[0]!.factoryId = 'factory'; vm.rows[0]!.unitPrice = '0.15' }

describe('管材建单与异常恢复', () => {
  beforeEach(() => {
    vi.resetAllMocks(); localStorage.clear()
    routing.query = { schedule_product_id: 'schedule-product' }
    vi.mocked(api.fetchTubeOptions).mockResolvedValue(structuredClone(options))
    vi.mocked(api.fetchTubeSource).mockResolvedValue(structuredClone(context))
    vi.mocked(api.findTubeOrder).mockRejectedValue(httpError(404))
    vi.mocked(api.createTubeOrder).mockImplementation(async payload => result(payload))
  })
  it('五金随管材同一请求保存，切换分类保留双方输入', async () => {
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), material_rows: [structuredClone(hardware)], material_source_revision: 'material-revision' })
    const { wrapper, vm } = await mountPage(); fill(vm)
    vm.materialRows[0]!.quantity = '12.3456'; vm.materialRows[0]!.factoryId = 'hardware-factory'
    await wrapper.get('[role="tab"][aria-controls="hardware-items"]').trigger('click')
    expect(vm.rows[0]!.quantity).toBe('600')
    await wrapper.get('[role="tab"][aria-controls="tube-items"]').trigger('click')
    expect(vm.materialRows[0]!.quantity).toBe('12.3456')
    vm.checkDispatch(); expect(vm.dialog).toBe('confirm')
    await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledWith(expect.objectContaining({
      material_source_revision: 'material-revision',
      materials: [{ bom_line_id: 'hardware', factory_id: 'hardware-factory', quantity: '12.3456', zone_id: 'hardware-zone' }],
      lines: [{ component_identity: 'front', quantity: '600', factory_id: 'factory', unit_price: '0.15' }],
    }))
    wrapper.unmount()
  })
  it('保存确认展示管材和附带五金各自的材质，不混用产品材质', async () => {
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), material_rows: [structuredClone(hardware)], material_source_revision: 'material-revision' })
    const wrapper = shallowMount(TubeOutsourcingFormView, { global: { plugins: [ElementPlus], stubs: { AppWindowDialog: { props: ['modelValue'], template: '<section v-if="modelValue"><slot /></section>' } } } })
    await flushPromises()
    const vm = wrapper.vm as unknown as ViewModel
    vm.returnDate = '2099-10-14'; fill(vm)
    vm.materialRows[0]!.quantity = '1'; vm.materialRows[0]!.factoryId = 'hardware-factory'
    vm.checkDispatch(); await flushPromises()
    const tubeTable = wrapper.get('.confirm-table')
    const hardwareTable = wrapper.findAll('table').at(-1)!
    expect(tubeTable.findAll('th').slice(0, 4).map(cell => cell.text())).toEqual(['部位', '材质', '加工厂', '本次外发（支）'])
    expect(tubeTable.findAll('tbody td')[1]!.text()).toBe('Q195')
    expect(hardwareTable.findAll('tbody td')[1]!.text()).toBe('铁')
    vm.rows[0]!.material = ''; vm.materialRows[0]!.material = ''
    await flushPromises()
    expect(tubeTable.findAll('tbody td')[1]!.text()).toBe('—')
    expect(hardwareTable.findAll('tbody td')[1]!.text()).toBe('—')
    expect(api.createTubeOrder).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('五金数量、加工厂和库区不足时不能进入保存确认', async () => {
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), material_rows: [structuredClone(hardware)], material_source_revision: 'material-revision' })
    const { wrapper, vm } = await mountPage(); fill(vm)
    const material = vm.materialRows[0]!
    material.quantity = '1'; vm.checkDispatch(); expect(vm.dialog).toBe('')
    material.factoryId = 'unknown'; vm.checkDispatch(); expect(vm.dialog).toBe('')
    material.factoryId = 'hardware-factory'; material.zoneId = 'unknown'; vm.checkDispatch(); expect(vm.dialog).toBe('')
    material.zoneId = 'hardware-zone'
    for (const quantity of ['-1', '1e1', '1.23456', '21']) {
      material.quantity = quantity; vm.checkDispatch(); expect(vm.dialog).toBe('')
    }
    material.quantity = '1'; vm.checkDispatch(); expect(vm.dialog).toBe('confirm')
    expect(api.createTubeOrder).not.toHaveBeenCalled(); wrapper.unmount()
  })
  it('未入库半成品无主库区也加载来源，附带五金保留自己的库区', async () => {
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), source_kind: 'METAL', zone_id: null, material_rows: [structuredClone(hardware)], material_source_revision: 'material-revision' })
    const { wrapper, vm } = await mountPage()
    vm.requestChange('source', 'METAL'); await flushPromises()
    expect(api.fetchTubeSource).toHaveBeenLastCalledWith({ schedule_product_id: 'schedule-product', source_kind: 'METAL' })
    expect(vm.context?.source_kind).toBe('METAL')
    expect(vm.materialRows[0]?.zoneId).toBe('hardware-zone')
    wrapper.unmount()
  })
  it('五金提交超时后保留原材料请求，恢复确认不会另建一单', async () => {
    vi.mocked(api.fetchTubeSource).mockResolvedValue({ ...structuredClone(context), material_rows: [structuredClone(hardware)], material_source_revision: 'material-revision' })
    const { wrapper, vm } = await mountPage(); fill(vm)
    vm.materialRows[0]!.quantity = '2.5'; vm.materialRows[0]!.factoryId = 'hardware-factory'
    vi.mocked(api.createTubeOrder).mockRejectedValueOnce(new AxiosError('超时', 'ECONNABORTED'))
    await vm.save()
    const original = structuredClone(JSON.parse(localStorage.getItem(key)!)) as TubeOrderInput
    expect(original.materials?.[0]?.quantity).toBe('2.5')
    vi.mocked(api.findTubeOrder).mockResolvedValue(result(original))
    await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem(key)).toBeNull(); wrapper.unmount()
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
    await vm.applyChange(); expect(vm.rows[0]!.quantity).toBe(''); expect(vm.rows[0]!.factoryId).toBe('')
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
  it('未喷塑半成品自动跳过无库存库区并选中有库存库区', async () => {
    const empty = { ...context, source_kind: 'PUBLIC_SEMI' as const, zone_id: 'semi-empty', rows: [{ ...row, max_quantity: '0' }] }
    const ready = { ...empty, zone_id: 'semi-ready', rows: [{ ...row, max_quantity: '36' }] }
    const { wrapper, vm } = await mountPage()
    vi.mocked(api.fetchTubeSource).mockReset()
    vi.mocked(api.fetchTubeSource).mockResolvedValueOnce(empty).mockResolvedValueOnce(ready)
    vm.requestChange('source', 'PUBLIC_SEMI')
    await flushPromises()
    expect(api.fetchTubeSource).toHaveBeenNthCalledWith(1, { schedule_product_id: 'schedule-product', source_kind: 'PUBLIC_SEMI', zone_id: 'semi-empty' })
    expect(api.fetchTubeSource).toHaveBeenNthCalledWith(2, { schedule_product_id: 'schedule-product', source_kind: 'PUBLIC_SEMI', zone_id: 'semi-ready' })
    expect(vm.zoneId).toBe('semi-ready'); expect(vm.warehouseId).toBe('semi-warehouse-2')
    expect(vm.context?.rows[0]?.max_quantity).toBe('36'); expect(vm.sourceHint).toBe('')
    wrapper.unmount()
  })
  it('所有半成品库区均无库存时明确提示0支', async () => {
    const empty = { ...context, source_kind: 'PUBLIC_SEMI' as const, zone_id: 'semi-empty', rows: [{ ...row, max_quantity: '0' }] }
    const { wrapper, vm } = await mountPage()
    vi.mocked(api.fetchTubeSource).mockReset()
    vi.mocked(api.fetchTubeSource).mockResolvedValue(empty)
    vm.requestChange('source', 'PUBLIC_SEMI')
    await flushPromises()
    expect(vm.sourceHint).toContain('均为 0 支')
    wrapper.unmount()
  })
  it('刷新恢复待核对请求及原库区所属仓库，自动回查不自动再写', async () => {
    const payload: TubePendingOrderInput = { client_request_id: 'existing-request', source_revision: 'old-revision', schedule_product_id: 'schedule-product', source_kind: 'RAW_PIPE', zone_id: 'zone-other', planned_dispatch_date: '2026-09-29', expected_return_date: '2026-10-14', remark: '', lines: [{ component_identity: 'front', quantity: '600', factory_id: 'factory' }] }
    localStorage.setItem(key, JSON.stringify(payload))
    const { wrapper, vm } = await mountPage()
    expect(vm.pending).toEqual(payload); expect(vm.warehouseId).toBe('other'); expect(vm.zoneId).toBe('zone-other')
    expect(api.createTubeOrder).not.toHaveBeenCalled(); expect(api.findTubeOrder).toHaveBeenCalledWith('existing-request')
    wrapper.unmount()
  })
  it('加工单价缺失或不合法阻止保存，真实0有效，金额按支数计算并去尾零', async () => {
    const { wrapper, vm } = await mountPage(); fill(vm)
    for (const value of ['', '-1', '1e2', '0.151']) {
      vm.rows[0]!.unitPrice = value; vm.checkDispatch(); expect(vm.dialog).toBe('')
    }
    expect(api.createTubeOrder).not.toHaveBeenCalled()
    vm.rows[0]!.unitPrice = '0'; vm.checkDispatch(); expect(vm.dialog).toBe('confirm')
    vm.rows[0]!.unitPrice = '0.15'; await flushPromises()
    expect(vm.plannedAmount).toBe('90.00')
    expect(wrapper.get('.planned-amount').text()).toContain('90 元')
    expect(wrapper.get('#tube-items').text()).toContain('加工单价（元/支）')
    await vm.loadSource(true)
    expect(vm.rows[0]!.unitPrice).toBe('0.15')
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
    await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledExactlyOnceWith(payload)
    expect(vm.pending).toBeNull(); expect(vm.rows[0]!.unitPrice).toBe('')
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('请重新填写加工单价并选择五金加工厂') }))
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
    crafts: [{ id: 'embroidery', name: '刺绣', outsourcing_code: 'EMBROIDERY' }],
    tasks: options.tasks.map(task => ({ ...task, products: task.products.map(product => ({ ...product, craft_ids: cuttingCrafts.map(craft => craft.id) })) })),
    source_kinds: [{ value: 'PUBLIC_CUTTING', label: '已入库裁片半成品' }, { value: 'SEWING', label: '车缝完成未入库直发' }],
  })
  const cuttingContext = (): TubeSourceContext => ({ ...structuredClone(context), source_kind: 'PUBLIC_CUTTING', category: 'cutting', craft_id: 'embroidery', craft_name: '刺绣',
    rows: [{ ...row, part_name: '座布', fabric_material: '涤纶', specification: '420×380', fabric_specification: '600D', fabric_color: '蓝色', pieces_per_set: '2', completed_craft_name: '车缝完成', pieces_per_bar: null, raw_bar_length_m: null, stock_unit: '套', max_quantity: '100', current_reported_minimum: '200' }],
    material_rows: [{ ...structuredClone(hardware), name: '织唛', unit: '个' }], material_source_revision: 'cutting-material-revision',
  })
  beforeEach(() => {
    vi.resetAllMocks(); localStorage.clear()
    routing.query = { schedule_product_id: 'schedule-product', category: 'cutting' }
    vi.mocked(api.fetchTubeOptions).mockResolvedValue(cuttingOptions())
    vi.mocked(api.fetchTubeSource).mockImplementation(async params => ({ ...cuttingContext(), source_kind: params.source_kind, zone_id: params.zone_id || null, craft_id: params.craft_id }))
    vi.mocked(api.createTubeOrder).mockImplementation(async payload => result(payload))
    vi.mocked(api.findTubeOrder).mockRejectedValue(httpError(404))
  })
  it('库存裁片按套填写，与辅料在同一原接口提交工艺和各自库区', async () => {
    localStorage.setItem(key, '管材页未确认记录')
    const { wrapper, vm } = await mountPage()
    expect(api.fetchTubeOptions).toHaveBeenCalledWith('cutting')
    expect(api.fetchTubeSource).toHaveBeenCalledWith({ schedule_product_id: 'schedule-product', source_kind: 'PUBLIC_CUTTING', zone_id: 'semi-empty', craft_id: 'embroidery' })
    expect(wrapper.text()).toContain('新建裁片外发单')
    expect(wrapper.text()).toContain('加工单价（元/套）')
    expect(wrapper.text()).toContain('420×380')
    expect(wrapper.text()).not.toContain('600D')
    expect(wrapper.text()).not.toContain('切割长度 mm')
    vm.rows[0]!.quantity = '40'; vm.rows[0]!.factoryId = 'factory'; vm.rows[0]!.unitPrice = '0'
    vm.materialRows[0]!.quantity = '12.3456'; vm.materialRows[0]!.factoryId = 'hardware-factory'
    await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledWith(expect.objectContaining({ source_kind: 'PUBLIC_CUTTING', craft_id: 'embroidery', zone_id: 'semi-empty',
      lines: [{ component_identity: 'front', quantity: '40', factory_id: 'factory', unit_price: '0' }],
      materials: [{ bom_line_id: 'hardware', factory_id: 'hardware-factory', quantity: '12.3456', zone_id: 'hardware-zone' }],
    }))
    expect(localStorage.getItem(key)).toBe('管材页未确认记录')
    wrapper.unmount()
  })
  it('车缝直发不提交主库区，辅料仍提交真实来源库区', async () => {
    routing.query.source_kind = 'SEWING'
    const { wrapper, vm } = await mountPage()
    expect(api.fetchTubeSource).toHaveBeenLastCalledWith({ schedule_product_id: 'schedule-product', source_kind: 'SEWING', craft_id: 'embroidery' })
    expect(wrapper.find('[aria-label="来源仓库"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('报工完成（套）')
    vm.rows[0]!.quantity = '20'; vm.rows[0]!.factoryId = 'factory'; vm.rows[0]!.unitPrice = '1.5'
    vm.materialRows[0]!.quantity = '1'; vm.materialRows[0]!.factoryId = 'hardware-factory'
    await vm.save()
    expect(api.createTubeOrder).toHaveBeenCalledWith(expect.objectContaining({ source_kind: 'SEWING', zone_id: null, craft_id: 'embroidery', materials: [expect.objectContaining({ zone_id: 'hardware-zone' })] }))
    wrapper.unmount()
  })
  it.each(cuttingCrafts)('无加工厂仍可选择 $name，主料和辅料提示先添加关联且不能提交', async craft => {
    vi.mocked(api.fetchTubeOptions).mockResolvedValue({ ...cuttingOptions(), crafts: structuredClone(cuttingCrafts), factories: [] })
    vi.mocked(api.fetchTubeSource).mockImplementation(async params => ({ ...cuttingContext(), craft_id: params.craft_id, factories: [] }))
    const wrapper = shallowMount(TubeOutsourcingFormView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true } })
    await flushPromises()
    const vm = wrapper.vm as unknown as ViewModel
    const craftSelect = wrapper.findAllComponents(ElSelect).find(select => select.attributes('aria-label') === '外发工艺')!
    expect(craftSelect.findAll('el-option-stub').map(option => option.attributes('label'))).toEqual(cuttingCrafts.map(item => item.name))
    expect(craftSelect.attributes('disabled')).toBe('false')
    craftSelect.vm.$emit('update:modelValue', craft.id)
    await flushPromises()
    expect(api.fetchTubeSource).toHaveBeenCalledWith(expect.objectContaining({ craft_id: craft.id }))
    for (const label of ['座布加工厂', '织唛加工厂']) {
      const factorySelect = wrapper.findAllComponents(ElSelect).find(select => select.attributes('aria-label') === label)!
      expect(factorySelect.props('noDataText')).toBe('该工艺暂无加工厂，请先添加加工厂并关联该工艺')
      expect(factorySelect.find('el-option-stub').exists()).toBe(false)
    }
    vm.returnDate = '2099-10-14'; vm.rows[0]!.quantity = '1'; vm.rows[0]!.unitPrice = '0'
    vm.materialRows[0]!.quantity = '1'
    await vm.save()
    expect(api.createTubeOrder).not.toHaveBeenCalled()
    expect(vm.pending).toBeNull()
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.objectContaining({ message: '座布：请选择一家加工厂。' }))
    wrapper.unmount()
  })
  it.each(cuttingCrafts.flatMap(craft => (['PUBLIC_CUTTING', 'SEWING'] as const).map(source => ({ ...craft, source }))))(
    '$source 来源选择 $name 后按原接口提交该工艺编号', async craft => {
      routing.query.source_kind = craft.source
      vi.mocked(api.fetchTubeOptions).mockResolvedValue({ ...cuttingOptions(), crafts: structuredClone(cuttingCrafts) })
      const { wrapper, vm } = await mountPage()
      expect(api.fetchTubeSource).not.toHaveBeenCalled()
      vm.requestChange('craft', craft.id); await flushPromises()
      expect(api.fetchTubeSource).toHaveBeenLastCalledWith({ schedule_product_id: 'schedule-product', source_kind: craft.source,
        craft_id: craft.id, ...(craft.source === 'PUBLIC_CUTTING' ? { zone_id: 'semi-empty' } : {}) })
      vm.rows[0]!.quantity = '2'; vm.rows[0]!.factoryId = 'factory'; vm.rows[0]!.unitPrice = '1'
      await vm.save()
      expect(api.createTubeOrder).toHaveBeenCalledWith(expect.objectContaining({ craft_id: craft.id, source_kind: craft.source,
        zone_id: craft.source === 'PUBLIC_CUTTING' ? 'semi-empty' : null,
        lines: [{ component_identity: 'front', quantity: '2', factory_id: 'factory', unit_price: '1' }] }))
      wrapper.unmount()
    },
  )
  it('套数不能小数或超额，正数量单价不能为空', async () => {
    const { wrapper, vm } = await mountPage()
    vm.rows[0]!.factoryId = 'factory'; vm.rows[0]!.unitPrice = '1'
    for (const quantity of ['1.5', '101', '-1']) { vm.rows[0]!.quantity = quantity; await vm.save() }
    expect(api.createTubeOrder).not.toHaveBeenCalled()
    vm.rows[0]!.quantity = '1'; vm.rows[0]!.unitPrice = ''; await vm.save()
    expect(api.createTubeOrder).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('两个可选工艺必须先选择，切换工艺须重新确认来源并清空填写', async () => {
    const data = cuttingOptions(); data.crafts!.push({ id: 'printing', name: '丝印', outsourcing_code: 'SCREEN_PRINTING' })
    vi.mocked(api.fetchTubeOptions).mockResolvedValue(data)
    const { wrapper, vm } = await mountPage()
    expect(api.fetchTubeSource).not.toHaveBeenCalled()
    vm.requestChange('craft', 'embroidery'); await flushPromises()
    vm.rows[0]!.quantity = '10'; vm.rows[0]!.factoryId = 'factory'
    vm.requestChange('craft', 'printing'); await flushPromises()
    expect(vm.dialog).toBe('change')
    expect(vm.rows[0]!.quantity).toBe('10')
    await vm.applyChange(); await flushPromises()
    expect(api.fetchTubeSource).toHaveBeenLastCalledWith(expect.objectContaining({ craft_id: 'printing' }))
    expect(vm.rows[0]!.quantity).toBe(''); expect(vm.rows[0]!.factoryId).toBe('')
    wrapper.unmount()
  })
})
