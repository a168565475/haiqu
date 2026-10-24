import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElDropdownItem } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import WorkshopPlanListView from './WorkshopPlanListView.vue'

const api = vi.hoisted(() => ({ items: vi.fn(), wages: vi.fn(), push: vi.fn() }))
const state = vi.hoisted(() => ({
  route: { name: 'workshop-metalworking-plan', query: {} },
  permissions: new Set<string>(),
}))
vi.mock('@/api/productionScheduling', () => ({ fetchScheduleItems: api.items }))
vi.mock('@/api/workshopReporting', () => ({ fetchPlanWageStatuses: api.wages }))
vi.mock('vue-router', () => ({ useRoute: () => state.route, useRouter: () => ({ push: api.push }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { is_superuser: false }, hasPermission: (code: string) => state.permissions.has(code) }) }))

const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  state.route.name = 'workshop-metalworking-plan'
  state.permissions = new Set(['inventory.add_finishedgoodsreceipt', 'inventory.add_internalsemifinishedreceipt', 'inventory.view_internalsemifinishedreceipt'])
  api.wages.mockResolvedValue([])
})
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  sessionStorage.clear()
  vi.restoreAllMocks()
})

async function createPlan(status: string | undefined) {
  api.items.mockResolvedValue({ data: [{
    id: 'plan-1', schedule_id: 'schedule-1', task_number: 'HT-001', product: {}, craft_names: [],
    production_task_status: status, job_status: 'IN_PROGRESS', job_status_display: '进行中',
  }], meta: { total: 1 } })
  const wrapper = mount(WorkshopPlanListView, { global: {
    plugins: [ElementPlus], stubs: { WageSchemeDetailDialog: true },
  } })
  wrappers.push(wrapper)
  await flushPromises()
  await wrapper.findAll('button').find(button => button.text().includes('更多'))!.trigger('click')
  await flushPromises()
  return wrapper
}

describe('内部计划入库入口的订单状态', () => {
  it.each(['METAL', 'SEWING', 'ASSEMBLY'])('%s 只允许生产中任务进入入库且保持原路由参数', async category => {
    state.route.name = ({ METAL: 'workshop-metalworking-plan', SEWING: 'workshop-sewing-plan', ASSEMBLY: 'workshop-assembly-plan' } as Record<string, string>)[category]!
    const wrapper = await createPlan('IN_PRODUCTION')
    const entry = wrapper.findAllComponents(ElDropdownItem).find(item => item.text() === (category === 'ASSEMBLY' ? '成品入库' : '半成品入库'))!
    expect(entry.props('disabled')).toBe(false)
    await entry.get('[role="menuitem"]').trigger('click')
    expect(api.push).toHaveBeenCalledWith({ name: category === 'ASSEMBLY' ? 'assembly-finished-receipt' : 'internal-semi-receipt', query: {
      schedule_product_id: 'plan-1', ...(category === 'ASSEMBLY' ? {} : { plan_category: category }),
    } })
  })

  it.each(['READY', 'COMPLETED', 'PAUSED', 'CANCELLED', undefined])('任务状态 %s 即使作业显示进行中也不能新入库', async status => {
    const wrapper = await createPlan(status)
    const entry = wrapper.findAllComponents(ElDropdownItem).find(item => item.text() === '半成品入库')!
    expect(entry.props('disabled')).toBe(true)
    expect(entry.get('[role="menuitem"]').attributes('title')).toBe('仅生产中的订单可入库')
    await entry.get('[role="menuitem"]').trigger('click')
    expect(api.push).not.toHaveBeenCalled()
  })

  it('已完成装配计划禁用成品入库', async () => {
    state.route.name = 'workshop-assembly-plan'
    const wrapper = await createPlan('COMPLETED')
    const entry = wrapper.findAllComponents(ElDropdownItem).find(item => item.text() === '成品入库')!
    expect(entry.props('disabled')).toBe(true)
    await entry.get('[role="menuitem"]').trigger('click')
    expect(api.push).not.toHaveBeenCalled()
  })

  it.each(['METAL', 'SEWING', 'ASSEMBLY'])('%s 任务暂停后仍可重新进入核对已有原请求', async category => {
    state.route.name = ({ METAL: 'workshop-metalworking-plan', SEWING: 'workshop-sewing-plan', ASSEMBLY: 'workshop-assembly-plan' } as Record<string, string>)[category]!
    const key = category === 'ASSEMBLY' ? 'assembly-receipt:plan-1' : `internal-receipt-pending:plan-1:${category}`
    const saved = JSON.stringify({ etag: '"v1"', payload: { request_id: 'original-request', schedule_product_id: 'plan-1', lines: [] } })
    sessionStorage.setItem(key, saved)
    const wrapper = await createPlan('PAUSED')
    const entry = wrapper.findAllComponents(ElDropdownItem).find(item => item.text() === (category === 'ASSEMBLY' ? '成品入库' : '半成品入库'))!
    expect(entry.props('disabled')).toBe(false)
    await entry.get('[role="menuitem"]').trigger('click')
    expect(api.push).toHaveBeenCalledOnce()
    expect(sessionStorage.getItem(key)).toBe(saved)
  })

  it('会话存储不可读时保留入口交由入库页处理恢复', async () => {
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('storage unavailable') })
    const wrapper = await createPlan('PAUSED')
    const entry = wrapper.findAllComponents(ElDropdownItem).find(item => item.text() === '半成品入库')!
    expect(entry.props('disabled')).toBe(false)
    expect(warning).toHaveBeenCalledWith('无法读取待核对入库标记，请进入入库页核对。')
  })

  it.each(['workshop-metalworking-plan', 'workshop-assembly-plan'])('%s 缺少权限不显示入库入口', async routeName => {
    state.route.name = routeName
    state.permissions.clear()
    const wrapper = await createPlan('IN_PRODUCTION')
    expect(wrapper.findAllComponents(ElDropdownItem).some(item => /^(半成品|成品)入库$/.test(item.text()))).toBe(false)
  })

  it('裁剪计划继续没有半成品入库入口', async () => {
    state.route.name = 'workshop-cutting-plan'
    const wrapper = await createPlan('IN_PRODUCTION')
    expect(wrapper.findAllComponents(ElDropdownItem).some(item => /入库/.test(item.text()))).toBe(false)
  })
})

