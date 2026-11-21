import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/inventory'
import MaterialQualityConfirmationView from './MaterialQualityConfirmationView.vue'
import { router } from '@/router'

const currentRoute = vi.hoisted(() => ({ value: { query: {} as Record<string, string> } }))
vi.mock('@/router', () => ({ router: { push: vi.fn(), currentRoute } }))
const identity = vi.hoisted(() => ({ user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 0, identityRequestGeneration: 0, hasPermission: () => true }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => identity }))
vi.mock('@/api/inventory', () => ({ fetchMaterialQualityBatches: vi.fn(), fetchMaterialQualityBatch: vi.fn(), confirmMaterialQuality: vi.fn() }))
const line = { id: 'line-1', received_quantity: '3.0000', return_quantity: '0.0000', quality_remark: '', supplier_name_snapshot: '供应商' }
const first = { id: 'batch-1', inbound_number: 'RK01', status: 'PENDING_QUALITY', lines: [line] }
const second = { ...first, id: 'batch-2', inbound_number: 'RK02', lines: [{ ...line, id: 'line-2' }] }
type View = { loading: boolean; loadError: string; canSubmit: boolean; selectedBatchId: string; batch: typeof first | null; rows: Array<{ included: boolean; line: typeof line; returnQuantity: string; qualityRemark: string }>; loadBatches: () => Promise<void>; selectBatch: (preserve?: boolean) => Promise<void>; confirmInbound: () => Promise<void> }
const mount = () => shallowMount(MaterialQualityConfirmationView, {
  global: { plugins: [ElementPlus], stubs: { ElTooltip: { inheritAttrs: false, template: '<slot />' } } },
})
// Element Plus declares MessageBoxData as input-data & Action; confirm without input resolves the action string.
const confirmedAction = 'confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>
describe('品质确认读取', () => {
  beforeEach(() => {
    vi.resetAllMocks(); localStorage.clear()
    currentRoute.value.query = {}
    Object.assign(identity, { user: { id: 7 }, initialized: true, identityReady: true, identityGeneration: 0, identityRequestGeneration: 0 })
    vi.mocked(api.fetchMaterialQualityBatches).mockResolvedValue([first, second] as never)
    vi.mocked(api.fetchMaterialQualityBatch).mockImplementation(async id => (id === second.id ? second : first) as never)
  })
  it('从入库记录只打开指定批次，确认后返回记录列表', async () => {
    currentRoute.value.query = { receipt: second.id }
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View
    expect(api.fetchMaterialQualityBatches).not.toHaveBeenCalled()
    expect(api.fetchMaterialQualityBatch).toHaveBeenCalledExactlyOnceWith(second.id)
    expect(vm.batch?.id).toBe(second.id)
    const dialog = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce(confirmedAction)
    await vm.confirmInbound()
    expect(api.confirmMaterialQuality).toHaveBeenCalledWith(second.id, expect.any(Object))
    expect(router.push).toHaveBeenCalledWith({ name: 'purchase-receipt-records' })
    dialog.mockRestore()
    wrapper.unmount()
  })
  it('米制管材质检按采购米显示与录入，退货只能为冻结原长整数倍', async () => {
    vi.mocked(api.fetchMaterialQualityBatches).mockResolvedValue([{ ...first, lines: [{ ...line, measurement_kind: 'PIPE', raw_bar_length_m: '3.35', received_bar_count: 10, return_bar_count: 0, received_quantity: '33.5000', source_unit_text_snapshot: '米' }] }] as never)
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    vm.rows[0]!.returnQuantity = '6.7'; await flushPromises()
    const cells = wrapper.findAll('td.quantity-cell')
    expect(cells[0]!.text()).toBe('33.5 米'); expect(cells[1]!.text()).toBe('26.8 米')
    expect(cells[1]!.attributes('title')).toBe('26.8 米')
    expect(vm.canSubmit).toBe(true)
    vm.rows[0]!.returnQuantity = '0.5'; expect(vm.canSubmit).toBe(false)
    vm.rows[0]!.returnQuantity = '36.85'; expect(vm.canSubmit).toBe(false)
    vm.rows[0]!.returnQuantity = '33.5'; await flushPromises()
    expect(cells[1]!.text()).toBe('0 米'); expect(vm.canSubmit).toBe(true)
    wrapper.unmount()
  })
  it('品质确认按五金件、塑料件、包材顺序分表，空分类不显示', async () => {
    const box = { ...line, part_name_snapshot: '纸箱', material_selection_snapshot: {
      schema_version: 1, category_key: 'PACKAGING', template_key: 'CARTON', name: '纸箱', attributes: { box_type: '半盖', layers: '5' },
    } }
    const screw = { ...line, id: 'line-2', part_name_snapshot: '螺丝', specification_snapshot: 'M6', section_title_snapshot: '五金件类' }
    vi.mocked(api.fetchMaterialQualityBatches).mockResolvedValue([{ ...first, lines: [box, screw] }] as never)
    const wrapper = mount(); await flushPromises()
    const tables = wrapper.findAll('.receipt-material-group')
    expect(tables.map(table => table.get('h3').text())).toEqual(['五金件', '包材'])
    const header = (table: typeof tables[number]) => table.findAll('thead th').map(cell => cell.text())
    expect(tables.map(table => header(table).slice(0, 4))).toEqual(Array.from({ length: 2 }, () => ['', '序号', '物料信息', '供应商']))
    expect(tables.map(table => header(table).slice(4, -7))).toEqual([['规格'], ['箱子形状', '层数']])
    expect(tables.map(table => header(table).slice(-7, -4))).toEqual(Array.from({ length: 2 }, () => ['到货数量', '退货数量', '合格入库数量']))
    expect(tables[1]!.findAll('tbody td').map(cell => cell.text()).slice(4, 6)).toEqual(['半盖', '5'])
    expect(wrapper.find('.specification-cell').exists()).toBe(false)
    wrapper.unmount()
  })
  it('面料和辅料分表时仍按原单一次确认完整质检结果', async () => {
    const accessory = { ...line, part_name_snapshot: '织带', category_snapshot: '辅料类' }
    const fabric = { ...line, id: 'line-2', part_name_snapshot: '牛津布', section_title_snapshot: '面料类' }
    vi.mocked(api.fetchMaterialQualityBatches).mockResolvedValue([{ ...first, lines: [accessory, fabric] }] as never)
    const wrapper = mount(); await flushPromises()
    expect(wrapper.findAll('.receipt-material-group h3').map(title => title.text())).toEqual(['面料', '辅料'])
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce(confirmedAction)
    await (wrapper.vm as unknown as View).confirmInbound()
    expect(api.confirmMaterialQuality).toHaveBeenCalledExactlyOnceWith(first.id, { items: [
      expect.objectContaining({ line_id: accessory.id }), expect.objectContaining({ line_id: fabric.id }),
    ] })
    confirm.mockRestore(); wrapper.unmount()
  })
  it('按根质检拒绝小数与超退，退货数量与确认时的到货数量都用根', async () => {
    const pipe = { ...line, measurement_kind: 'PIPE', source_unit_text_snapshot: 'KG',
      raw_bar_length_m: '3.35', received_quantity: '33.50', received_bar_count: 10, return_bar_count: 0,
      specification_snapshot: '25×25', material_snapshot: '铁',
      calculation_snapshot: { receipt_quantity_mode: 'ROOTS' } }
    vi.mocked(api.fetchMaterialQualityBatches).mockResolvedValue([{ ...first, lines: [pipe] }] as never)
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View
    const headers = wrapper.findAll('thead th').map(cell => cell.text())
    const row = wrapper.findAll('tbody tr:first-child td')
    expect(headers).toEqual(expect.arrayContaining(['材质', '规格', '单根长度']))
    expect(['材质', '规格', '单根长度'].map(label => row[headers.indexOf(label)]?.text())).toEqual(['铁', '25×25', '3.35 米'])
    for (const invalid of ['0.1', '11']) { vm.rows[0]!.returnQuantity = invalid; expect(vm.canSubmit).toBe(false) }
    vm.rows[0]!.returnQuantity = '2'; await flushPromises()
    expect(wrapper.findAll('td.quantity-cell').map(cell => cell.text())).toEqual(['10 根', '8 根'])
    expect(vm.canSubmit).toBe(true)
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce(confirmedAction)
    await vm.confirmInbound()
    expect(api.confirmMaterialQuality).toHaveBeenCalledWith(first.id, { items: [{
      line_id: line.id, expected_received_quantity: '10', return_bar_count: '2', quality_remark: '',
    }] })
    confirm.mockRestore(); wrapper.unmount()
  })
  it('KG管材质检只显示和提交采购重量，根数由后端按剩余合格重量折算', async () => {
    const weightLine = { ...line, measurement_kind: 'PIPE', raw_bar_length_m: '3.35', received_bar_count: 2, return_bar_count: 0, source_unit_text_snapshot: 'KG', bar_weight_kg: '2.5', received_weight_kg: '4.1', return_weight_kg: '0' }
    vi.mocked(api.fetchMaterialQualityBatches).mockResolvedValue([{ ...first, lines: [weightLine] }] as never)
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View
    vm.rows[0]!.returnQuantity = '3'; await flushPromises(); expect(vm.canSubmit).toBe(true)
    expect(wrapper.find('[aria-label="第 1 项实退根数"]').exists()).toBe(false)
    const cells = wrapper.findAll('td.quantity-cell')
    expect(cells[0]!.text()).toBe('4.1 kg'); expect(cells[1]!.text()).toBe('1.1 kg')
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce(confirmedAction)
    await vm.confirmInbound()
    expect(api.confirmMaterialQuality).toHaveBeenCalledWith('batch-1', expect.objectContaining({ items: [expect.objectContaining({ return_weight_kg: '3', expected_received_quantity: '4.1' })] }))
    const submitted = vi.mocked(api.confirmMaterialQuality).mock.calls[0]![1] as { items: Record<string, unknown>[] }
    expect(submitted.items[0]).not.toHaveProperty('return_bar_count')
    confirm.mockRestore(); wrapper.unmount()
  })
  it('新采购管材部分退货后须至少剩一整根，整根边界和全退可确认', async () => {
    const pipe = { ...line, measurement_kind: 'PIPE', source_unit_text_snapshot: 'KG',
      received_bar_count: 2, bar_weight_kg: '2.5', received_weight_kg: '6', return_weight_kg: '0',
      calculation_snapshot: { receipt_root_rounding: 'FLOOR' } }
    vi.mocked(api.fetchMaterialQualityBatches).mockResolvedValue([{ ...first, lines: [pipe] }] as never)
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View
    vm.rows[0]!.returnQuantity = '3.5001'; await flushPromises()
    expect(vm.canSubmit).toBe(false)
    expect(wrapper.get('[aria-label="第 1 项退货重量"]').attributes('title')).toContain('不足一整根')
    for (const value of ['0', '3.5', '6']) {
      vm.rows[0]!.returnQuantity = value
      expect(vm.canSubmit).toBe(true)
    }
    wrapper.unmount()
  })
  it('旧米制质检草稿先从根换米，刷新保留米输入并按精确根数提交', async () => {
    const pipeLine = { ...line, measurement_kind: 'PIPE', raw_bar_length_m: '3.35', received_bar_count: 10, return_bar_count: 0, received_quantity: '33.5000', source_unit_text_snapshot: '米' }
    vi.mocked(api.fetchMaterialQualityBatches).mockResolvedValue([{ ...first, lines: [pipeLine] }] as never)
    const key = 'material-quality-draft:v2:batch-1:user:7'
    localStorage.setItem(key, JSON.stringify({ 'line-1': { returnQuantity: '2', qualityRemark: '旧草稿' } }))
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View & { saveDraft: () => void }
    expect(Number(vm.rows[0]!.returnQuantity)).toBe(6.7)
    await vm.loadBatches()
    expect(Number(vm.rows[0]!.returnQuantity)).toBe(6.7)
    vm.rows[0]!.returnQuantity = ''
    await vm.loadBatches()
    expect(vm.rows[0]!.returnQuantity).toBe('')
    expect(vm.canSubmit).toBe(false)
    vm.rows[0]!.returnQuantity = '6.7'
    vm.saveDraft()
    expect(JSON.parse(localStorage.getItem(key)!)['line-1']).toMatchObject({ quantityInputUnit: '米' })
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce(confirmedAction)
    await vm.confirmInbound()
    expect(api.confirmMaterialQuality).toHaveBeenCalledWith('batch-1', expect.objectContaining({ items: [expect.objectContaining({ return_bar_count: '2', expected_received_quantity: '33.5000' })] }))
    confirm.mockRestore(); wrapper.unmount()
  })
  it('首次和刷新复用刚读取的完整批次，保留输入且不重复读取详情', async () => {
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    expect(vm.rows).toHaveLength(1); expect(vm.canSubmit).toBe(true)
    expect(api.fetchMaterialQualityBatch).not.toHaveBeenCalled()
    vm.rows[0]!.returnQuantity = '0.1234'; vm.rows[0]!.qualityRemark = '保留内容'
    await vm.loadBatches()
    expect(vm.rows[0]).toMatchObject({ returnQuantity: '0.1234', qualityRemark: '保留内容' })
    expect(api.fetchMaterialQualityBatch).not.toHaveBeenCalled(); wrapper.unmount()
  })
  it('切换批次重新取详情，晚到响应不能覆盖新选择', async () => {
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    let finish!: (value: never) => void
    vi.mocked(api.fetchMaterialQualityBatch).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    vm.selectedBatchId = second.id; const slow = vm.selectBatch()
    vm.selectedBatchId = first.id; await vm.selectBatch(); finish(second as never); await slow
    expect(vm.batch?.id).toBe(first.id); expect(vm.rows[0]?.line.id).toBe(line.id)
    expect(api.fetchMaterialQualityBatch).toHaveBeenCalledTimes(2); wrapper.unmount()
  })
  it('失败禁止提交，刷新可恢复，空列表清除旧批次和输入', async () => {
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    vi.mocked(api.fetchMaterialQualityBatches).mockRejectedValueOnce(new Error('失败'))
    await vm.loadBatches(); expect(vm.loadError).not.toBe(''); expect(vm.loading).toBe(false); expect(vm.canSubmit).toBe(false)
    await vm.loadBatches(); expect(vm.canSubmit).toBe(true)
    vi.mocked(api.fetchMaterialQualityBatches).mockResolvedValueOnce([])
    await vm.loadBatches(); expect(vm.batch).toBeNull(); expect(vm.rows).toEqual([]); expect(vm.loading).toBe(false); expect(vm.canSubmit).toBe(false)
    wrapper.unmount()
  })
  it('历史无主质检草稿逐字隔离，新的普通草稿只写当前UID', async () => {
    const key = 'material-quality-draft:v2:batch-1'
    const raw = JSON.stringify({ 'line-1': { returnQuantity: '0.1234', qualityRemark: '历史无主内容' } })
    localStorage.setItem(key, raw)
    const wrapper = mount(); await flushPromises()
    const vm = wrapper.vm as unknown as View & { saveDraft: () => void }
    expect(vm.rows[0]?.qualityRemark).not.toBe('历史无主内容')
    vm.saveDraft()
    expect(localStorage.getItem(key)).toBe(raw)
    expect(localStorage.getItem(`${key}:user:7`)).not.toBeNull()
    wrapper.unmount()
  })
  it('草稿与刷新后的数量精度校验、已确认状态门禁保留', async () => {
    localStorage.setItem('material-quality-draft:v2:batch-1:user:7', JSON.stringify({ 'line-1': { returnQuantity: '0.1234', qualityRemark: '草稿' } }))
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    expect(vm.rows[0]).toMatchObject({ returnQuantity: '0.1234', qualityRemark: '草稿' }); expect(vm.canSubmit).toBe(true)
    for (const value of ['-1', '3.0001', '0.12345', 'x']) { vm.rows[0]!.returnQuantity = value; expect(vm.canSubmit).toBe(false) }
    vm.rows[0]!.returnQuantity = '3.0000'; expect(vm.canSubmit).toBe(true)
    vi.mocked(api.fetchMaterialQualityBatch).mockResolvedValueOnce({ ...first, status: 'CONFIRMED' } as never)
    await vm.selectBatch(); expect(vm.canSubmit).toBe(false); expect(vm.loadError).not.toBe(''); wrapper.unmount()
  })
  it('确认框等待期间切换身份，关闭确认后不得以新身份提交旧批次', async () => {
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    let accept!: (value: Awaited<ReturnType<typeof ElMessageBox.confirm>>) => void
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockReturnValueOnce(new Promise(resolve => { accept = resolve }))
    const operation = vm.confirmInbound(); await flushPromises()
    identity.user = { id: 8 }; identity.identityGeneration++; identity.identityRequestGeneration++
    accept(confirmedAction); await operation
    expect(api.confirmMaterialQuality).not.toHaveBeenCalled(); expect(router.push).not.toHaveBeenCalled()
    confirm.mockRestore(); wrapper.unmount()
  })
  it('A质检成功迟到不得删除A owned草稿、跳转或污染B', async () => {
    const key = 'material-quality-draft:v2:batch-1:user:7', raw = JSON.stringify({ 'line-1': { returnQuantity: '1', qualityRemark: 'A-original' } })
    localStorage.setItem(key, raw)
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValueOnce(confirmedAction)
    let finish!: (value: never) => void
    vi.mocked(api.confirmMaterialQuality).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const operation = vm.confirmInbound(); await flushPromises()
    identity.user = { id: 8 }; identity.identityGeneration++; identity.identityRequestGeneration++
    finish({} as never); await operation
    expect(localStorage.getItem(key)).toBe(raw); expect(router.push).not.toHaveBeenCalled()
    expect(localStorage.getItem('material-quality-draft:v2:batch-1:user:8')).toBeNull()
    confirm.mockRestore(); wrapper.unmount()
  })
  it('卸载期间回包失效，取消确认不提交', async () => {
    const wrapper = mount(); await flushPromises(); const vm = wrapper.vm as unknown as View
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValueOnce('cancel')
    await vm.confirmInbound(); expect(api.confirmMaterialQuality).not.toHaveBeenCalled(); confirm.mockRestore()
    let finish!: (value: never) => void
    vi.mocked(api.fetchMaterialQualityBatches).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    const pending = vm.loadBatches(); wrapper.unmount(); finish([] as never); await pending
    expect(vm.batch?.id).toBe(first.id)
  })
})
