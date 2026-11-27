import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import type { DirectorActivity, DirectorJob, DirectorOverview, DirectorPage, DirectorRecord } from '@/types/workshopDirectorWorkbench'
import WorkshopDirectorWorkbench from './WorkshopDirectorWorkbench.vue'

const api = vi.hoisted(() => ({ overview: vi.fn(), items: vi.fn(), detail: vi.fn(), activity: vi.fn() }))
vi.mock('@/api/workshopDirectorWorkbench', () => ({
  getDirectorOverview: api.overview, getDirectorItems: api.items, getDirectorDetail: api.detail, getDirectorActivity: api.activity,
}))
enableAutoUnmount(afterEach)
const job: DirectorJob = {
  id: 'plan1', task_id: 'task1', task_number: 'SC-101', schedule_number: 'PC-201', product_name: '折叠椅', craft_name: '金工', category: 'METAL',
  stage: 'working', due_date: '2026-11-25', days_remaining: -1, latest_date: '2026-11-26', latest_operation: '弯管',
  quantity: { target: '90', done: '60', remaining: '30', unit: '支', reason: '' },
}
const overview: DirectorOverview = {
  as_of: '2026-11-26', workshop: 'METAL', workshops: ['METAL'], counts: { working: 4, late: 1, today: 1, planned: 2 },
  upcoming: ['11-26', '11-27', '11-28', '11-29', '11-30', '12-01', '12-02'].map((d, i) => ({ date: '2026-' + d, count: i < 2 ? 1 : 0 })),
  jobs: [job, { ...job, id: 'plan2', days_remaining: 0 }, { ...job, id: 'plan3', days_remaining: 2 }],
}
const record: DirectorRecord = {
  id: 'line1', date: '2026-11-26', number: 'BG-301', task_number: 'SC-101', product_name: '折叠椅', name: '弯管', quantity: '20', unit: '支', job_id: 'plan1',
}
const activity: DirectorActivity = {
  available: true, start_date: '2026-11-01', end_date: '2026-11-26', record_count: 3, task_count: 2, day_count: 1,
  quantities: [{ unit: '支', quantity: '60' }], records: [record],
}
const meta = { total: 1, page: 1, page_size: 20, total_pages: 1 }
const result = <T,>(data: T): DirectorPage<T> => ({ data, meta })
async function render() {
  const pinia = createPinia()
  const page = mount(WorkshopDirectorWorkbench, { global: { plugins: [pinia], stubs: {
    PurchaseWorkbenchMessages: true, ElPagination: true,
    AppWindowDialog: { props: ['title'], template: '<div role="dialog"><header>{{ title }}</header><slot /></div>' },
  } } })
  await flushPromises()
  return { page, auth: useAuthStore(pinia) }
}
beforeEach(() => {
  vi.resetAllMocks()
  api.overview.mockResolvedValue(overview)
  api.items.mockResolvedValue(result([job]))
  api.activity.mockResolvedValue(result(activity))
  api.detail.mockResolvedValue({ job, operations: [{ name: '弯管', ...job.quantity }], reports: [record], receipts: null })
})