describe('内部作业计划报工记录入口', () => {
  it('四个计划共用的操作菜单包含按排产产品查看报工记录的入口', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/views/workshop/WorkshopPlanListView.vue'),
      'utf8',
    )

    expect(source).toContain("auth.hasPermission('workshop_reporting.view_workreport')")
    expect(source).toContain('if (result.data.length)')
    expect(source).toContain("if (!status && wageStatusError.value) return '加载失败'")
    expect(source).toContain('function openWorkReportRecords(row: ScheduleItem)')
    expect(source).toContain("if (!wageStatuses.value[row.id]?.workshop_id) return")
    expect(source).toContain("name: 'work-report-days'")
    expect(source).toContain('schedule_product_id: row.id')
    expect(source).toContain('craft_id: wageStatuses.value[row.id]?.craft_id')
    expect(source).toContain(':disabled="!wageStatus(row)?.workshop_id"')
    expect(source).toContain('>查看报工记录</ElDropdownItem>')
    expect(source).toContain('label="完成进度"')
    expect(source).toContain('`${status.progress_percent}%`')
    expect(source).toContain('label="预计工价"')
    expect(source).toContain('formatWageMoney(wageStatus(row)?.estimated_wage)')
  })

  it('计划表格将任务单号、排产单号、规格和颜色拆成独立列且不显示产品图片', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/views/workshop/WorkshopPlanListView.vue'),
      'utf8',
    )

    const taskColumn = source.indexOf('label="生产任务单号"')
    const scheduleColumn = source.indexOf('label="排产单号"')
    const productColumn = source.indexOf('label="产品名称"')
    const specificationColumn = source.indexOf('label="规格"')
    const colorColumn = source.indexOf('label="颜色"')
    expect(taskColumn).toBeGreaterThan(-1)
    expect(scheduleColumn).toBeGreaterThan(taskColumn)
    expect(productColumn).toBeGreaterThan(scheduleColumn)
    expect(specificationColumn).toBeGreaterThan(productColumn)
    expect(colorColumn).toBeGreaterThan(specificationColumn)
    expect(source).not.toContain('排产单号 / 生产任务单号')
    expect(source).not.toContain('<img')
  })
})
