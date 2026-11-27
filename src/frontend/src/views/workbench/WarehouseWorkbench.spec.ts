import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import type { WarehouseActivity, WarehouseCard, WarehouseDetail, WarehouseOverview, WarehouseRow } from '@/types/warehouseWorkbench'
import WarehouseWorkbench from './WarehouseWorkbench.vue'

const api = vi.hoisted(() => ({ overview: vi.fn(), items: vi.fn(), detail: vi.fn(), activity: vi.fn() }))
vi.mock('@/api/warehouseWorkbench', () => ({
  getWarehouseOverview: api.overview, getWarehouseItems: api.items, getWarehouseDetail: api.detail, getWarehouseActivity: api.activity,
}))
enableAutoUnmount(afterEach)
const task: WarehouseRow = {
  id: 'task-1', kind: 'task', task_number: 'SC-2601', product: '折叠椅', number: '', party: '金工车间', date: '2026-11-25', status: '待仓库审核', document_count: 2,
}
const issue: WarehouseRow = { ...task, id: 'issue-1', kind: 'issue', number: 'LL260101' }
const order: WarehouseRow = { ...task, id: 'out-7', kind: 'outsourcing', number: 'WF261103003', party: '车缝厂', status: '部分回货' }
const rowMeta = (total: number) => ({ total, page_size: 20, total_pages: Math.ceil(total / 20), page: 1 })
const card = (count: number, preview: WarehouseRow | null, breakdown: WarehouseCard['breakdown'] = {}): WarehouseCard => ({ count, preview, breakdown, available: true })
const overview: WarehouseOverview = {
  as_of: '2026-11-26', queues: {
    inbound: card(1, null, { semi: 0, finished: 1 }), purchase: card(0, null, { partial: 0 }),
    issue: card(1, task, { documents: 2 }), dispatch: card(1, order, { partial: 1 }), returns: card(1, order, { overdue: 1, today: 0 }),
  }, priority: [{ ...order, queue: 'returns' }],
}
const activity: WarehouseActivity = {
  start_date: '2026-11-01', end_date: overview.as_of, counts: { inbound: 1, purchase: 3, issue: 0, dispatch: 1, returns: 2 }, records: [],
}
const returnDetail: WarehouseDetail = { row: order, lines: [{ name: '椅座面', unit: '件', required: '600', done: '260', remaining: '340', basis_label: '整单部位需求' }],
  movements: [
    { date: '2026-11-25', action: '仓库收回', number: 'RK002', description: '椅座面 260 件' },
    { date: '2026-11-22', action: '仓库发出', number: 'CK001', description: '座面上片 400 片' },
  ], related: { queue: 'dispatch', id: order.id, kind: order.kind } }

