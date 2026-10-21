import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EmployeeListView from './EmployeeListView.vue'
import { useAuthStore } from '@/stores/auth'
import type { AccessEmployee } from '@/types/access'

const api = vi.hoisted(() => ({ getEmployees: vi.fn(), getDepartments: vi.fn(), getRoles: vi.fn() }))
vi.mock('@/api/access', async original => ({ ...await original<object>(), ...api }))
const wrappers: ReturnType<typeof mount>[] = []
let pinia: ReturnType<typeof createPinia>
function employee(index: number, overrides: Partial<AccessEmployee> = {}): AccessEmployee {
  return { id: `employee-${index}`, employee_code: `EMP-${index}`, display_name: index < 3 ? '同名员工' : `员工${index}`, status: 'ACTIVE', username: `user-${index}`, account_active: true, account_protected: false, team_id: null, department: '生产部', role_ids: [], etag: `"employee-${index}"`, ...overrides }
}
function grant(...permissions: string[]) {
  const auth = useAuthStore()
  auth.user = { ...auth.user!, username: 'ordinary-manager', is_superuser: false, effective_access: { active: true, is_superuser: false, roles: [], legacy_sources: [], version: 'v1', actions: Object.fromEntries(permissions.map(permission => [permission, { scopes: ['MODULE'], sources: [{ type: 'ROLE', scope: 'MODULE' }] }])) } }
}
async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/employees', component: EmployeeListView }, { path: '/settings/access', name: 'access-management', component: { template: '<div>账号</div>' } }] })
  await router.push('/employees'); await router.isReady()
  const wrapper = mount(EmployeeListView, { global: { plugins: [pinia, router], stubs: { EmployeeDirectoryDialog: true, DepartmentMappingDialog: true, EmployeeDepartmentsDialog: true } } })
  wrappers.push(wrapper); await flushPromises(); return { wrapper, router }
}
function button(wrapper: ReturnType<typeof mount>, label: string) { return wrapper.findAll('button').find(element => element.text() === label)! }
beforeEach(() => {
  vi.resetAllMocks(); pinia = createPinia(); setActivePinia(pinia)
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true, employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  api.getEmployees.mockResolvedValue([employee(1), employee(2), employee(3, { status: 'LEFT', account_active: false }), employee(4, { username: null, account_active: null })])
  api.getDepartments.mockResolvedValue([])
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('员工主列表', () => {
  it('仅加载ERP员工，同名保留编码，无角色全量读取或自动企微预览', async () => {
    const { wrapper } = await render()
    expect(api.getEmployees).toHaveBeenCalledOnce(); expect(api.getRoles).not.toHaveBeenCalled(); expect(api.getDepartments).not.toHaveBeenCalled()
    expect(wrapper.findAll('tbody tr')).toHaveLength(4)
    expect(wrapper.text()).toContain('EMP-1'); expect(wrapper.text()).toContain('EMP-2')
    expect(wrapper.findComponent({ name: 'EmployeeDirectoryDialog' }).attributes('modelvalue')).toBe('false')
    expect(wrapper.text()).toContain('账号已启用也不代表已获得 ERP 访问权限')
  })
  it('查询员工编码并按员工/账号状态筛选，空结果明确显示', async () => {
    const { wrapper } = await render()
    await wrapper.get('[aria-label="搜索员工"]').setValue('EMP-2'); await button(wrapper, '查询').trigger('click')
    expect(wrapper.findAll('tbody tr')).toHaveLength(1); expect(wrapper.get('tbody').text()).toContain('EMP-2')
    await wrapper.get('[aria-label="员工状态筛选"]').setValue('LEFT')
    expect(wrapper.text()).toContain('没有符合条件的员工')
    await wrapper.get('[aria-label="搜索员工"]').setValue(''); await button(wrapper, '查询').trigger('click')
    expect(wrapper.get('tbody').text()).toContain('EMP-3')
    await wrapper.get('[aria-label="员工状态筛选"]').setValue('all'); await wrapper.get('[aria-label="账号状态"]').setValue('none')
    expect(wrapper.get('tbody').text()).toContain('EMP-4'); expect(wrapper.findAll('tbody tr')).toHaveLength(1)
  })
  it('分页后筛选回到第一页，刷新失败不把旧名单当成功', async () => {
    api.getEmployees.mockResolvedValueOnce(Array.from({ length: 21 }, (_, index) => employee(index + 1)))
    const { wrapper } = await render()
    await button(wrapper, '下一页').trigger('click'); expect(wrapper.get('tbody').text()).toContain('EMP-21')
    await wrapper.get('[aria-label="搜索员工"]').setValue('EMP-1'); await button(wrapper, '查询').trigger('click')
    expect(wrapper.get('.access-pagination').text()).toContain('1 / 1')
    api.getEmployees.mockRejectedValueOnce(new Error('offline'))
    await button(wrapper, '刷新员工').trigger('click'); await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true); expect(wrapper.findAll('tbody tr')).toHaveLength(0)
  })
  it('只有组织权限时可维护部门，点击前不加载部门选项', async () => {
    grant('organizations.manage_organization')
    const { wrapper } = await render()
    expect(button(wrapper, '从企业微信读取')).toBeUndefined(); expect(button(wrapper, '权限管理')).toBeUndefined()
    expect(api.getDepartments).not.toHaveBeenCalled()
    await button(wrapper, '部门管理').trigger('click'); await flushPromises()
    expect(api.getDepartments).toHaveBeenCalledOnce()
    expect(wrapper.findComponent({ name: 'EmployeeDepartmentsDialog' }).props('employee')).toEqual(employee(1))
  })
  it('权限管理员按员工ID进入现有授权页，账号管理员仅进入账号页', async () => {
    grant('access_control.manage_access')
    const first = await render()
    await button(first.wrapper, '权限管理').trigger('click'); await flushPromises()
    expect(first.router.currentRoute.value.query).toEqual({ tab: 'employees', employee_id: 'employee-1' })
    first.wrapper.unmount(); wrappers.splice(wrappers.indexOf(first.wrapper), 1)
    grant('access_control.manage_accounts')
    const second = await render()
    expect(button(second.wrapper, '权限管理')).toBeUndefined()
    await button(second.wrapper, '账号管理').trigger('click'); await flushPromises()
    expect(second.router.currentRoute.value.query).toEqual({ tab: 'employees' })
  })
  it('没有目录权限不读员工；权限被撤回清除旧名单与弹窗', async () => {
    grant()
    const { wrapper } = await render()
    expect(api.getEmployees).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('没有员工目录查看权限')
    grant('access_control.manage_accounts'); await flushPromises()
    await button(wrapper, '从企业微信读取').trigger('click')
    grant(); await flushPromises()
    expect(wrapper.findAll('tbody tr')).toHaveLength(0); expect(wrapper.findComponent({ name: 'EmployeeDirectoryDialog' }).exists()).toBe(false)
  })
  it('在途读取晚到不能恢复已撤权名单', async () => {
    let finish!: (rows: AccessEmployee[]) => void
    api.getEmployees.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const { wrapper } = await render()
    grant(); await flushPromises(); finish([employee(1)]); await flushPromises()
    expect(wrapper.text()).not.toContain('EMP-1')
  })
})
