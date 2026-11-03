import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/sampleMaterials'
import SampleMaterialProgress from './SampleMaterialProgress.vue'

vi.mock('@/api/sampleMaterials', () => ({ fetchSampleMaterials: vi.fn() }))
const line = { key: 'pipe-1', category: 'tube', name: '铁管', specification: '20*20', material: '铁', color: '蓝色',
  quantity: '12', supplyQuantity: '2', arrivedQuantity: '3', remainingQuantity: '7', issuedQuantity: '4', shortageQuantity: '8', unitLabel: '米',
  material_selection_snapshot: { schema_version: 1, name: '铁管', template_key: 'TUBE', unit_name: '根', color_card: '色卡A', color_code: 'B1',
    attributes: { shape: '方管', section_size: '20*20', thickness: '2.0', material: '铁', color: '蓝色' } },
}
const tooltipStub = { props: ['visible'], template: '<div><slot /><div v-if="visible"><slot name="content" /></div></div>' }
let wrapper: VueWrapper | undefined
async function render() {
  wrapper = mount(SampleMaterialProgress, { props: { sampleId: 'sample-1' }, global: { plugins: [ElementPlus], stubs: { ElTooltip: tooltipStub } } })
  await flushPromises()
  return wrapper
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.fetchSampleMaterials).mockResolvedValue({ available: true, progress: { status: 'PROCUREMENT_PENDING', label: '待采购', lines: [line] } } as never)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('样品用料进度属性浮层（组件契约）', () => {
  it('保持原列和数量，经过数量单元格也展示该行快照的完整属性', async () => {
    const page = await render()
    const headers = page.findAll('.el-table__header th').map(cell => cell.text())
    expect(headers).toEqual(['材料名称', '规格', '材质', '颜色 / 色卡 / 色号', '需求数量', '仓库供料', '采购已入库', '采购剩余缺口', '实际领料', '领料后缺口', '单位'])
    const cells = page.get('.el-table__body tbody tr').findAll('td')
    expect(cells.map(cell => cell.text())).toEqual(['铁管', '20*20', '铁', '蓝色', '12', '2', '3', '7', '4', '8', '米'])
    expect(page.find('.material-attribute-tooltip').exists()).toBe(false)
    await cells[4]!.trigger('mouseenter')
    const attributes = page.get('.material-attribute-tooltip').findAll('div').map(field => field.text())
    expect(attributes).toEqual(expect.arrayContaining(['品名铁管', '规格20*20', '厚度2.0', '材质铁', '色卡色卡A', '色号B1', '颜色蓝色']))
    await page.get('.el-table').trigger('mouseleave')
    expect(page.find('.material-attribute-tooltip').exists()).toBe(false)
    expect(api.fetchSampleMaterials).toHaveBeenCalledOnce()
  })

  it('切换行使用各自行快照，缺快照时只显示已有属性', async () => {
    vi.mocked(api.fetchSampleMaterials).mockResolvedValue({ available: true, progress: { status: 'PROCUREMENT_PENDING', label: '待采购', lines: [line,
      { ...line, key: 'legacy-2', specification: '10*10', material: '铝', material_selection_snapshot: undefined },
    ] } } as never)
    const page = await render()
    const rows = page.findAll('.el-table__body tbody tr')
    await rows[0]!.findAll('td')[0]!.trigger('mouseenter')
    expect(page.get('.material-attribute-tooltip').text()).toContain('厚度2.0')
    await rows[1]!.findAll('td')[0]!.trigger('mouseenter')
    expect(page.findAll('.material-attribute-tooltip')).toHaveLength(1)
    expect(page.get('.material-attribute-tooltip').text()).toContain('规格10*10')
    expect(page.get('.material-attribute-tooltip').text()).toContain('品名铁管')
    expect(page.get('.material-attribute-tooltip').text()).toContain('材质铝')
    expect(page.get('.material-attribute-tooltip').text()).not.toContain('厚度')
  })
})
