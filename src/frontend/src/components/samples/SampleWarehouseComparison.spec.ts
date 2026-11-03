import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it } from 'vitest'
import type { SampleWarehouseLine } from '@/types/sampleWarehouse'
import SampleWarehouseComparison from './SampleWarehouseComparison.vue'

const line: SampleWarehouseLine = {
  key: 'pipe-1', category: 'tube', name: '铁管', specification: '20*20', material: '铁', color: '色卡A / B1 / 蓝色',
  quantity: '12', unitId: 'meter', unitLabel: '米', supplyQuantity: '2', notes: '',
  material_selection_snapshot: {
    schema_version: 1, catalog_id: 'catalog-1', catalog_version: 'v1', category_key: 'TUBE', template_key: 'TUBE',
    name: '铁管', display_name: '铁管', scope: 'BASE', processing_state: 'RAW', processing_stage: '原材料', unit_id: 'root', unit_name: '根',
    color_card: '色卡A', color_code: 'B1', color_name: '蓝色',
    attributes: { shape: '方管', section_size: '20*20', thickness: '2.0', material: '铁', color: '蓝色' },
  },
}
const tooltipStub = { props: ['visible'], template: '<div><slot /><div v-if="visible"><slot name="content" /></div></div>' }
let wrapper: VueWrapper | undefined
async function render(lines: SampleWarehouseLine[] = [line]) {
  wrapper = mount(SampleWarehouseComparison, { props: { modelValue: lines, available: true, fullscreen: false, errorMessage: '' },
    global: { plugins: [ElementPlus], stubs: { ElTooltip: tooltipStub } },
  })
  await flushPromises()
  return wrapper
}
afterEach(() => { wrapper?.unmount(); wrapper = undefined })

describe('样品仓库核对属性浮层（组件契约）', () => {
  it('保持十列和供料数量，整行经过显示保存的规格厚度材质与完整颜色', async () => {
    const page = await render()
    expect(page.findAll('th').map(cell => cell.text())).toEqual([
      '材料分类', '材料名称', '规格', '材质', '颜色 / 色号', '需求数量', '本次可供数量 *', '采购缺口', '单位', '核对结果',
    ])
    const row = page.get('tbody tr')
    const cells = row.findAll('td')
    expect(cells).toHaveLength(10)
    expect(cells[2]!.text()).toBe('20*20')
    expect(cells[5]!.text()).toBe('12')
    expect(cells[7]!.text()).toBe('10')
    expect((page.get('input[aria-label="铁管本次可供数量"]').element as HTMLInputElement).value).toBe('2')
    expect(page.find('.material-attribute-tooltip').exists()).toBe(false)
    await row.trigger('mouseenter')
    const attributes = page.get('.material-attribute-tooltip').findAll('div').map(field => field.text())
    expect(attributes).toEqual(expect.arrayContaining(['品名铁管', '规格20*20', '厚度2.0', '材质铁', '色卡色卡A', '色号B1', '颜色蓝色']))
    expect(attributes.filter(value => value.startsWith('颜色'))).toHaveLength(1)
    await page.get('.material-inventory-link').trigger('click')
    expect(page.emitted('lookup')).toEqual([['pipe-1']])
    expect(page.emitted('update:modelValue')).toBeUndefined()
    await row.trigger('mouseleave')
    expect(page.find('.material-attribute-tooltip').exists()).toBe(false)
  })

  it('切换行只展示当前行属性，旧行颜色保留且移出后无残留', async () => {
    const page = await render([line, { ...line, key: 'legacy-2', name: '旧管材', specification: '10*10', material: '铝', color: '米白色', material_selection_snapshot: undefined }])
    const rows = page.findAll('tbody tr')
    await rows[0]!.trigger('mouseenter')
    expect(page.get('.material-attribute-tooltip').text()).toContain('厚度2.0')
    await rows[1]!.trigger('mouseenter')
    expect(page.findAll('.material-attribute-tooltip')).toHaveLength(1)
    expect(page.get('.material-attribute-tooltip').findAll('div').map(field => field.text())).toEqual(['品名旧管材', '材质铝', '规格10*10', '颜色米白色'])
    await rows[1]!.trigger('mouseleave')
    expect(page.find('.material-attribute-tooltip').exists()).toBe(false)
  })
})
