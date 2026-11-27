import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'

import MaterialIssuePartitions from './MaterialIssuePartitions.vue'
import MaterialIssueDetailView from '@/views/workshop/material-issues/MaterialIssueDetailView.vue'
import type { MaterialRequirement } from '@/types/materialIssue'

const detailApi = vi.hoisted(() => vi.fn())
vi.mock('@/api/materialIssues', () => ({
  fetchMaterialIssue: detailApi, confirmMaterialIssue: vi.fn(), previewMaterialIssue: vi.fn(), returnMaterialIssue: vi.fn(),
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { issueId: 'issue-1' }, query: {} }), useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: null, hasPermission: () => false }) }))

const requirement = {
  requirement_id: 'semi-1', line_type: 'SEMI', unit: '支', material_name: '前脚管', specification: '管材规格',
  material_number: 'PIPE-1', color: '黑色', available_stock: '12', max_issue_quantity: '12',
  completed_craft: '喷塑', warehouse_zone: '半成品一库', required_quantity: '12',
  internal_issued_quantity: '0', outsourcing_issued_quantity: '0', order_remaining: '12',
} as MaterialRequirement
const raw = {
  ...requirement, requirement_id: 'raw-1', line_type: 'RAW', material_name: '管材原料',
  part_names: ['前脚'], internal_issued_quantity: '3', warehouse_zones: ['原料库'],
  conversion_snapshot: { kind: 'PIPE', pieces_per_bar: 6, raw_bar_length_m: '3.05', cutting_length_mm: 500 },
} as MaterialRequirement
const wrappers: ReturnType<typeof mount>[] = []
const globalOptions = { plugins: [ElementPlus], stubs: { AppWindowDialog: true } }
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.clearAllMocks() })

it('向下键按原材料、半成品顺序聚焦下一行申请数量', async () => {
  const wrapper = mount(MaterialIssuePartitions, {
    attachTo: document.body,
    props: {
      requirements: [raw, { ...raw, requirement_id: 'raw-2' }, requirement, { ...requirement, requirement_id: 'semi-2' }],
      selected: { 'raw-1': '6', 'raw-2': '12', 'semi-1': '3', 'semi-2': '4' },
      allocations: {},
      showPipeDeductionColumns: false,
    },
    global: globalOptions,
  })
  wrappers.push(wrapper)
  await flushPromises()

  const quantities = wrapper.findAll<HTMLInputElement>('.quantity-input input')
  expect(quantities).toHaveLength(4)
  quantities[0]!.element.focus()
  for (const [index, input] of quantities.entries()) {
    await input.trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement).toBe((quantities[index + 1] ?? input).element)
  }
  expect(quantities.map(input => input.element.value)).toEqual(['6', '12', '3', '4'])
})

