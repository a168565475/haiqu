import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '@/api/inventory'
import * as sources from '@/api/inventoryMaterialSources'
import type { MaterialTransferLineRecord, MaterialTransferRecord } from '@/types/inventory'
import type { MaterialSelectionSnapshot } from '@/types/materialCatalog'
import MaterialTransferRecordsView from './MaterialTransferRecordsView.vue'

const identity = vi.hoisted(() => ({
  user: { is_superuser: false }, canReadAccessDirectory: false, permissions: [] as string[],
  hasPermission(code: string) { return this.permissions.includes(code) },
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => identity }))
vi.mock('@/api/inventory', () => ({ fetchMaterialTransfers: vi.fn() }))
vi.mock('@/api/inventoryMaterialSources', () => ({
  fetchInboundMaterialOptions: vi.fn(), fetchInboundMaterial: vi.fn(), fetchInboundPublicOptions: vi.fn(),
}))
const wrappers: ReturnType<typeof mount>[] = []

function snapshot(overrides: Partial<MaterialSelectionSnapshot> = {}): MaterialSelectionSnapshot {
  return {
    schema_version: 1, catalog_id: 'catalog', catalog_version: 'saved-v1', category_key: 'HARDWARE',
    template_key: 'HARDWARE', name: '螺丝', scope: 'BASE', processing_state: 'RAW', processing_stage: 'RAW',
    attributes: { specification: 'M8' }, unit_id: 'kg', unit_name: 'KG', display_name: '螺丝 M8', ...overrides,
  }
}
function line(overrides: Partial<MaterialTransferLineRecord> = {}): MaterialTransferLineRecord {
  return {
    line_key: 'line-1', material_catalog_id: 'catalog', material_selection_snapshot: snapshot(), quantity: '2.5000',
    raw_bar_length_m: null, weight_quantity: null, zone_id: 'zone', direction: 'IN', catalog_name: '螺丝',
    unit_name: 'KG', zone_name: '一区', warehouse_name: '五金仓', ...overrides,
  }
}
function record(lines: MaterialTransferLineRecord[], overrides: Partial<MaterialTransferRecord> = {}): MaterialTransferRecord {
  return { id: 'transfer-1', transfer_number: 'TF261112001', direction: 'IN', direction_display: '入库',
    transfer_date: '2026-11-12', remark: '盘点差异', operated_by_name: '仓管', created_at: '2026-11-12T08:00:00Z', lines, ...overrides }
}
async function render() {
  const wrapper = mount(MaterialTransferRecordsView, { global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
function cells(wrapper: ReturnType<typeof mount>, rowIndex: number) {
  const headers = wrapper.findAll('th').map(item => item.text())
  const row = wrapper.findAll('tbody tr')[rowIndex]!
  return Object.fromEntries(row.findAll('td').map((cell, index) => [headers[index]!, cell.text()]))
}
beforeEach(() => {
  vi.resetAllMocks()
  identity.permissions = ['inventory.view_material_receipt']
  vi.mocked(api.fetchMaterialTransfers).mockResolvedValue([])
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('收发记录按保存快照逐行显示（模拟接口）', () => {
  it('同一单据多条同名材料各占一行，规格、仓库、库区、数量和单位独立列', async () => {
    vi.mocked(api.fetchMaterialTransfers).mockResolvedValue([record([
      line({ catalog_name: '主档后来改名', material_selection_snapshot: snapshot({ name: '保存时螺丝', attributes: { specification: 'M8', future_field: '历史扩展值' } }) }),
      line({ line_key: 'line-2', quantity: '3.7500', warehouse_name: '备料仓', zone_name: '二区',
        material_selection_snapshot: snapshot({ name: '保存时螺丝', attributes: { specification: 'M10' } }) }),
    ])])
    const wrapper = await render()
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(cells(wrapper, 0)).toMatchObject({ 单号: 'TF261112001', 品名: '保存时螺丝', 规格描述: 'M8', 数量: '2.5', 单位: 'KG', 仓库: '五金仓', 库区: '一区', future_field: '历史扩展值' })
    expect(cells(wrapper, 1)).toMatchObject({ 单号: 'TF261112001', 品名: '保存时螺丝', 规格描述: 'M10', 数量: '3.75', 单位: 'KG', 仓库: '备料仓', 库区: '二区', future_field: '—' })
    expect(wrapper.text()).not.toContain('主档后来改名')
    expect(wrapper.findAll('th').map(item => item.text())).not.toContain('明细')
  })

  it('管材显示根数和原长，旧管材实重不展示，普通KG物料保留自己的单位', async () => {
    const tube = snapshot({ category_key: 'TUBE', template_key: 'TUBE', name: '方管', unit_id: 'root', unit_name: '根', attributes: { shape: '方管', section_size: '25×25' } })
    vi.mocked(api.fetchMaterialTransfers).mockResolvedValue([record([
      line({ material_selection_snapshot: tube, quantity: '2.0000', raw_bar_length_m: '6.0000', weight_quantity: '7.2512' }),
      line({ line_key: 'line-2', material_selection_snapshot: tube, quantity: '3.0000', raw_bar_length_m: '6.0000', weight_quantity: null }),
      line({ line_key: 'line-3', quantity: '4.2500' }),
    ], { direction: 'OUT', direction_display: '出库' })])
    const wrapper = await render()
    expect(cells(wrapper, 0)).toMatchObject({ 方向: '出库', 数量: '2', 单位: '根', '单根原长（m）': '6' })
    expect(cells(wrapper, 1)).toMatchObject({ 数量: '3', 单位: '根' })
    expect(wrapper.text()).not.toMatch(/实际重量|重量待核对|7\.2512/)
    expect(cells(wrapper, 2)).toMatchObject({ 数量: '4.25', 单位: 'KG', '单根原长（m）': '—', 截面形状: '—' })
  })

  it('只有记录权限也能看完整面料色卡色号颜色，不请求当前目录或候选', async () => {
    const fabric = snapshot({ category_key: 'FABRIC', template_key: 'FABRIC', name: '牛津布', attributes: { material: '涤纶', color: '历史显示值' }, color_name: '红', color_card: 'A卡', color_code: '01', product_color_id: 'color-a' })
    vi.mocked(api.fetchMaterialTransfers).mockResolvedValue([record([
      line({ material_selection_snapshot: fabric }),
      line({ line_key: 'line-2', material_selection_snapshot: { ...fabric, color_card: 'B卡', color_code: '02', product_color_id: 'color-b' } }),
    ])])
    const wrapper = await render()
    expect(identity.hasPermission('inventory.receive_material')).toBe(false)
    expect(cells(wrapper, 0)).toMatchObject({ 材质: '涤纶', 颜色: '红', 色卡: 'A卡', 色号: '01' })
    expect(cells(wrapper, 1)).toMatchObject({ 颜色: '红', 色卡: 'B卡', 色号: '02' })
    expect(sources.fetchInboundMaterialOptions).not.toHaveBeenCalled()
    expect(sources.fetchInboundMaterial).not.toHaveBeenCalled()
    expect(sources.fetchInboundPublicOptions).not.toHaveBeenCalled()
  })

  it('读取中与空记录各有明确状态，保留共享表框并且不出现弹窗或分页', async () => {
    let resolve!: (value: MaterialTransferRecord[]) => void
    vi.mocked(api.fetchMaterialTransfers).mockReturnValueOnce(new Promise(done => { resolve = done }))
    const wrapper = await render()
    expect(wrapper.get('.empty-cell').text()).toBe('正在加载…')
    resolve([]); await flushPromises()
    expect(wrapper.get('.empty-cell').text()).toBe('暂无材料收发记录')
    expect(wrapper.get('.empty-cell').attributes('colspan')).toBe('10')
    expect(wrapper.find('.erp-list-filter .erp-list-heading').exists()).toBe(true)
    expect(wrapper.find('.erp-list-table-frame .erp-list-native-table').exists()).toBe(true)
    expect(wrapper.find('.el-dialog, .el-pagination').exists()).toBe(false)
  })

  it('加载失败不能冒充空数据，刷新成功后清除错误', async () => {
    vi.mocked(api.fetchMaterialTransfers).mockRejectedValueOnce(new Error('服务不可用'))
    const wrapper = await render()
    expect(wrapper.get('.empty-cell').text()).toBe('收发记录加载失败，请刷新重试。')
    vi.mocked(api.fetchMaterialTransfers).mockResolvedValueOnce([record([line()])])
    await wrapper.get('button').trigger('click'); await flushPromises()
    expect(wrapper.find('.empty-cell').exists()).toBe(false)
    expect(cells(wrapper, 0).品名).toBe('螺丝')
  })

  it('无记录权限时只显示无权提示，不读取记录或渲染表格', async () => {
    identity.permissions = []
    const wrapper = await render()
    expect(wrapper.text()).toContain('无权查看收发记录')
    expect(api.fetchMaterialTransfers).not.toHaveBeenCalled()
    expect(wrapper.find('table').exists()).toBe(false)
  })
})
