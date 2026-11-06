import { flushPromises, shallowMount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchBom } from '@/api/boms'
import BomPreviewView from './BomPreviewView.vue'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bomId: 'bom-1' } }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: () => false }) }))
vi.mock('@/api/boms', () => ({ fetchBom: vi.fn() }))
const record = { bom_number: 'BOM-TEST', order_quantity: '100', current_order_quantity: '120', version_number: 1, sections: [
  { id: 's1', title: '塑料件类', section_type: 'ACCESSORY', lines: [{ id: 'l1', line_number: 4, part_name: '脚套', material: 'PP', plastic_material_number: 'HIDDEN-CODE', plastic_color: '黑色', specification: '20', unit: '个', unit_consumption: '2', images: [] }] },
  { id: 's2', title: '面料类', section_type: 'FABRIC', lines: [] },
] }
let wrapper: ReturnType<typeof shallowMount> | undefined
afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks() })
async function open() {
  wrapper = shallowMount(BomPreviewView, { global: { plugins: [ElementPlus], renderStubDefaultSlot: true, stubs: { ElResult: false } } })
  await flushPromises()
  return wrapper
}

describe('BOM 预览渲染', () => {
  it('裁剪无米数字段也显示订单套数和片数，预览不呈现历史耗米', async () => {
    vi.mocked(fetchBom).mockResolvedValue({ ...record, sections: [{ id: 'cutting', title: '裁剪明细', section_type: 'FABRIC', lines: [{ id: 'cut-1', part_name: '外袋', specification: '20', cutting_pieces_per_set: 2, cutting_sets_per_product: 3, unit: '套', images: [] }] }] } as never)
    const view = await open()
    expect(view.get('[data-field="order_cutting_sets"]').text()).toBe('300')
    expect(view.get('[data-field="order_cutting_pieces"]').text()).toBe('600')
    expect(view.text()).not.toMatch(/米\/片|每套耗米|订单耗米/)
  })
  it('旧BOM预览保留808根，新版本显示800根', async () => {
    const line = { id: 'pipe-1', part_name: '上下管', length_value: '500', unit_consumption: '2', tube_cut_piece_count: '5',
      cutting_length_mm: 500, pieces_per_product: 2, pieces_per_bar: 5, raw_values: {}, images: [] }
    vi.mocked(fetchBom).mockResolvedValue({ ...record, order_quantity: '2000', sections: [{ id: 'pipes', title: '管材类',
      section_type: 'PROFILE', lines: [line, { ...line, id: 'pipe-2', raw_values: { pipe_plan_version: 3 } }] }] } as never)
    const view = await open()
    expect(view.findAll('[data-field="branch_count"]').map(cell => cell.text())).toEqual(['808', '800'])
    expect(view.findAll('[data-field="total_consumption"]').map(cell => cell.text())).toEqual(['4000', '4000'])
  })

  it('导入待确认预览保留原表采购余量和长料长度，未关联销售订单时不显示任务来源编号', async () => {
    const sourceRows = [
      ['730', '2', '8', '5.89'], ['910', '4', '6', '5.51'], ['680', '3', '9', '6.17'],
      ['640', '3', '9', '5.81'], ['470', '3', '12', '5.72'], ['265', '6', '22', '5.93'],
    ]
    vi.mocked(fetchBom).mockResolvedValue({ ...record, status: 'PENDING_CONFIRMATION', order_quantity: '500', order_number: 'HT26130', source_sales_order_number: null,
      sections: [{ id: 'pipes', title: '管材类', section_type: 'PROFILE', lines: sourceRows.map(([length, consumption, cuts, rawLength], index) => ({
        id: `pipe-${index}`, part_name: '管材', length_value: length, unit_consumption: consumption, tube_cut_piece_count: cuts,
        source_purchase_allowance_percent: '1', source_raw_bar_length_m: rawLength,
        cutting_length_mm: Number(length), pieces_per_product: Number(consumption), pieces_per_bar: Number(cuts), raw_values: { pipe_plan_version: 3 }, images: [],
      })) }],
    } as never)
    const view = await open()
    expect(view.findAll('[data-field="branch_count"]').map(cell => cell.text())).toEqual(['127', '337', '169', '169', '127', '138'])
    expect(view.findAll('[data-field="tube_cut_length_m"]').map(cell => cell.text())).toEqual(['5.89', '5.51', '6.17', '5.81', '5.72', '5.93'])
    expect(view.findAll('[data-field="suggested_purchase_meters"]').map(cell => cell.text())).toEqual(['748.03', '1856.87', '1042.73', '981.89', '726.44', '818.34'])
    expect(view.get('.preview-status-tag').text()).toBe('待确认')
    expect(view.text()).toContain('销售订单未关联')
    expect(view.text()).not.toContain('销售订单HT26130')
  })

  it('已确认 BOM 显示真实关联销售订单', async () => {
    vi.mocked(fetchBom).mockResolvedValue({ ...record, status: 'VERIFIED', order_number: '任务来源编号', source_sales_order_number: 'SO-001' } as never)
    const view = await open()
    expect(view.get('.preview-status-tag').text()).toBe('已确认')
    expect(view.text()).toContain('销售订单SO-001')
  })

  it('每区按实际字段显示，序号从一开始，不输出原料编号或空数据假行', async () => {
    vi.mocked(fetchBom).mockResolvedValue(record as never)
    const view = await open()
    expect(view.findAll('th').slice(0, 9).map(item => item.text())).toEqual(['序号', '品名', '材质', '颜色', '规格', '单位', '单个用量', '备注', '图片'])
    expect(view.find('tbody td').text()).toBe('1')
    expect(view.text()).not.toContain('HIDDEN-CODE')
    expect(view.findAll('.empty-row')).toHaveLength(1)
    expect(view.findAll('.document-outline button').map(button => button.text())).toEqual(['塑料件类（1）', '面料类（0）'])
    expect(view.text()).toContain('BOM计算数量100')
    expect(view.text()).toContain('当前计划数量120')
    expect(view.findAll('bom-line-image-summary-stub')).toHaveLength(1)
  })

  it('接口失败显示错误，不伪造空数据成功；可重新加载', async () => {
    vi.mocked(fetchBom).mockRejectedValueOnce(new Error('读取失败'))
    const view = await open()
    expect(view.findComponent({ name: 'ElResult' }).props('subTitle')).toBe('读取失败')
    expect(view.find('.preview-shell').exists()).toBe(false)
    vi.mocked(fetchBom).mockResolvedValueOnce({ ...record, sections: [] } as never)
    await view.findComponent({ name: 'ElButton' }).trigger('click')
    await flushPromises()
    expect(view.find('.preview-shell').exists()).toBe(true)
    expect(view.find('table').exists()).toBe(false)
  })

  it('滚到底部时目录选中最后一个分区', async () => {
    vi.mocked(fetchBom).mockResolvedValue(record as never)
    const view = await open()
    const scroller = view.get('.paper-scroll')
    Object.defineProperties(scroller.element, { clientHeight: { value: 400 }, scrollHeight: { value: 600 }, scrollTop: { value: 200 } })
    await scroller.trigger('scroll')
    expect(view.get('.document-outline button.active').text()).toBe('面料类（0）')
  })
})
