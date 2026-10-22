import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElSelect, ElTable } from 'element-plus'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Lookup from './SampleInventoryLookup.vue'
import { fetchSampleInventoryCandidates } from '@/api/sampleWarehouse'

vi.mock('@/api/sampleWarehouse', () => ({ fetchSampleInventoryCandidates: vi.fn() }))
const candidate = { balanceId: 'stock-1', stockMode: 'PUBLIC_V2' as const, materialNumber: 'M01', warehouseName: '原料管材仓', zoneName: '一楼', availableQuantity: '2.0000', unitLabel: '根', rawBarLengthM: '6.00', meterQuantity: '12.00' }
const line = { key: 'demand-1', category: 'tube' as const, rawMaterialId: 'raw-1', name: '铁管', specification: '20*28*0.8*6140', material: '铁', color: '/', quantity: '12', unitId: '', unitLabel: '米', notes: '', supplyQuantity: '', inventoryAllocations: [] }
const wrappers: ReturnType<typeof mount>[] = []
async function render() {
  const wrapper = mount(Lookup, { props: { modelValue: true, sampleId: 'sample-1', activeLineKey: '', lines: [line] }, global: { plugins: [ElementPlus], stubs: { AppWindowDialog: { template: '<div><slot /><slot name="footer" /></div>' } } } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
const apply = async (wrapper: Awaited<ReturnType<typeof render>>) => { await wrapper.findAll('button').find(button => button.text() === '应用关联')!.trigger('click'); await flushPromises() }
beforeEach(() => { vi.clearAllMocks(); vi.mocked(fetchSampleInventoryCandidates).mockResolvedValue({ lines: [{ lineKey: line.key, candidates: [candidate] }] }) })
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))
it('按本单需求加载，勾选根数按库存单根长度回填关联及米数', async () => {
  const wrapper = await render()
  expect(fetchSampleInventoryCandidates).toHaveBeenCalledExactlyOnceWith('sample-1')
  const input = wrapper.get('input[aria-label="供料数量 20*28*0.8*6140 一楼"]')
  expect(input.attributes('disabled')).toBeDefined()
  await wrapper.get('input[type="checkbox"]').setValue(true)
  await input.setValue('2')
  await apply(wrapper)
  expect(wrapper.emitted('apply')?.[0]?.[0]).toEqual([expect.objectContaining({ supplyQuantity: '12', inventoryAllocations: [expect.objectContaining({ balanceId: 'stock-1', quantity: '2', rawBarLengthM: '6.00' })] })])
  expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  expect(line.supplyQuantity).toBe('')
})
it('拦截小数根数、超需求、库存不足，取消不回写', async () => {
  const wrapper = await render()
  await wrapper.get('input[type="checkbox"]').setValue(true)
  const input = wrapper.get('input[aria-label="供料数量 20*28*0.8*6140 一楼"]')
  await input.setValue('1.5'); await apply(wrapper)
  expect(wrapper.text()).toContain('管材按整数根填写')
  await input.setValue('3'); await apply(wrapper)
  expect(wrapper.text()).toContain('不能超过需求数量')
  await wrapper.setProps({ lines: [{ ...line, quantity: '30' }] })
  await apply(wrapper); expect(wrapper.text()).toContain('供料超出可用数量')
  await wrapper.findAll('button').find(button => button.text() === '取消')!.trigger('click')
  expect(wrapper.emitted('apply')).toBeUndefined()
})
it('相同库存跨需求重复勾选时累计校验', async () => {
  const wrapper = await render()
  await wrapper.setProps({ modelValue: false })
  vi.mocked(fetchSampleInventoryCandidates).mockResolvedValue({ lines: [{ lineKey: line.key, candidates: [candidate] }, { lineKey: 'demand-2', candidates: [candidate] }] })
  await wrapper.setProps({ modelValue: true, lines: [line, { ...line, key: 'demand-2' }] }); await flushPromises()
  for (const box of wrapper.findAll('input[type="checkbox"]')) await box.setValue(true)
  for (const input of wrapper.findAll('input[aria-label^="供料数量"]')) await input.setValue('2')
  await apply(wrapper)
  expect(wrapper.text()).toContain('供料超出可用数量'); expect(wrapper.emitted('apply')).toBeUndefined()
})
it('单项查询应用不会把其他未核对需求默认为零', async () => {
  const wrapper = await render()
  await wrapper.setProps({ modelValue: false })
  await wrapper.setProps({ modelValue: true, activeLineKey: line.key, lines: [line, { ...line, key: 'untouched' }] }); await flushPromises()
  await wrapper.get('input[type="checkbox"]').setValue(true)
  await wrapper.get('input[aria-label^="供料数量"]').setValue('2')
  await apply(wrapper)
  expect(wrapper.emitted('apply')?.[0]?.[0]).toEqual([
    expect.objectContaining({ key: line.key, supplyQuantity: '12' }),
    expect.objectContaining({ key: 'untouched', supplyQuantity: '' }),
  ])
})
it('失败可重试，空库存可明确应用零供料', async () => {
  vi.mocked(fetchSampleInventoryCandidates).mockRejectedValueOnce(new Error('403'))
  const wrapper = await render()
  expect(wrapper.text()).toContain('查询失败或没有核对权限')
  vi.mocked(fetchSampleInventoryCandidates).mockResolvedValue({ lines: [{ lineKey: line.key, candidates: [] }] })
  await wrapper.findAll('button').find(button => button.text() === '重新查询')!.trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain('暂无库存')
  const row = wrapper.get('.el-table__body tbody tr')
  expect(row.text()).toContain(line.name)
  expect(row.text()).toContain(line.specification)
  expect(row.text()).toContain('12 米')
  const headers = wrapper.findAll('.el-table__header th').map(cell => cell.text())
  const cells = row.findAll('td')
  expect(cells[headers.indexOf('可用库存')]!.text()).toMatch(/^0(?:\s|根|米|$)/)
  expect(row.get('input[type="checkbox"]').attributes('disabled')).toBeDefined()
  await apply(wrapper)
  expect(wrapper.emitted('apply')?.[0]?.[0]).toEqual([expect.objectContaining({ supplyQuantity: '0', inventoryAllocations: [] })])
})
it('关闭后迟到响应不覆盖重新打开的结果', async () => {
  let resolve!: (value: never) => void
  vi.mocked(fetchSampleInventoryCandidates).mockReturnValueOnce(new Promise(done => { resolve = done }))
  const wrapper = await render()
  await wrapper.setProps({ modelValue: false }); await wrapper.setProps({ modelValue: true }); await flushPromises()
  resolve({ lines: [{ lineKey: line.key, candidates: [{ ...candidate, warehouseName: '旧结果' }] }] } as never); await flushPromises()
  expect(wrapper.text()).toContain('原料管材仓'); expect(wrapper.text()).not.toContain('旧结果')
})
it('多项需求和多个库存来源在一张表内展示，属性各占一列且没有筛选下拉', async () => {
  const wrapper = await render()
  await wrapper.setProps({ modelValue: false })
  const otherLine = { ...line, key: 'demand-2', specification: '20*28*0.8*6420', material: '不锈钢', color: '银色' }
  vi.mocked(fetchSampleInventoryCandidates).mockResolvedValue({ lines: [
    { lineKey: line.key, candidates: [candidate, { ...candidate, balanceId: 'stock-2', zoneName: '二楼' }] },
    { lineKey: otherLine.key, candidates: [{ ...candidate, balanceId: 'stock-3', materialNumber: 'M02' }] },
  ] })
  await wrapper.setProps({ modelValue: true, lines: [line, otherLine] }); await flushPromises()
  expect(wrapper.findAllComponents(ElTable)).toHaveLength(1)
  expect(wrapper.findComponent(ElSelect).exists()).toBe(false)
  const headers = wrapper.findAll('.el-table__header th').map(cell => cell.text())
  for (const label of ['材料名称', '品号', '规格', '材质', '颜色', '材料仓', '库区', '可用库存', '单根长度', '库存米数', '需求数量', '本次供料', '供料米数']) {
    expect(headers).toContain(label)
  }
  const rows = wrapper.findAll('.el-table__body tbody tr')
  expect(rows).toHaveLength(3)
  expect(rows.map(row => row.findAll('td')[headers.indexOf('规格')]!.text())).toEqual([line.specification, line.specification, otherLine.specification])
  expect(rows[2]!.findAll('td')[headers.indexOf('材质')]!.text()).toBe('不锈钢')
  expect(rows[2]!.findAll('td')[headers.indexOf('颜色')]!.text()).toBe('银色')
  await rows[1]!.get('input[type="checkbox"]').setValue(true)
  await rows[1]!.get('input[aria-label^="供料数量"]').setValue('1')
  await apply(wrapper)
  expect(wrapper.emitted('apply')?.[0]?.[0]).toEqual([
    expect.objectContaining({ key: line.key, supplyQuantity: '6', inventoryAllocations: [expect.objectContaining({ balanceId: 'stock-2', quantity: '1' })] }),
    expect.objectContaining({ key: otherLine.key, supplyQuantity: '0', inventoryAllocations: [] }),
  ])
})
