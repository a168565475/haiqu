import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ElSelect } from 'element-plus'
import EmployeeListView from './EmployeeListView.vue'
import { useAuthStore } from '@/stores/auth'
import type { AccessEmployee } from '@/types/access'

const api = vi.hoisted(() => ({ getEmployees: vi.fn(), getDepartments: vi.fn(), getRoles: vi.fn(), getTeams: vi.fn(), getCatalog: vi.fn(), adjustEmployees: vi.fn(), renameEmployee: vi.fn() }))
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
  const wrapper = mount({ template: '<router-view />' }, { global: { plugins: [pinia, router], stubs: { ElDropdown: { template: '<div><slot/><slot name="dropdown"/></div>' }, ElDropdownMenu: { template: '<div><slot/></div>' }, ElDropdownItem: { props: ['disabled'], template: '<button :disabled="disabled"><slot/></button>' }, EmployeeDirectoryDialog: true, DepartmentMappingDialog: true, EmployeeDepartmentsDialog: true, DeleteManagementDialog: true, AppWindowDialog: { props: ['modelValue', 'title'], template: '<section v-if="modelValue" role="dialog"><h2>{{ title }}</h2><slot /><slot name="footer" /></section>' } } } })
  wrappers.push(wrapper); await flushPromises(); return { wrapper, router }
}
function button(wrapper: ReturnType<typeof mount>, label: string) { return wrapper.findAll('button').find(element => element.text() === label || (label === '下一页' && element.classes().includes('btn-next')) || (label === '上一页' && element.classes().includes('btn-prev')))! }
beforeEach(() => {
  vi.resetAllMocks(); pinia = createPinia(); setActivePinia(pinia)
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true, employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  vi.spyOn(useAuthStore(), 'initialize').mockResolvedValue()
  api.getEmployees.mockResolvedValue([employee(1), employee(2), employee(3, { status: 'LEFT', account_active: false }), employee(4, { username: null, account_active: null })])
  api.getDepartments.mockResolvedValue([]); api.getRoles.mockResolvedValue([]); api.getTeams.mockResolvedValue([]); api.getCatalog.mockResolvedValue([])
})
afterEach(() => wrappers.splice(0).forEach(wrapper => wrapper.unmount()))