describe('领料候选整行选择', () => {
  it.each([
    { ...raw, requirement_id: 'fabric-1', material_name: '裁剪布料', unit: '米', conversion_snapshot: undefined },
    raw,
    requirement,
  ])('点击 $material_name 的文字和单元格空白均切换选择，控件不会重复切换', async (row) => {
    const selected: Record<string, string> = {}
    const wrapper = mount(MaterialIssuePartitions, {
      attachTo: document.body,
      props: { requirements: [row], selected, allocations: {} },
      global: {
        plugins: [ElementPlus],
        stubs: { AppWindowDialog: { template: '<div data-testid="picker"><slot /><slot name="footer" /></div>' } },
      },
    })
    wrappers.push(wrapper)
    const partition = row.line_type === 'RAW' ? 'raw-partition' : 'semi-partition'
    await wrapper.get(`[data-testid="${partition}"] header button`).trigger('click')
    await flushPromises()
    const candidate = wrapper.get('.candidate-table tbody tr')
    const textCell = candidate.findAll('td')[row.line_type === 'RAW' ? 1 : 0]!

    await textCell.get('span').trigger('click')
    expect(candidate.classes()).toContain('is-picked')
    expect(selected).toEqual({})
    await textCell.trigger('click')
    expect(candidate.classes()).not.toContain('is-picked')

    if (row.line_type === 'RAW') {
      const checkbox = candidate.get('input[type="checkbox"]').element as HTMLInputElement
      checkbox.click()
      await flushPromises()
      expect(candidate.classes()).toContain('is-picked')
      checkbox.click()
    } else {
      await candidate.get('button').trigger('click')
      expect(candidate.classes()).toContain('is-picked')
      await candidate.get('button').trigger('click')
    }
    await flushPromises()
    expect(candidate.classes()).not.toContain('is-picked')
    await textCell.trigger('click')
    await wrapper.get('[data-testid="picker"] > button').trigger('click')
    expect(selected).toEqual({ [row.requirement_id]: '0' })
  })

  it('金工添加原材料只列管材，确认选择保留原单五金', async () => {
    const hardware: MaterialRequirement = {
      ...raw, requirement_id: 'hardware-1', section_code: 'HARDWARE',
      material_name: '螺丝', unit: '件', conversion_snapshot: undefined,
    }
    const selected = { [hardware.requirement_id]: '4' }
    const wrapper = mount(MaterialIssuePartitions, {
      props: { requirements: [raw, hardware], selected, allocations: {}, pipeInRoots: true },
      global: {
        plugins: [ElementPlus],
        stubs: { AppWindowDialog: { template: '<div data-testid="picker"><slot /><slot name="footer" /></div>' } },
      },
    })
    wrappers.push(wrapper)
    await wrapper.get('[data-testid="raw-partition"] header button').trigger('click')
    await flushPromises()
    const candidates = wrapper.findAll('.candidate-table tbody tr')
    expect(candidates).toHaveLength(1)
    expect(candidates[0]!.text()).toContain('管材原料')
    const headers = wrapper.findAll('.candidate-table thead th').map(cell => cell.text())
    const cells = candidates[0]!.findAll('td')
    expect(cells[headers.indexOf('原管长度')]!.text()).toBe('3.05 m')
    expect(cells[headers.indexOf('切割长度')]!.text()).toBe('500 mm')
    expect(wrapper.findAll('.candidate-table thead th.pipe-length-cell').map(cell => cell.text())).toEqual(['原管长度', '切割长度'])
    expect(wrapper.get<HTMLInputElement>('.candidate-table thead input[type="checkbox"]').element.checked).toBe(false)
    await candidates[0]!.trigger('click')
    await wrapper.get('[data-testid="picker"] > button').trigger('click')
    expect(selected).toEqual({ [hardware.requirement_id]: '4', [raw.requirement_id]: '0' })
  })

  it('已有材料取消后重新选回，确认时保留原数量和库存分配', async () => {
    const selected = { [raw.requirement_id]: '6' }
    const batches = [{ inbound_line_id: 'inbound-1', inbound_number: '入库-1', zone_name: '原料库', requested_pieces: '6', available_quantity: '2', available_meters: '6.10' }]
    const allocations = { [raw.requirement_id]: batches }
    const wrapper = mount(MaterialIssuePartitions, {
      props: { requirements: [raw], selected, allocations },
      global: {
        plugins: [ElementPlus],
        stubs: { AppWindowDialog: { template: '<div data-testid="picker"><slot /><slot name="footer" /></div>' } },
      },
    })
    wrappers.push(wrapper)
    await wrapper.get('[data-testid="raw-partition"] header button').trigger('click')
    await flushPromises()
    const candidate = wrapper.get('.candidate-table tbody tr')

    await candidate.trigger('click')
    expect(candidate.classes()).not.toContain('is-picked')
    expect(selected[raw.requirement_id]).toBe('6')
    expect(allocations[raw.requirement_id]).toBe(batches)
    await candidate.trigger('click')
    expect(candidate.classes()).toContain('is-picked')
    await wrapper.get('[data-testid="picker"] > button').trigger('click')
    expect(selected[raw.requirement_id]).toBe('6')
    expect(allocations[raw.requirement_id]).toBe(batches)
  })
})

