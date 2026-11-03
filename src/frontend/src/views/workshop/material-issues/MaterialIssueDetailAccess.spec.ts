import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MaterialIssueDetailView from './MaterialIssueDetailView.vue'

const state = vi.hoisted(() => ({ followed: true }))
const navigation = vi.hoisted(() => ({ push: vi.fn() }))
const api = vi.hoisted(() => ({ detail: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { issueId: 'issue-1' }, query: {} }) }))
vi.mock('@/router', () => ({ router: navigation }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => {
  const permissions = ['material_issues.view_materialissue', 'material_issues.view_metalprocessingsource', 'production_tasks.view_productiontask']
  return { user: { id: 1, is_superuser: false, effective_access: { legacy_sources: [], actions: Object.fromEntries(
    permissions.map(code => [code, { scopes: [state.followed ? 'FOLLOWED' : 'MODULE'], sources: [] }]),
  ) } }, canReadAccessDirectory: false, hasPermission: (code: string) => permissions.includes(code) }
} }))
vi.mock('@/api/materialIssues', () => ({ fetchMaterialIssue: api.detail, materialIssueProductImageUrl: () => '',
  confirmMaterialIssue: vi.fn(), previewMaterialIssue: vi.fn(), returnMaterialIssue: vi.fn() }))

const wrappers: ReturnType<typeof mount>[] = []
async function createView() {
  const wrapper = mount(MaterialIssueDetailView, { global: { plugins: [ElementPlus], stubs: { ProtectedImage: true, AppWindowDialog: true } } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
beforeEach(() => {
  vi.clearAllMocks()
  state.followed = true
  api.detail.mockResolvedValue({ etag: '"issue-1"', data: {
    id: 'issue-1', issue_number: '领料-1', status: 'ISSUED', status_display: '已出库', line_count: 1,
    production_task: { id: 'task-1', task_number: '任务-1' }, product: { id: 'product-1', product_name: '产品', image_file_id: null },
    workshop: { id: 'metal', name: '金工车间' }, recipient: { id: 'employee-1', name: '领料人' },
    created_by: { id: 'employee-1', name: '制单人' }, audit_events: [], remark: '', issue_at: '2026-11-03',
    lines: [{ id: 'line-1', line_type: 'RAW', material_name: '管材', unit: '支', requested_quantity: '10', issued_quantity: '10',
      conversion_snapshot: { kind: 'PIPE' } }],
  } })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('领料关联详情的返回范围', () => {
  it('跟单可看关联明细，返回任务且不提供独立金工来源入口', async () => {
    const wrapper = await createView()
    expect(api.detail).toHaveBeenCalledWith('issue-1')
    expect(wrapper.text()).toContain('领料-1')
    expect(wrapper.find('[data-testid="issue-metal-processing-entry"]').exists()).toBe(false)
    await wrapper.findAll('button').find(button => button.text() === '返回生产任务')!.trigger('click')
    expect(navigation.push).toHaveBeenCalledWith({ name: 'production-task-detail', params: { taskId: 'task-1' } })
  })
  it('独立模块授权保留返回列表和金工来源入口', async () => {
    state.followed = false
    const wrapper = await createView()
    await wrapper.findAll('button').find(button => button.text() === '返回列表')!.trigger('click')
    expect(navigation.push).toHaveBeenLastCalledWith({ name: 'material-issues', query: {} })
    await wrapper.get('[data-testid="issue-metal-processing-entry"]').trigger('click')
    expect(navigation.push).toHaveBeenLastCalledWith({ name: 'workshop-outsourcing', query: { tab: 'sources', issue_id: 'issue-1' } })
  })
})
