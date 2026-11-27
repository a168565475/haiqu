import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { RouterView, createMemoryHistory, createRouter } from 'vue-router'
import { expect, it, vi } from 'vitest'
import MaterialIssueListView from './MaterialIssueListView.vue'
import MaterialIssueDetailView from './MaterialIssueDetailView.vue'

// A module reloaded by Vite can export a different router from the installed one.
vi.mock('@/router', () => ({ router: { push: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({
  user: { is_superuser: true }, hasPermission: () => true,
}) }))
vi.mock('@/api/materialIssues', async importOriginal => {
  const issue = {
    id: 'issue-1', issue_number: 'LL001', status: 'ISSUED', status_display: '已出库',
    production_task: { id: 'task-1', task_number: '任务001' }, product: { product_name: '折叠椅' },
    workshop: { name: '金工车间' }, recipient: { name: '领料人' }, created_by: { name: '制单人' },
    lines: [], audit_events: [],
  }
  return {
    ...await importOriginal<typeof import('@/api/materialIssues')>(),
    fetchMaterialIssueOptions: async () => ({ workshops: [], recipients: [], production_tasks: [] }),
    fetchMaterialIssues: async () => ({ data: [issue], meta: { total: 1 } }),
    fetchMaterialIssue: async () => ({ data: issue, etag: '"issue-1"' }),
  }
})

it('查看领料单和返回列表都切换当前画面并保留查询条件', async () => {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { name: 'material-issues', path: '/workshop/material-issues', component: MaterialIssueListView },
    { name: 'material-issue-detail', path: '/workshop/material-issues/:issueId', component: MaterialIssueDetailView },
  ] })
  const list = '/workshop/material-issues'
  await router.push(list + '?status=ISSUED')
  const wrapper = mount(RouterView, { global: {
    plugins: [router, ElementPlus], stubs: { AppWindowDialog: true, ProtectedImage: true },
  } })
  try {
    await flushPromises()
    await wrapper.get('tbody tr button').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe(list + '/issue-1?status=ISSUED')
    expect(wrapper.get('h1').text()).toBe('领料单详情')
    expect(wrapper.text()).toContain('LL001')

    await wrapper.findAll('button').find(button => button.text() === '返回列表')!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe(list + '?status=ISSUED')
    expect(wrapper.get('h1').text()).toBe('车间领料')
  } finally { wrapper.unmount() }
})