describe('半成品按整数支领用显示', () => {
  it('半成品选择弹窗拆分工艺和库区，选中后隐藏类型与已完成工艺并拆分规格颜色库区', async () => {
    const wrapper = mount(MaterialIssuePartitions, {
      props: {
        requirements: [requirement], selected: { 'semi-1': '5' }, allocations: {},
      },
      global: {
        plugins: [ElementPlus],
        stubs: { AppWindowDialog: { template: '<div data-testid="picker"><slot /><slot name="footer" /></div>' } },
      },
    })
    wrappers.push(wrapper)
    await flushPromises()

    const semi = wrapper.get('[data-testid="semi-partition"]')
    const selectedHeaders = semi.findAll('thead th').map(cell => cell.text())
    expect(selectedHeaders).not.toContain('可用说明')
    expect(selectedHeaders.filter(Boolean).slice(-3)).toEqual(['预计结余', '申请数量', '操作'])
    for (const partition of [wrapper.get('[data-testid="raw-partition"]'), semi]) {
      expect(partition.findAll('thead th.el-table-fixed-column--right').map(cell => cell.text())).toEqual(['申请数量', '操作'])
      expect(partition.get('thead th.el-table-fixed-column--right.is-center').text()).toBe('申请数量')
    }
    expect(selectedHeaders).toContain('规格')
    expect(selectedHeaders).toContain('颜色')
    expect(selectedHeaders).toContain('库区')
    expect(selectedHeaders).not.toContain('类型 / 已完成工艺')
    expect(selectedHeaders).not.toContain('已完成工艺')
    expect(selectedHeaders).toContain('材质')
    expect(selectedHeaders).toContain('加工状态')
    expect(semi.text()).toContain('喷塑')

    await semi.get('header button').trigger('click')
    await flushPromises()
    const pickerHeaders = wrapper.get('[data-testid="picker"] .candidate-table').findAll('thead th').map(cell => cell.text())
    expect(pickerHeaders).toContain('加工状态')
    expect(pickerHeaders).not.toContain('匹配依据')
    expect(pickerHeaders).toContain('操作')
    expect(pickerHeaders).not.toContain('工艺')
    expect(wrapper.get('[data-testid="picker"]').text()).toContain('添加')
  })

  it.each(['SEMI_PIPE', 'SEMI_PIPE_PIECES', undefined])('库存十二支领取五支显示结余七支，兼容快照 %s', async (kind) => {
    const wrapper = mount(MaterialIssuePartitions, {
      props: {
        requirements: [{ ...requirement, conversion_snapshot: kind ? { kind, pieces_per_bar: 6, raw_bar_length_m: '3.05' } : undefined }],
        selected: { 'semi-1': '5' }, allocations: {},
      }, global: globalOptions,
    })
    wrappers.push(wrapper)
    await flushPromises()
    const semi = wrapper.get('[data-testid="semi-partition"]')
    expect(semi.text()).toContain('7 支')
    expect(semi.text()).not.toContain('不扣原材料根数、米数')
    expect(semi.text()).not.toContain('预计扣根')
    expect(semi.text()).not.toContain('预计扣米')
    expect(semi.text()).not.toContain('整根')
  })

  it('原材料管材主表显示库区和支、根换算，隐藏预计米数', async () => {
    const wrapper = mount(MaterialIssuePartitions, {
      props: { requirements: [raw], selected: { 'raw-1': '6' }, allocations: { 'raw-1': [
        { inbound_line_id: 'inbound-1', inbound_number: '入库-1', zone_name: '原料库', requested_pieces: '6', available_quantity: '2', available_meters: '6.10' },
      ] } }, global: globalOptions,
    })
    wrappers.push(wrapper)
    await flushPromises()
    const partition = wrapper.get('[data-testid="raw-partition"]')
    expect(partition.text()).toContain('品名')
    expect(partition.text()).toContain('部位')
    expect(partition.text()).not.toContain('品名 / 部位')
    expect(partition.text()).toContain('管材原料')
    expect(partition.text()).toContain('前脚')
    expect(partition.text()).toContain('规格')
    expect(partition.text()).toContain('颜色')
    expect(partition.text()).toContain('库区')
    expect(partition.text()).toContain('已领取')
    expect(partition.findAll('tbody td')[7]?.text()).toBe('3')
    expect(partition.text()).toContain('原料库')
    expect(partition.text()).not.toContain('按现有合格库存领用')
    expect(partition.text()).toContain('6 支')
    expect(partition.text()).toContain('1 根')
    expect(partition.text()).not.toContain('3.05 米')
    expect(partition.text()).toContain('系统按相同物料和规格的合格库存自动分配')
    expect(partition.text()).not.toContain('分配批次')
    expect(partition.find('.quota-line').exists()).toBe(false)
  })

  it('管材支数不是整根倍数时输入框变红并在下方显示规则', async () => {
    const wrapper = mount(MaterialIssuePartitions, {
      props: { requirements: [raw], selected: { 'raw-1': '5' }, allocations: {} },
      global: globalOptions,
    })
    wrappers.push(wrapper)
    await flushPromises()
    const partition = wrapper.get('[data-testid="raw-partition"]')
    expect(partition.get('.quantity-input').classes()).toContain('is-rule-error')
    expect(partition.find('.quantity-rule-bubble').exists()).toBe(false)
    expect(document.body.querySelector('.material-issue-rule-tooltip')?.textContent).toBe('申请支数必须为 6 的正整数倍（每根可切 6 支）。')
  })

  it('普通原材料超过本次可领量时定位到对应输入框并悬浮提示', async () => {
    const ordinaryRaw = {
      ...raw,
      requirement_id: 'hardware-1',
      material_name: '铆钉',
      unit: 'PCS',
      max_issue_quantity: '10',
      conversion_snapshot: undefined,
    } as MaterialRequirement
    const wrapper = mount(MaterialIssuePartitions, {
      props: { requirements: [ordinaryRaw], selected: { 'hardware-1': '11' }, allocations: {} },
      global: globalOptions,
    })
    wrappers.push(wrapper)
    await flushPromises()
    const input = wrapper.get('[data-testid="raw-partition"] .quantity-input')
    expect(input.classes()).toContain('is-rule-error')
    expect(input.get('input').attributes('aria-invalid')).toBe('true')
    expect(document.body.querySelector('.material-issue-rule-tooltip')?.textContent).toBe('申请数量超过当前可领上限。')
  })

  it('半成品非整数时定位到对应输入框并悬浮提示，空值和零不报错', async () => {
    const selected = { 'semi-1': '1.5' }
    const wrapper = mount(MaterialIssuePartitions, {
      props: { requirements: [requirement], selected, allocations: {} },
      global: globalOptions,
    })
    wrappers.push(wrapper)
    await flushPromises()
    const input = wrapper.get('[data-testid="semi-partition"] .quantity-input')
    expect(input.classes()).toContain('is-rule-error')
    expect(input.get('input').attributes('aria-invalid')).toBe('true')
    expect(document.body.querySelector('.material-issue-rule-tooltip')?.textContent).toBe('半成品支数和套数必须为正整数。')

    await wrapper.setProps({ selected: { 'semi-1': '0' } })
    await flushPromises()
    expect(wrapper.get('[data-testid="semi-partition"] .quantity-input').classes()).not.toContain('is-rule-error')

    await wrapper.setProps({ selected: { 'semi-1': '' } })
    await flushPromises()
    expect(wrapper.get('[data-testid="semi-partition"] .quantity-input').classes()).not.toContain('is-rule-error')
  })

  it('装配领料不显示管材换算三列', async () => {
    const wrapper = mount(MaterialIssuePartitions, {
      props: {
        requirements: [raw], selected: { 'raw-1': '6' }, allocations: {},
        showPipeDeductionColumns: false,
      },
      global: globalOptions,
    })
    wrappers.push(wrapper)
    await flushPromises()
    const partition = wrapper.get('[data-testid="raw-partition"]')
    expect(partition.text()).not.toContain('每根切割')
    expect(partition.text()).not.toContain('预计扣根数')
    expect(partition.text()).not.toContain('预计扣米数')
  })

  it('旧半成品详情不再把历史换算值说成实际原材料扣减', async () => {
    detailApi.mockResolvedValue({ etag: '"issue-1"', data: {
      id: 'issue-1', issue_number: '领料-1', status: 'ISSUED', status_display: '已出库', line_count: 2,
      production_task: null, product: null, workshop: null, recipient: null, created_by: { id: 'employee', name: '申请人' },
      issued_by: { id: 'reviewer', name: '审核人' }, audit_events: [],
      lines: [
        { ...raw, id: 'raw-line', requested_quantity: '6', issued_quantity: '6', bar_count: '1', meters: '3.05', batch_allocations: [
          { inbound_line_id: 'inbound-1', inbound_number: '入库-1', zone_name: '原料库', requested_pieces: '6', bar_count: '1', meters: '3.05' },
        ] },
        { ...requirement, id: 'semi-line', requested_quantity: '5', issued_quantity: '5', order_remaining: '7',
          conversion_snapshot: { kind: 'SEMI_PIPE', pieces_per_bar: 6, issued_bar_count: '99', issued_meters: '999.99' },
        },
      ],
    } })
    const wrapper = mount(MaterialIssueDetailView, { global: globalOptions })
    wrappers.push(wrapper)
    await flushPromises()
    const tables = wrapper.findAll('section.detail-table')
    expect(tables[0]!.text()).toContain('6 支 → 1 根')
    expect(tables[0]!.text()).not.toContain('3.05 米')
    expect(tables[0]!.text()).not.toContain('入库-1')
    expect(tables[0]!.text()).not.toContain('批次')
    expect(tables[1]!.text()).toContain('不扣原材料根数和米数')
    expect(tables[1]!.text()).not.toContain('扣根米')
    expect(tables[1]!.text()).not.toContain('999.99')
    expect(tables[1]!.text()).toContain('出库后结余')
  })
})
