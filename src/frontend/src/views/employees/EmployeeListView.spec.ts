import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import EmployeeListView from './EmployeeListView.vue'
import { useAuthStore } from '@/stores/auth'
import type { AccessEmployee } from '@/types/access'

const api = vi.hoisted(() => ({ getEmployees: vi.fn(), getDepartments: vi.fn(), getRoles: vi.fn(), getTeams: vi.fn(), getCatalog: vi.fn() }))
vi.mock('@/api/access', async original => ({ ...await original<object>(), ...api }))
vi.mock('@/directives/horizontalOverflow', () => ({ vHorizontalOverflow: {} }))
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
  const wrapper = mount({ template: '<router-view />' }, { global: { plugins: [pinia, router], stubs: { EmployeeDirectoryDialog: true, DepartmentMappingDialog: true, EmployeeDepartmentsDialog: true, DeleteManagementDialog: true, AppWindowDialog: { props: ['modelValue', 'title'], template: '<section v-if="modelValue" role="dialog"><h2>{{ title }}</h2><slot /><slot name="footer" /></section>' } } } })
  wrappers.push(wrapper); await flushPromises(); return { wrapper, router }
}
function button(wrapper: ReturnType<typeof mount>, label: string) { return wrapper.findAll('button').find(element => element.text() === label)! }
beforeEach(() => {
  vi.resetAllMocks(); pinia = createPinia(); setActivePinia(pinia)
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true, employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  api.getEmployees.mockResolvedValue([employee(1), employee(2), employee(3, { status: 'LEFT', account_active: false }), employee(4, { username: null, account_active: null })])
  api.getDepartments.mockResolvedValue([]); api.getRoles.mockResolvedValue([]); api.getTeams.mockResolvedValue([]); api.getCatalog.mockResolvedValue([])
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('员工主列表', () => {
  it('使用统一员工列表，标题位于筛选卡片内，不自动读取企微', async () => {
    const { wrapper } = await render()
    expect(api.getEmployees).toHaveBeenCalledOnce(); expect(api.getRoles).toHaveBeenCalledOnce(); expect(api.getDepartments).toHaveBeenCalledOnce()
    expect(wrapper.findAll('tbody tr')).toHaveLength(4)
    expect(wrapper.text()).toContain('EMP-1'); expect(wrapper.text()).toContain('EMP-2')
    expect(wrapper.findComponent({ name: 'EmployeeDirectoryDialog' }).attributes('modelvalue')).toBe('false')
    expect(wrapper.text()).not.toContain('统一员工档案供账号、考勤与车间配置使用。')
    expect(wrapper.text()).not.toContain('部门归属不会自动分配角色')
    expect(wrapper.get('.employee-filters.access-box h1').text()).toBe('员工')
    expect(wrapper.findAll('th').map(cell => cell.text())).toContain('企业微信部门')
    expect(wrapper.findAll('.employee-wecom-department').map(cell => cell.text())).toEqual(['UNKNOWN', 'UNKNOWN', 'UNKNOWN', 'UNKNOWN'])
  })
  it.each<{ departments: AccessEmployee['wecom_departments']; expected: string }>([
    { departments: undefined, expected: 'UNKNOWN' },
    { departments: null, expected: 'UNKNOWN' },
    { departments: [], expected: '未分配' },
    { departments: [{ id: 5, name: '生产部' }], expected: '生产部（5）' },
    { departments: [{ id: 9, name: null }], expected: 'UNKNOWN（9）' },
    { departments: [{ id: 5, name: '生产部' }, { id: 12, name: '技术支持' }, { id: 9, name: null }], expected: '生产部（5）、技术支持（12）、UNKNOWN（9）' },
  ])('企业微信部门按来源字段显示$expected，未取得来源时不使用ERP部门替代', async ({ departments, expected }) => {
    api.getEmployees.mockResolvedValueOnce([employee(1, { department: 'ERP归属部门', wecom_departments: departments })])
    const { wrapper } = await render()
    const cell = wrapper.get('.employee-wecom-department')
    expect(cell.text()).toBe(expected)
    expect(cell.attributes('title')).toBe(expected)
    expect(wrapper.get('tbody').text()).toContain('ERP归属部门')
  })
  it('完整保留生成账号与悬停内容，没有账号时显示占位符', async () => {
    const username = 'wecom_0123456789abcdef0123456789abcdef'
    api.getEmployees.mockResolvedValueOnce([employee(1, { username }), employee(2, { username: null, account_active: null })])
    const { wrapper } = await render()
    const cells = wrapper.findAll('.employee-account')
    expect(cells.map(cell => cell.text())).toEqual([username, '未开通'])
    expect(cells.map(cell => cell.attributes('title'))).toEqual([username, '未开通'])
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
  it('只有组织权限时可维护部门，不提供员工读取和删除', async () => {
    grant('organizations.manage_organization')
    const { wrapper } = await render()
    expect(button(wrapper, '从企业微信读取')).toBeUndefined(); expect(button(wrapper, '权限管理')).toBeUndefined()
    expect(api.getDepartments).toHaveBeenCalledOnce()
    await button(wrapper, '部门管理').trigger('click'); await flushPromises()
    expect(api.getDepartments).toHaveBeenCalledOnce()
    expect(wrapper.findComponent({ name: 'EmployeeDepartmentsDialog' }).props('employee')).toEqual(employee(1))
  })
  it('两个入口使用相同操作：就地分配角色，管理员也能选择和删除', async () => {
    const { wrapper, router } = await render()
    await button(wrapper, '分配角色').trigger('click'); await flushPromises()
    expect(wrapper.get('[role="dialog"]').text()).toContain('分配员工角色')
    expect(router.currentRoute.value.path).toBe('/employees')
    await button(wrapper, '取消').trigger('click')
    await wrapper.get('[aria-label="选择本页员工"]').setValue(true)
    await button(wrapper, '删除所选（4）').trigger('click')
    expect(wrapper.findComponent({ name: 'DeleteManagementDialog' }).props('items')).toHaveLength(4)
    expect(wrapper.findComponent({ name: 'DeleteManagementDialog' }).props('kind')).toBe('employees')
  })
  it('补部门入口打开已勾选映射模式，普通读取保持不勾选', async () => {
    const { wrapper } = await render()
    await button(wrapper, '按映射补充部门').trigger('click')
    expect(wrapper.findComponent({ name: 'EmployeeDirectoryDialog' }).props('initialApplyDepartments')).toBe(true)
  })
  it('没有目录权限不读员工；权限被撤回清除旧名单与弹窗', async () => {
    grant()
    const { wrapper } = await render()
    expect(api.getEmployees).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('无权限管理权限')
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
