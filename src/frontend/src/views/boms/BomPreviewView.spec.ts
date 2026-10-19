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
