import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import type { AuthUser } from '@/types/auth'
import type { SampleListItem, SampleListResult } from '@/types/sample'
import type { Paginated, WageScheme } from '@/types/workshopReporting'
import ProductionOverviewTodo from './ProductionOverviewTodo.vue'

const { fetchSamples, fetchWages } = vi.hoisted(() => ({ fetchSamples: vi.fn(), fetchWages: vi.fn() }))
vi.mock('@/api/samples', () => ({ fetchSamples }))
vi.mock('@/api/workshopReporting', () => ({ fetchWageSchemes: fetchWages }))

const permissions = ['samples.view_samplerequest', 'samples.review_sample_application', 'workshop_reporting.view_wagescheme']
function user(grants = permissions): AuthUser {
  return { id: 1, username: 'director', display_name: '厂长', is_superuser: false,
    employee: { id: 'employee-1', employee_code: 'E001', display_name: '厂长', status: 'ACTIVE' },
    permissions: [...grants], data_scope: 'ALL' }
}
function sample(id: string, allowed = true): SampleListItem {
  return { id, request_number: `打样-${id}`, status: 'DIRECTOR_REVIEW', customer_name: '客户名称',
    item_summary: { text: '待确认样品', count: 1 }, sample_due_date: '2026-10-28',
    application_actions: { is_application: true, can_director_review: allowed, can_resubmit: false },
  } as SampleListItem
}
function sampleResult(rows = [sample('允许'), sample('不允许', false)], total = 30): SampleListResult {
  return { data: rows, meta: { page: 1, page_size: 5, total, total_pages: Math.ceil(total / 5) } }
}
function wageResult(): Paginated<WageScheme> {
  return { data: [{ id: 'wage-1', scheme_number: '工价-待批', status: 'PENDING_APPROVAL',
    product: { name: '椅子' }, workshop: { name: '金工' }, production_task: { task_number: 'SC-001' },
  } as WageScheme], meta: { page: 1, page_size: 5, total: 12, total_pages: 3 } }
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

const wrappers: ReturnType<typeof mount>[] = []
function render(view: 'overview' | 'detail' | 'mini' = 'detail', account = user()) {
  const pinia = createPinia()
  const auth = useAuthStore(pinia)
  auth.user = account
  const wrapper = mount(ProductionOverviewTodo, {
    props: { view, refreshKey: 'first' },
    global: { plugins: [pinia], stubs: { RouterLink: RouterLinkStub } },
  })
  wrappers.push(wrapper)
  return { wrapper, auth }
}

beforeEach(() => {
  fetchSamples.mockReset().mockResolvedValue(sampleResult())
  fetchWages.mockReset().mockResolvedValue(wageResult())
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('生产总览待处理事项', () => {
  it('只显示逐行有权确认的打样，工价明确为可查看范围，链接遵循业务页支持的参数', async () => {
    const { wrapper } = render()
    expect(wrapper.get('[data-testid="todo-samples"]').attributes('data-state')).toBe('loading')
    await flushPromises()
    expect(fetchSamples).toHaveBeenCalledWith({ page: 1, page_size: 5, status: 'DIRECTOR_REVIEW', ordering: 'created_at' }, expect.any(AbortSignal))
    expect(fetchWages).toHaveBeenCalledWith({ page: 1, page_size: 5, status: 'PENDING_APPROVAL', ordering: 'created_at' }, expect.any(AbortSignal))
    const samples = wrapper.get('[data-testid="todo-samples"]')
    expect(samples.text()).toContain('本页可确认')
    expect(samples.text()).toContain('1 项')
    expect(samples.text()).toContain('已核对前 2 条')
    expect(samples.text()).toContain('其余请到列表查看')
    expect(samples.text()).not.toContain('30')
    expect(samples.text()).toContain('打样-允许')
    expect(samples.text()).not.toContain('打样-不允许')
    expect(wrapper.get('[data-testid="todo-wages"]').text()).toContain('可查看范围12 份')
    const links = wrapper.findAllComponents(RouterLinkStub).map(link => link.props('to'))
    expect(links).toContain('/samples?status=DIRECTOR_REVIEW')
    expect(links).toContain('/workshop/wage-schemes')
    expect(links).toContain('/workshop/wage-schemes/wage-1')
    expect(links).not.toContain('/workshop/wage-schemes?status=PENDING_APPROVAL')
    expect(wrapper.text()).not.toContain('待我审批')
  })

  it('只切换展示模式不会重取数据，缩略只汇报已经列出的条数', async () => {
    const { wrapper } = render('overview')
    await flushPromises()
    expect(wrapper.text()).not.toContain('工价-待批')
    expect(wrapper.find('.po-todo__note').exists()).toBe(false)
    expect(wrapper.text()).toContain('本页可确认')
    expect(wrapper.text()).toContain('可查看范围')
    await wrapper.setProps({ view: 'detail' })
    expect(wrapper.text()).toContain('工价-待批')
    expect(wrapper.find('.po-todo__note').exists()).toBe(true)
    await wrapper.setProps({ view: 'mini' })
    expect(wrapper.text()).toBe('已列 2 项')
    expect(fetchSamples).toHaveBeenCalledTimes(1)
    expect(fetchWages).toHaveBeenCalledTimes(1)
  })

  it('没有来源权限不请求数据，不把权限缺失显示成零', async () => {
    const { wrapper } = render('overview', user([]))
    await flushPromises()
    expect(fetchSamples).not.toHaveBeenCalled()
    expect(fetchWages).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="todo-samples"]').attributes('data-state')).toBe('forbidden')
    expect(wrapper.get('[data-testid="todo-wages"]').attributes('data-state')).toBe('forbidden')
    expect(wrapper.text()).not.toContain('0 项')
    expect(wrapper.text()).not.toContain('0 份')
    await wrapper.setProps({ view: 'mini' })
    expect(wrapper.text()).toBe('待查看')
  })

  it('独立处理来源失败，重试清空旧快照，403不保留敏感内容', async () => {
    fetchSamples.mockRejectedValueOnce(new Error('offline'))
    const { wrapper } = render()
    await flushPromises()
    expect(wrapper.get('[data-testid="todo-samples"]').attributes('data-state')).toBe('error')
    expect(wrapper.text()).toContain('工价-待批')
    fetchWages.mockRejectedValueOnce({ response: { status: 403 } })
    await wrapper.get('[data-testid="todo-samples"] button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('打样-允许')
    expect(wrapper.text()).not.toContain('工价-待批')
    expect(wrapper.get('[data-testid="todo-wages"]').attributes('data-state')).toBe('forbidden')
    expect(wrapper.get('[data-testid="todo-wages"]').text()).not.toContain('0 份')
  })

  it('刷新立即清除内容，旧请求迟到不得覆盖新结果', async () => {
    const { wrapper } = render()
    await flushPromises()
    const pending = deferred<SampleListResult>()
    fetchSamples.mockReturnValueOnce(pending.promise)
    await wrapper.setProps({ refreshKey: 'second' })
    expect(wrapper.text()).not.toContain('打样-允许')
    const oldSignal = fetchSamples.mock.calls.at(-1)![1] as AbortSignal
    fetchSamples.mockResolvedValueOnce(sampleResult([sample('新结果')], 1))
    await wrapper.setProps({ refreshKey: 'third' })
    await flushPromises()
    expect(oldSignal.aborted).toBe(true)
    expect(wrapper.text()).toContain('打样-新结果')
    pending.resolve(sampleResult([sample('迟到旧结果')], 1))
    await flushPromises()
    expect(wrapper.text()).not.toContain('打样-迟到旧结果')
    expect(wrapper.text()).toContain('打样-新结果')
  })

  it('撤销权限中止请求且立即清空，迟到响应无法重新显示旧内容', async () => {
    const pending = deferred<SampleListResult>()
    fetchSamples.mockReturnValueOnce(pending.promise)
    const { wrapper, auth } = render()
    await flushPromises()
    expect(wrapper.text()).toContain('工价-待批')
    const signal = fetchSamples.mock.calls[0]![1] as AbortSignal
    auth.user!.permissions = []
    await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(wrapper.text()).not.toContain('工价-待批')
    pending.resolve(sampleResult())
    await flushPromises()
    expect(wrapper.text()).not.toContain('打样-允许')
    expect(wrapper.get('[data-testid="todo-samples"]').attributes('data-state')).toBe('forbidden')
    expect(fetchSamples).toHaveBeenCalledTimes(1)
  })

  it('同一账号权限版本改变也重新请求，卸载取消未完成请求', async () => {
    const { wrapper, auth } = render()
    await flushPromises()
    const pending = deferred<SampleListResult>()
    fetchSamples.mockReturnValueOnce(pending.promise)
    auth.user!.effective_access = { active: true, is_superuser: false, roles: [], actions: {}, legacy_sources: [], version: 'new-scope' }
    await flushPromises()
    expect(fetchSamples).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).not.toContain('打样-允许')
    const signal = fetchSamples.mock.calls.at(-1)![1] as AbortSignal
    wrapper.unmount()
    expect(signal.aborted).toBe(true)
    pending.resolve(sampleResult())
    await flushPromises()
  })

  it('首页没有可确认样品时不声称所有待办完成，也不在缩略显示假零', async () => {
    fetchSamples.mockResolvedValueOnce(sampleResult([sample('不可确认', false)], 40))
    fetchWages.mockResolvedValueOnce({ data: [], meta: { page: 1, page_size: 5, total: 0, total_pages: 0 } })
    const { wrapper } = render()
    await flushPromises()
    expect(wrapper.text()).toContain('本页暂无你可确认的申请')
    expect(wrapper.text()).toContain('其余请到列表查看')
    expect(wrapper.text()).not.toContain('全部处理完')
    await wrapper.setProps({ view: 'mini' })
    expect(wrapper.text()).toBe('待查看')
  })
})