async function render() {
  const pinia = createPinia()
  const page = mount(WarehouseWorkbench, { global: { plugins: [pinia], stubs: {
    PurchaseWorkbenchMessages: true, ElPagination: true,
    AppWindowDialog: { props: ['title'], template: '<div role="dialog"><header>{{ title }}</header><slot /></div>' },
  } } })
  await flushPromises()
  return { page, auth: useAuthStore(pinia) }
}
beforeEach(() => {
  vi.resetAllMocks()
  api.overview.mockResolvedValue(overview)
  api.items.mockResolvedValue({ data: [issue], meta: rowMeta(1) })
  api.detail.mockResolvedValue(returnDetail)
  api.activity.mockResolvedValue({ data: activity, meta: rowMeta(0) })
})
describe('仓库工作台', () => {
  it('五类卡片按单和任务显示；领料先选任务，再按真实单据编号取得物料明细', async () => {
    api.items.mockResolvedValueOnce({ data: [task], meta: rowMeta(1) })
      .mockResolvedValueOnce({ data: [issue, { ...issue, id: 'issue-2', number: 'LL260102' }], meta: rowMeta(2) })
    api.detail.mockResolvedValueOnce({ row: issue, lines: [{ name: '钢圆管', unit: '根', required: '90.000', done: '0', remaining: '90' }], movements: [], related: null })
    const { page } = await render()
    expect(page.findAll('.queue-title').map(el => el.text())).toEqual(['车间交仓待入库', '采购待收货', '生产任务待发料', '外发待发出', '外发待收回'])
    expect(page.get('[data-queue=issue]').text()).toContain('1个任务')
    expect(page.get('[data-queue=issue]').text()).toContain('2 张领料单')
    await page.get('[data-queue=issue]').trigger('click'); await flushPromises()
    expect(api.items).toHaveBeenLastCalledWith('issue', undefined, 1, expect.any(AbortSignal))
    await page.get('.open-row').trigger('click'); await flushPromises()
    expect(api.items).toHaveBeenLastCalledWith('issue', task.id, 1, expect.any(AbortSignal))
    expect(page.findAll('.open-row')).toHaveLength(2)
    await page.get('.row-link').trigger('click'); await flushPromises()
    expect(api.detail).toHaveBeenLastCalledWith({ queue: 'issue', kind: 'issue', id: 'issue-1' }, expect.any(AbortSignal))
    expect(page.findAll('.warehouse-dialog tbody tr:first-child td').map(cell => cell.text())).toEqual(['钢圆管', '90 根', '0 根', '90 根'])
    await page.get('.back').trigger('click'); await flushPromises()
    expect(api.items).toHaveBeenLastCalledWith('issue', task.id, 1, expect.any(AbortSignal))
  })

  it('点优先跟进展示同一张外发单的应回、实回和仓库收发记录，可切去核对待发裁片', async () => {
    const { page } = await render()
    expect(page.get('.date-tag').text()).toBe('逾期 1 天')
    await page.get('.priority-row').trigger('click'); await flushPromises()
    const cells = page.findAll('.warehouse-dialog tbody tr:first-child td')
    expect(cells[0]!.text()).toContain('椅座面')
    expect(cells[0]!.get('small').text()).toBe('整单部位需求')
    expect(cells.slice(1).map(cell => cell.text())).toEqual(['600 件', '260 件', '340 件'])
    expect(page.get('[role=dialog]').text()).toContain('座面上片 400 片')
    await page.get('.related button').trigger('click'); await flushPromises()
    expect(api.detail).toHaveBeenLastCalledWith({ queue: 'dispatch', kind: order.kind, id: order.id }, expect.any(AbortSignal))
  })

  it('采购同单分行展示供应商、到货日期和各自计量单位', async () => {
    const po = { ...order, kind: 'purchase', number: 'CGDD-1' }
    api.items.mockResolvedValueOnce({ data: [po], meta: rowMeta(1) })
    api.detail.mockResolvedValueOnce({ row: po, related: null, movements: [], lines: [
      { name: '椅面', party: '甲厂', date: '2026-11-25', unit: '件', required: '60', done: '20', remaining: '40' },
      { name: '支撑管', party: '乙厂', date: null, unit: '根', required: '120', done: '50', remaining: '70' },
    ] })
    const { page } = await render()
    await page.get('[data-queue=purchase]').trigger('click'); await flushPromises()
    await page.get('.row-link').trigger('click'); await flushPromises()
    const rows = page.findAll('.warehouse-dialog tbody tr')
    expect(rows[0]!.get('small').text()).toBe('甲厂 · 预计到货 2026-11-25')
    expect(rows[1]!.get('small').text()).toBe('乙厂')
    expect(rows.map(row => row.get('td:last-child').text())).toEqual(['40 件', '70 根'])
  })

  it('按期间查询汇总，点外发收回只查所选期间和业务的收发记录', async () => {
    const { page } = await render()
    expect(page.get('.warehouse-activity footer').text()).toContain('已办收发 7 笔')
    await page.get('.period-switch button:last-child').trigger('click'); await flushPromises()
    expect(api.activity).toHaveBeenLastCalledWith('year', 'all', 1, expect.any(AbortSignal), true)
    api.activity.mockResolvedValueOnce({ data: { ...activity, records: [{ ...order, queue: 'returns', description: '椅座面 260 件' }] }, meta: rowMeta(1) })
    await page.get('[data-activity=returns]').trigger('click'); await flushPromises()
    expect(api.activity).toHaveBeenLastCalledWith('year', 'returns', 1, expect.any(AbortSignal))
    expect(page.get('[role=dialog]').text()).toContain('本年外发收回记录')
    expect(page.get('[role=dialog]').text()).toContain('椅座面 260 件')
  })

  it('无权限显示原因；零张可点开空列表；切换身份清除前一账号的弹窗与迟到响应', async () => {
    api.overview.mockResolvedValueOnce({ ...overview, queues: { ...overview.queues, inbound: { count: null, available: false, breakdown: {}, preview: null } } })
    api.items.mockResolvedValueOnce({ data: [], meta: rowMeta(0) })
    const { page, auth } = await render()
    expect(page.get<HTMLButtonElement>('[data-queue=inbound]').element.disabled).toBe(true)
    expect(page.get('[data-queue=inbound]').text()).toContain('无查看权限')
    await page.get('[data-queue=purchase]').trigger('click'); await flushPromises()
    expect(page.get('[role=dialog]').text()).toContain('当前没有待处理的单据')
    let old!: (value: WarehouseOverview) => void
    api.overview.mockImplementationOnce(() => new Promise<WarehouseOverview>(resolve => { old = resolve }))
    auth.identityGeneration++; await flushPromises()
    expect(page.find('[role=dialog]').exists()).toBe(false)
    const signal = api.overview.mock.lastCall![0] as AbortSignal
    auth.identityGeneration++; await flushPromises()
    old({ ...overview, priority: [] }); await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(page.find('.priority-row').exists()).toBe(true)
  })
})
