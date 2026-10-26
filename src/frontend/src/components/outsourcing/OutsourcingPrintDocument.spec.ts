import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import type { OutsourcingPrintDocumentData } from '@/types/outsourcingPrint'
import OutsourcingPrintDocument from './OutsourcingPrintDocument.vue'

function document(overrides: Partial<OutsourcingPrintDocumentData> = {}): OutsourcingPrintDocumentData {
  return {
    kind: 'processing', title: '委外加工单', orderNumber: 'WWJG-REAL', submittedBy: '提交员工', submittedAt: '2026-10-26 08:00:00',
    updatedAt: '2026-10-26 09:00:00', craftName: '喷塑', factoryNames: '加工厂甲', preparedBy: '制单员工', preparedDate: '2026-10-26',
    deliveryDate: '2026-10-30', productName: '扶手椅', dispatchDate: '2026-10-27', remark: '真实订单备注',
    plans: [{ id: 'plan-1', completed: '否', orderNumber: 'HT-01', itemNumber: 'ITEM-01', productName: '扶手椅', plannedQuantity: '400', color: '红色', specification: '50×50×80' }],
    materials: [
      { id: 'material-1', orderNumber: 'HT-01', name: '扶手管', unitConsumption: '2', orderQuantity: '1000', issueQuantity: '60', unit: '支', specification: 'Φ22×0.8', color: '本色', material: 'Q195' },
      { id: 'material-2', orderNumber: 'HT-01', name: '螺母', unitConsumption: '—', orderQuantity: '1000', issueQuantity: '12', unit: '个', specification: 'M6', color: '镀锌', material: '碳钢' },
    ],
    sprayRows: [{ id: 'line-1', factoryName: '加工厂甲', partName: '扶手管', specification: '22', cuttingLength: '650', unitConsumption: '2', orderQuantity: '1000', totalQuantity: '60', sprayColor: '黑色亮光' }],
    ...overrides,
  }
}

describe('外发打印纸面模板', () => {
  it('加工单先列主计划和七列材料，再同序展示颜色材质，缺值不造数据', () => {
    const wrapper = mount(OutsourcingPrintDocument, { props: { document: document() } })
    try {
      expect(wrapper.get('h1').text()).toBe('委外加工单')
      expect(wrapper.get('[data-section="basic"]').text()).toContain('WWJG-REAL')
      expect(wrapper.findAll('[data-section="plans"] thead tr').at(-1)!.findAll('th')).toHaveLength(7)
      const materials = wrapper.get('[data-section="materials"]')
      expect(materials.findAll('[data-material-row]').map(row => row.findAll('td').map(cell => cell.text()))).toEqual([
        ['HT-01', '扶手管', '2', '1000', '60', '支', 'Φ22×0.8'],
        ['HT-01', '螺母', '—', '1000', '12', '个', 'M6'],
      ])
      expect(materials.findAll('[data-material-attributes]').map(row => row.findAll('td').slice(0, 2).map(cell => cell.text()))).toEqual([['本色', 'Q195'], ['镀锌', '碳钢']])
      expect(wrapper.find('[data-section="spray"]').exists()).toBe(false)
      expect(wrapper.find('button,input,select').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })

  it('喷塑规格跨两列，真实明细与固定仓库提示只出现在喷塑模板', () => {
    const wrapper = mount(OutsourcingPrintDocument, { props: { document: document({ kind: 'spray', title: 'HT-01单 嗨趣休闲用品有限公司喷塑计划' }) } })
    try {
      expect(wrapper.get('h1').text()).toBe('HT-01单 嗨趣休闲用品有限公司喷塑计划')
      const table = wrapper.get('[data-section="spray"]')
      expect(table.get('th[colspan="2"]').text()).toBe('材料规格')
      expect(table.get('[data-spray-row]').findAll('td').map(cell => cell.text())).toEqual(['加工厂甲', '扶手管', '22', '650', '2', '1000', '60', '黑色亮光'])
      expect(table.get('[data-warehouse-note]').text()).toBe('喷塑回来请注明单号，否则一律拒收。仓库电话：15284640047张')
      expect(wrapper.get('[data-field="remark"]').text()).toContain('真实订单备注')
      expect(wrapper.find('[data-section="basic"]').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })

  it('空表保留表头并明确无明细，长表不截断任何记录', async () => {
    const wrapper = mount(OutsourcingPrintDocument, { props: { document: document({ plans: [], materials: [] }) } })
    try {
      expect(wrapper.get('[data-section="plans"] tbody').text()).toContain('暂无明细')
      expect(wrapper.get('[data-section="materials"] tbody').text()).toContain('暂无明细')
      const row = document().sprayRows[0]!
      await wrapper.setProps({ document: document({ kind: 'spray', sprayRows: Array.from({ length: 80 }, (_, index) => ({ ...row, id: `row-${index}`, partName: `部件${index + 1}` })) }) })
      expect(wrapper.findAll('[data-spray-row]')).toHaveLength(80)
      expect(wrapper.findAll('[data-spray-row]').at(-1)!.text()).toContain('部件80')
    } finally { wrapper.unmount() }
  })
})