describe('员工主列表', () => {
  it('组织管理员可修改姓名，只提交所选员工和去除空格的姓名', async () => {
    grant('organizations.manage_organization')
    const { wrapper } = await render()
    await button(wrapper, '修改姓名').trigger('click')
    expect(wrapper.get('[aria-label="员工姓名"]').element).toHaveProperty('value', '同名员工')
    await wrapper.get('[aria-label="员工姓名"]').setValue('  新姓名  ')
    await button(wrapper, '确认保存').trigger('click'); await flushPromises()
    expect(api.renameEmployee).toHaveBeenCalledExactlyOnceWith(employee(1), '新姓名')
    expect(wrapper.find('[aria-label="员工姓名"]').exists()).toBe(false)
    expect(api.getEmployees).toHaveBeenCalledTimes(2)
  })
  it('空姓名不发送请求，保存失败保留输入并显示错误', async () => {
    const { wrapper } = await render()
    await button(wrapper, '修改姓名').trigger('click')
    await wrapper.get('[aria-label="员工姓名"]').setValue('  ')
    await button(wrapper, '确认保存').trigger('click'); await flushPromises()
    expect(api.renameEmployee).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('请输入员工姓名')
    api.renameEmployee.mockRejectedValueOnce(new Error('failed'))
    await wrapper.get('[aria-label="员工姓名"]').setValue('未保存的姓名')
    await button(wrapper, '确认保存').trigger('click'); await flushPromises()
    expect(wrapper.get('[aria-label="员工姓名"]').element).toHaveProperty('value', '未保存的姓名')
    expect(wrapper.get('[role="alert"]').text()).toContain('操作失败')
  })
  it('只有账号权限时不显示修改姓名', async () => {
    grant('access_control.manage_accounts')
    const { wrapper } = await render()
    expect(button(wrapper, '修改姓名')).toBeUndefined()
  })
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
  it('登录方式后显示真实登录时间与次数，区分未登录、无账号和未知数据', async () => {
    api.getEmployees.mockResolvedValue([
      employee(1, {last_login:'2026-10-23T03:30:00Z', login_count:3}),
      employee(2, {last_login:null, login_count:0}),
      employee(3, {username:null, last_login:null, login_count:null}),
      employee(4),
    ])
    const { wrapper } = await render()
    const headers = wrapper.findAll('th').map(cell => cell.text())
    expect(headers.slice(headers.indexOf('登录方式'), headers.indexOf('登录方式') + 5)).toEqual(['登录方式','最后登录时间','登录次数','员工编码','登录账号'])
    expect(wrapper.findAll('.employee-login-count').map(cell => cell.text())).toEqual(['3','0','—','UNKNOWN'])
    expect(wrapper.findAll('.employee-last-login').map(cell => cell.text())).toEqual([new Date('2026-10-23T03:30:00Z').toLocaleString('zh-CN',{hour12:false}),'未登录','—','UNKNOWN'])
  })
  it('查询员工编码并按员工/账号状态筛选，空结果明确显示', async () => {
    const { wrapper } = await render()
    await wrapper.get('[aria-label="搜索员工"]').setValue('EMP-2'); await button(wrapper, '查询').trigger('click')
    expect(wrapper.findAll('tbody tr')).toHaveLength(1); expect(wrapper.get('tbody').text()).toContain('EMP-2')
    wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === '员工状态筛选')!.vm.$emit('update:modelValue', 'LEFT'); await flushPromises()
    expect(wrapper.text()).toContain('没有符合条件的员工')
    await wrapper.get('[aria-label="搜索员工"]').setValue(''); await button(wrapper, '查询').trigger('click')
    expect(wrapper.get('tbody').text()).toContain('EMP-3')
    wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === '员工状态筛选')!.vm.$emit('update:modelValue', 'all')
    wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === '账号状态')!.vm.$emit('update:modelValue', 'none'); await flushPromises()
    expect(wrapper.get('tbody').text()).toContain('EMP-4'); expect(wrapper.findAll('tbody tr')).toHaveLength(1)
  })
  it('角色分配筛选重置页码，并与部门和员工状态组合生效', async () => {
    api.getEmployees.mockResolvedValueOnce([
      ...Array.from({ length: 51 }, (_, index) => employee(index + 1, {role_ids: [], department_ids: ['production']})),
      employee(52, {role_ids: ['role-a', 'role-b'], department_ids: ['production']}),
      employee(53, {role_ids: ['role-a'], department_ids: ['quality'], status: 'LEFT'}),
    ])
    const { wrapper } = await render()
    await button(wrapper, '下一页').trigger('click')
    const select = (label: string, value: string) => wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === label)!.vm.$emit('update:modelValue', value)
    select('角色分配筛选', 'assigned'); await flushPromises()
    expect(wrapper.get('.access-pagination .el-pager .is-active').text()).toBe('1')
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(wrapper.get('tbody').text()).toContain('EMP-52')
    select('部门筛选', 'production'); await flushPromises()
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    select('员工状态筛选', 'LEFT'); await flushPromises()
    expect(wrapper.text()).toContain('没有符合条件的员工')
    select('员工状态筛选', 'all'); select('角色分配筛选', 'unassigned'); await flushPromises()
    expect(wrapper.findAll('tbody tr')).toHaveLength(50)
    expect(wrapper.get('tbody').text()).not.toContain('EMP-52')
    select('角色分配筛选', 'all'); select('部门筛选', 'all'); await flushPromises()
    expect(wrapper.text()).toContain('共 53 人')
  })
  it('部门联动具体角色筛选，按角色ID匹配多角色员工，换部门清除旧角色', async () => {
    api.getRoles.mockResolvedValue([
      {id:'assembly', department_id:'production', display_name:'装配车间', archived:false},
      {id:'metal', department_id:'production', display_name:'金工车间', archived:false},
      {id:'quality-role', department_id:'quality', display_name:'装配车间', archived:false},
    ])
    api.getEmployees.mockResolvedValueOnce([
      ...Array.from({length:51}, (_, index) => employee(index + 1, {role_ids:['metal'], department_ids:['production']})),
      employee(52, {role_ids:['metal','assembly'], department_ids:['production','quality']}),
      employee(53, {role_ids:['quality-role'], department_ids:['quality']}),
    ])
    const { wrapper } = await render()
    const select = (label: string) => wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === label)!
    select('部门筛选').vm.$emit('update:modelValue', 'production'); await flushPromises()
    expect(select('角色筛选').findAllComponents({name:'ElOption'}).map(option => option.props('value'))).toEqual(['all','assembly','metal'])
    await button(wrapper, '下一页').trigger('click')
    select('角色筛选').vm.$emit('update:modelValue', 'assembly'); await flushPromises()
    expect(wrapper.get('.access-pagination .el-pager .is-active').text()).toBe('1')
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expect(wrapper.get('tbody').text()).toContain('EMP-52')
    select('部门筛选').vm.$emit('update:modelValue', 'quality'); await flushPromises()
    expect(select('角色筛选').props('modelValue')).toBe('all')
    expect(select('角色筛选').findAllComponents({name:'ElOption'}).map(option => option.props('value'))).toEqual(['all','quality-role'])
    select('角色筛选').vm.$emit('update:modelValue', 'quality-role'); await flushPromises()
    expect(wrapper.get('tbody').text()).toContain('EMP-53')
    expect(wrapper.get('tbody').text()).not.toContain('EMP-52')
    select('角色分配筛选').vm.$emit('update:modelValue', 'unassigned'); await flushPromises()
    expect(wrapper.text()).toContain('没有符合条件的员工')
    select('角色分配筛选').vm.$emit('update:modelValue', 'all')
    select('部门筛选').vm.$emit('update:modelValue', 'all'); await flushPromises()
    expect(select('角色筛选').findAllComponents({name:'ElOption'})).toHaveLength(4)
    expect(wrapper.text()).toContain('共 53 人')
  })
  it('分页后筛选回到第一页，刷新失败不把旧名单当成功', async () => {
    api.getEmployees.mockResolvedValueOnce(Array.from({ length: 51 }, (_, index) => employee(index + 1)))
    const { wrapper } = await render()
    await button(wrapper, '下一页').trigger('click'); expect(wrapper.get('tbody').text()).toContain('EMP-51')
    await wrapper.get('[aria-label="搜索员工"]').setValue('EMP-1'); await button(wrapper, '查询').trigger('click')
    expect(wrapper.get('.access-pagination .el-pager .is-active').text()).toBe('1')
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
    expect(wrapper.findAll('tbody tr.selected')).toHaveLength(4)
    expect(wrapper.get('.employee-filters').text()).not.toContain('删除所选')
    expect(wrapper.get('.employee-batch-toolbar').text()).toContain('已选 4 人')
    await button(wrapper, '删除所选').trigger('click')
    expect(wrapper.findComponent({ name: 'DeleteManagementDialog' }).props('items')).toHaveLength(4)
    expect(wrapper.findComponent({ name: 'DeleteManagementDialog' }).props('kind')).toBe('employees')
  })
  it.each(['按映射补充部门', '从企业微信读取'])('%s入口默认启用部门映射', async label => {
    const { wrapper } = await render()
    await button(wrapper, label).trigger('click')
    expect(wrapper.findComponent({ name: 'EmployeeDirectoryDialog' }).props('initialApplyDepartments')).toBe(true)
  })
  it('企业微信部门和本地部门按ID组合筛选，多部门员工也能匹配', async () => {
    api.getEmployees.mockResolvedValueOnce([
      employee(1, { department_ids: ['production', 'quality'], wecom_departments: [{ id: 5, name: '生产部' }, { id: 6, name: '品质部' }] }),
      employee(2, { department_ids: ['quality'], wecom_departments: [{ id: 5, name: '生产部' }] }),
      employee(3, { department_ids: [], wecom_departments: [] }),
      employee(4, { department_ids: undefined, wecom_departments: null }),
    ])
    const { wrapper } = await render()
    const select = (label: string, value: string) => wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === label)!.vm.$emit('update:modelValue', value)
    select('部门筛选', 'quality'); select('企业微信部门筛选', '6'); await flushPromises()
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expect(wrapper.get('tbody').text()).toContain('EMP-1')
    select('部门筛选', 'none'); select('企业微信部门筛选', 'none'); await flushPromises()
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    expect(wrapper.get('tbody').text()).toContain('EMP-3')
    select('部门筛选', 'all'); select('企业微信部门筛选', 'all'); await flushPromises()
    expect(wrapper.findAll('tbody tr')).toHaveLength(4)
  })
  it('批量部门联动对应角色，点击调整同时提交所选员工及版本', async () => {
    api.getRoles.mockResolvedValue([
      { id: 'prod-role', department_id: 'production', display_name: '生产员工', archived: false },
      { id: 'quality-role', department_id: 'quality', display_name: '质检员', archived: false },
      { id: 'archived-role', department_id: 'production', display_name: '停用角色', archived: true },
    ])
    api.adjustEmployees.mockResolvedValue({ updated_count: 2 })
    const { wrapper } = await render()
    await wrapper.get('[aria-label="选择员工 EMP-1"]').setValue(true)
    await wrapper.get('[aria-label="选择员工 EMP-2"]').setValue(true)
    const department = wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === '批量调整部门')!
    const roles = wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === '批量调整角色')!
    expect(department.props('multiple')).toBe(true)
    expect(roles.props('multiple')).toBe(true)
    department.vm.$emit('update:modelValue', ['production']); await flushPromises()
    expect(roles.findAllComponents({ name: 'ElOption' }).map(option => option.props('value'))).toEqual(['prod-role'])
    roles.vm.$emit('update:modelValue', ['prod-role']); await flushPromises()
    department.vm.$emit('update:modelValue', ['production', 'quality']); await flushPromises()
    expect(roles.props('modelValue')).toEqual([])
    expect(roles.findAllComponents({ name: 'ElOption' }).map(option => option.props('value'))).toEqual(['prod-role', 'quality-role'])
    roles.vm.$emit('update:modelValue', ['prod-role', 'quality-role']); await flushPromises()
    await button(wrapper, '调整').trigger('click'); await flushPromises()
    expect(api.adjustEmployees).toHaveBeenCalledWith({items: [{id: 'employee-1', etag: '"employee-1"'}, {id: 'employee-2', etag: '"employee-2"'}], department_ids: ['production', 'quality'], role_ids: ['prod-role', 'quality-role']})
    expect(wrapper.get('.employee-batch-toolbar').text()).toContain('已选 0 人')
  })
  it('角色只来自本次所选部门，失败保留本次选择并显示错误', async () => {
    api.getEmployees.mockResolvedValue([employee(1, {department_ids: ['production', 'quality']}), employee(2, {department_ids: ['quality']})])
    api.getRoles.mockResolvedValue([{id:'prod-role', department_id:'production', display_name:'生产员工', archived:false}, {id:'quality-role', department_id:'quality', display_name:'质检员', archived:false}])
    api.adjustEmployees.mockRejectedValue(new Error('offline'))
    const { wrapper } = await render()
    await wrapper.get('[aria-label="选择本页员工"]').setValue(true)
    const roles = wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === '批量调整角色')!
    expect(roles.findAllComponents({ name: 'ElOption' })).toHaveLength(0)
    wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === '批量调整部门')!.vm.$emit('update:modelValue', ['quality']); await flushPromises()
    expect(roles.findAllComponents({ name: 'ElOption' }).map(option => option.props('value'))).toEqual(['quality-role'])
    roles.vm.$emit('update:modelValue', ['quality-role']); await flushPromises()
    await button(wrapper, '调整').trigger('click'); await flushPromises()
    expect(api.adjustEmployees.mock.calls[0]![0]).toMatchObject({department_ids:['quality'], role_ids:['quality-role']})
    expect(wrapper.get('.employee-batch-toolbar').text()).toContain('已选 2 人')
    expect(wrapper.get('[role="alert"]').text()).toContain('操作失败')
  })
  it.each([{departmentIds:[]}, {departmentIds:['production']}])('角色留空时显式覆盖清空，部门以本次选择 $departmentIds 为准', async ({departmentIds}) => {
    api.adjustEmployees.mockResolvedValue({updated_count:1})
    const { wrapper } = await render()
    await wrapper.get('[aria-label="选择员工 EMP-1"]').setValue(true)
    wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === '批量调整部门')!.vm.$emit('update:modelValue', departmentIds); await flushPromises()
    await button(wrapper, '调整').trigger('click'); await flushPromises()
    expect(api.adjustEmployees).toHaveBeenCalledWith({items:[{id:'employee-1',etag:'"employee-1"'}], department_ids:departmentIds, role_ids:[]})
  })
  it('仅组织管理员不能执行需要同时覆盖部门和角色的批量调整', async () => {
    grant('organizations.manage_organization')
    api.adjustEmployees.mockResolvedValue({updated_count:1})
    const { wrapper } = await render()
    await wrapper.get('[aria-label="选择员工 EMP-1"]').setValue(true)
    const selects = wrapper.findAllComponents(ElSelect)
    expect(selects.some(c => c.props('ariaLabel') === '批量调整角色')).toBe(false)
    expect(selects.some(c => c.props('ariaLabel') === '批量调整部门')).toBe(false)
    expect(button(wrapper, '删除所选')).toBeUndefined()
    expect(button(wrapper, '调整')).toBeUndefined()
    expect(api.adjustEmployees).not.toHaveBeenCalled()
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