describe('车间主管工作台', () => {
  it('单岗直接看自己车间的产品和排产倒计时，按任务号打开工序、报工记录', async () => {
    const { page } = await render()
    expect(page.find('select').exists()).toBe(false)
    expect(page.get('.current-workshop').text()).toBe('金工车间')
    expect(page.findAll('.deadline > b').map(el => el.text())).toEqual(['已超 1 天', '今天到期', '还剩 2 天'])
    expect(page.get('.job-card').text()).toContain('今日报工 · 弯管')
    expect(page.get('.job-card').text()).toContain('该工序还差 30 支')
    await page.get('.job-card').trigger('click')
    await flushPromises()
    expect(api.detail).toHaveBeenLastCalledWith('METAL', 'plan1', expect.any(AbortSignal))
    const dialog = page.get('[role=dialog]')
    expect(dialog.text()).toContain('PC-201')
    expect(dialog.text()).toContain('工序进度')
    expect(dialog.text()).toContain('BG-301')
  })

  it('选日期查看当天排程，点待办进相应清单，再点任务并返回', async () => {
    const { page } = await render()
    await page.findAll('.day-selector button')[1]!.trigger('click')
    await flushPromises()
    expect(api.items).toHaveBeenLastCalledWith('METAL', 'day', '2026-11-27', 1, expect.any(AbortSignal), 2)
    await page.findAll('.follow-row')[2]!.trigger('click')
    await flushPromises()
    expect(api.items).toHaveBeenLastCalledWith('METAL', 'planned', undefined, 1, expect.any(AbortSignal))
    await page.get('[role=dialog] td button').trigger('click')
    await flushPromises()
    expect(page.get('[role=dialog]').text()).toContain('报工记录')
    await page.get('[role=dialog] .back').trigger('click')
    await flushPromises()
    expect(page.get('[role=dialog] th').text()).toBe('生产任务单号')
  })

  it('工序缺少要求数量时仍展示真实已报产量和单位', async () => {
    api.overview.mockResolvedValue({ ...overview, jobs: [{ ...job, quantity: {
      target: null, remaining: null, done: '60', unit: '支', reason: '缺少当前有效的工序要求数量',
    } }] })
    const { page } = await render()
    const card = page.get('.job-card')
    expect(card.get('.meter-head').text()).toContain('该工序已报60 支')
    expect(card.get('.quantity-note').text()).toBe('缺少当前有效的工序要求数量')
    expect(card.find('.meter').exists()).toBe(false)
  })

  it('装配汇总按单位分开，切本季后下钻到该期间的入库记录', async () => {
    api.overview.mockResolvedValue({ ...overview, workshop: 'ASSEMBLY', workshops: ['ASSEMBLY'] })
    api.activity.mockResolvedValue(result({ ...activity, quantities: [{ unit: '件', quantity: '1200' }, { unit: '套', quantity: '20' }] }))
    const { page } = await render()
    expect(page.findAll('.kpi-values strong').map(el => el.text())).toEqual(['1,200件', '20套'])
    expect(page.get('.director-activity h2').text()).toBe('装配入库汇总')
    await page.findAll('.period-switch button')[1]!.trigger('click')
    await flushPromises()
    await page.get('.director-activity .board-foot button').trigger('click')
    await flushPromises()
    expect(api.activity).toHaveBeenLastCalledWith('ASSEMBLY', 'quarter', 1, expect.any(AbortSignal))
    expect(page.get('[role=dialog] header').text()).toBe('本季装配入库记录')
    await page.get('[role=dialog] td button').trigger('click')
    await flushPromises()
    expect(api.detail).toHaveBeenLastCalledWith('ASSEMBLY', 'plan1', expect.any(AbortSignal))
  })

  it('按服务端可见车间切换，切换账号后重新按本人岗位加载，不保留前一车间', async () => {
    api.overview.mockResolvedValueOnce({ ...overview, workshops: ['METAL', 'SEWING'] }).mockResolvedValueOnce({ ...overview, workshop: 'SEWING', workshops: ['METAL', 'SEWING'] })
    const { page, auth } = await render()
    expect(page.findAll('select option').map(option => option.text())).toEqual(['金工车间', '车缝车间'])
    await page.get('select').setValue('SEWING')
    await flushPromises()
    expect(api.overview).toHaveBeenLastCalledWith('SEWING', expect.any(AbortSignal))
    expect(page.get('.director-activity h2').text()).toBe('车缝报工汇总')
    auth.identityGeneration++
    await flushPromises()
    expect(api.overview).toHaveBeenLastCalledWith(undefined, expect.any(AbortSignal))
    expect(page.find('select').exists()).toBe(false)
  })

  it('缺少报工权限显示原因，查汇总失败可单独重试，空排程保持可读', async () => {
    api.overview.mockResolvedValue({ ...overview, counts: { working: null, planned: null, late: null, today: null }, jobs: [], upcoming: overview.upcoming.map(day => ({ ...day, count: 0 })) })
    api.activity.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(result({ ...activity, available: false }))
    const { page } = await render()
    expect(page.find('.job-card').exists()).toBe(false)
    expect(page.get('.empty-jobs').text()).toContain('无法查看')
    expect(page.findAll('.follow-row').every(b => b.attributes('disabled') !== undefined)).toBe(true)
    expect(page.get('.director-calendar .empty').text()).toContain('当天没有')
    expect(api.items).not.toHaveBeenCalled()
    await page.get('.director-activity [role=alert] button').trigger('click')
    await flushPromises()
    expect(page.get('.director-activity .empty').text()).toContain('没有查看报工记录的权限')
    expect(page.find('.kpi-values').exists()).toBe(false)
  })
})
