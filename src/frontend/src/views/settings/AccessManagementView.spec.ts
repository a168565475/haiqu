import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type LocationQueryRaw } from 'vue-router'
import { ElMessage, ElSelect, ElOption } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AccessManagementView from './AccessManagementView.vue'
import { useAuthStore } from '@/stores/auth'
import { pageInstanceKey } from '@/utils/pageInstanceKey'
import type { AccessEmployee, AccessRole } from '@/types/access'

const api = vi.hoisted(() => ({ getRoles: vi.fn(), getEmployees: vi.fn(), getTeams: vi.fn(), getCatalog: vi.fn(), getDepartments: vi.fn(), setRoleDepartment: vi.fn(), assignRoles: vi.fn(), addTeamMembers: vi.fn() }))
vi.mock('@/api/access', async original => ({ ...await original<object>(), ...api }))
vi.mock('@/directives/horizontalOverflow', () => ({ vHorizontalOverflow: {} }))
const dialogStub = { props: ['modelValue', 'title'], template: '<section v-if="modelValue" role="dialog"><h2>{{ title }}</h2><slot /><slot name="footer" /></section>' }
const role: AccessRole = { id: '10000000-0000-4000-8000-000000000001', role_code: 'ROLE_ONE', display_name: '测试角色', description: '', department_id: null, archived: false, assigned_employee_count: 0, grants: [], etag: 'role-v1' }
function employee(index: number): AccessEmployee {
  return { id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`, employee_code: `EMP-${index}`,
    display_name: index === 1 || index === 101 ? '同名员工' : `员工${index}`, status: 'ACTIVE', username: `account_${index}`,
    account_active: true, account_protected: false, team_id: null, department: '生产部', department_ids: ['department-production'], role_ids: [], etag: `employee-${index}-v1` }
}
const target = employee(101)
const wrappers: ReturnType<typeof mount>[] = []
let pinia: ReturnType<typeof createPinia>
async function render(query: LocationQueryRaw = {}) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/settings/access', name: 'access-management', component: AccessManagementView }, { path: '/employees', name: 'employee-list', component: AccessManagementView, props: { employeesOnly: true } }] })
  await router.push({ path: query.tab === 'employees' ? '/employees' : '/settings/access', query }); await router.isReady()
  const wrapper = mount({ setup: () => ({ pageInstanceKey }), template: '<RouterView v-slot="{ Component, route }"><div :key="pageInstanceKey(route, 1)"><component :is="Component" /></div></RouterView>' }, { global: { plugins: [pinia, router], stubs: { ElDropdown: { template: '<div><slot/><slot name="dropdown"/></div>' }, ElDropdownMenu: { template: '<div><slot/></div>' }, ElDropdownItem: { props: ['disabled'], template: '<button :disabled="disabled"><slot/></button>' }, AppWindowDialog: dialogStub, PermissionCell: true } } })
  wrappers.push(wrapper); await flushPromises()
  return { wrapper, router }
}
function button(wrapper: ReturnType<typeof mount>, name: string) { return wrapper.findAll('button').find(item => item.text() === name)! }
beforeEach(() => {
  pinia = createPinia(); setActivePinia(pinia); vi.resetAllMocks()
  const auth = useAuthStore()
  auth.applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true,
    employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  vi.spyOn(auth, 'initialize').mockResolvedValue()
  vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
  api.getRoles.mockResolvedValue([role]); api.getEmployees.mockResolvedValue(Array.from({ length: 101 }, (_, index) => employee(index + 1)))
  api.getTeams.mockResolvedValue([]); api.getCatalog.mockResolvedValue([]); api.assignRoles.mockResolvedValue(target)
  api.getDepartments.mockResolvedValue([{ id:'department-production', unit_code:'DEPT_PRODUCTION', unit_name:'生产部', parent_id:null, status:'ACTIVE', sort_order:40, etag:'dep-v1' }, { id:'department-support', unit_code:'DEPT_SUPPORT', unit_name:'技术支持', parent_id:null, status:'ACTIVE', sort_order:110, etag:'dep-v1' }])
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('企微成员进入现有员工角色分配', () => {
  it('销售团队添加成员使用多选，仅提供业务部在职未分组员工并按ID提交', async () => {
    api.getDepartments.mockResolvedValue([{id:'business', unit_code:'DEPT_BUSINESS', unit_name:'业务部', status:'ACTIVE'}])
    api.getEmployees.mockResolvedValue([
      {...employee(1), department_ids:['business']},
      {...employee(2), department_ids:['business','production']},
      {...employee(3), department_ids:['business'], status:'LEFT'},
      {...employee(4), department_ids:['business'], team_id:'another-team'},
      employee(5),
    ])
    api.getTeams.mockResolvedValue([{id:'team', name:'业务团队', manager_name:'经理', member_ids:[], is_active:true, etag:'team-v1'}])
    const { wrapper } = await render()
    await button(wrapper, '销售团队').trigger('click')
    await button(wrapper, '＋ 添加未分组成员').trigger('click')
    const select = wrapper.findAllComponents(ElSelect).find(item => item.props('ariaLabel') === '销售团队成员')!
    expect(select.props('multiple')).toBe(true)
    expect(select.props('filterable')).toBe(true)
    expect(select.findAllComponents(ElOption).map(item => item.props('value'))).toEqual([employee(1).id, employee(2).id])
    expect(select.findAllComponents(ElOption).map(item => item.props('label'))).toEqual(['同名员工', '员工2'])
    select.vm.$emit('update:modelValue', [employee(1).id, employee(2).id]); await flushPromises()
    await button(wrapper, '确认保存').trigger('click'); await flushPromises()
    expect(api.addTeamMembers).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({id:'team', etag:'team-v1'}), [employee(1).id, employee(2).id])
  })
  it('分配角色只列出当前两个部门的角色，已有跨部门角色保留', async () => {
    const current = { ...employee(1), department: '生产部、技术支持', department_ids: ['department-production', 'department-support'], role_ids: ['previous-role'] }
    api.getEmployees.mockResolvedValue([current])
    api.getRoles.mockResolvedValue([
      { ...role, department_id: 'department-production' },
      { ...role, id: 'support-role', display_name: '技术角色', department_id: 'department-support' },
      { ...role, id: 'other-role', display_name: '财务角色', department_id: 'department-finance' },
      { ...role, id: 'unclassified-role', display_name: '未分类角色' },
      { ...role, id: 'previous-role', display_name: '原有角色', department_id: 'department-finance' },
    ])
    const { wrapper } = await render({ tab: 'employees', employee_id: current.id })
    const choices = wrapper.findAll('[role="dialog"] .access-check-grid label')
    expect(choices.map(item => item.text())).toEqual(['测试角色', '技术角色'])
    expect(wrapper.get('[role="dialog"]').text()).toContain('原有角色（本次保留）')
    await choices[0]!.get('input').setValue(true)
    await button(wrapper, '确认保存').trigger('click'); await flushPromises()
    expect(api.assignRoles).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ id: current.id }), ['previous-role', role.id])
  })
  it('只有一个部门时不按部门名称混入其他部门的角色', async () => {
    api.getRoles.mockResolvedValue([
      { ...role, department_id: 'department-production' },
      { ...role, id: 'other-role', display_name: '其他角色', department_id: 'department-support' },
    ])
    const { wrapper } = await render({ tab: 'employees', employee_id: employee(1).id })
    expect(wrapper.findAll('[role="dialog"] .access-check-grid label').map(item => item.text())).toEqual(['测试角色'])
  })
  it('员工角色ID正序或逆序不改变展示、分配选项顺序和选中状态', async () => {
    api.getRoles.mockResolvedValue([
      { ...role, department_id: 'department-production' },
      { ...role, id: 'support-role', display_name: '技术角色', department_id: 'department-support' },
      { ...role, id: 'unselected-role', display_name: '未分配角色', department_id: 'department-production' },
    ])
    for (const roleIds of [[role.id, 'support-role'], ['support-role', role.id]]) {
      const current = { ...employee(1), department: '生产部、技术支持', department_ids: ['department-production', 'department-support'], role_ids: roleIds }
      api.getEmployees.mockResolvedValue([current])
      const { wrapper } = await render({ tab: 'employees', employee_id: current.id })
      const row = wrapper.get(`[data-employee-id="${current.id}"]`)
      expect(row.findAll('.access-role-tags .access-tag').map(item => item.text())).toEqual(['测试角色', '技术角色'])
      const choices = wrapper.findAll('[role="dialog"] .access-check-grid label')
      expect(choices.map(item => item.text())).toEqual(['测试角色', '技术角色', '未分配角色'])
      expect(choices.map(item => {
        const input = item.get('input').element as HTMLInputElement
        return { id: input.value, checked: input.checked }
      })).toEqual([
        { id: role.id, checked: true },
        { id: 'support-role', checked: true },
        { id: 'unselected-role', checked: false },
      ])
      expect(api.assignRoles).not.toHaveBeenCalled()
      wrapper.unmount(); wrappers.splice(wrappers.indexOf(wrapper), 1)
    }
  })
  it('没有当前部门时不提供全部角色，也不能提交', async () => {
    api.getEmployees.mockResolvedValue([{ ...employee(1), department: '', department_ids: [] }])
    const { wrapper } = await render({ tab: 'employees', employee_id: employee(1).id })
    expect(wrapper.findAll('[role="dialog"] .access-check-grid label')).toHaveLength(0)
    expect(wrapper.get('[role="dialog"]').text()).toContain('请先设置员工部门')
    expect(button(wrapper, '确认保存').attributes('disabled')).toBeDefined()
    expect(api.assignRoles).not.toHaveBeenCalled()
  })
  it('配置外层通过公开关闭检查保留编辑子窗，取消后才可关闭或离开', async () => {
    const { wrapper, router } = await render()
    const view = wrapper.findComponent(AccessManagementView).vm
    expect(view.canClose()).toBe(true)
    await button(wrapper, '＋ 新建角色').trigger('click')
    expect(view.canClose()).toBe(false)
    expect(ElMessage.warning).toHaveBeenLastCalledWith('请先完成或关闭当前编辑窗口。')
    await router.push('/employees')
    expect(router.currentRoute.value.path).toBe('/settings/access')
    await button(wrapper, '取消').trigger('click')
    expect(view.canClose()).toBe(true)
  })
  it('配置外层关闭不能丢弃未保存授权，撤销后解除保护', async () => {
    const { wrapper } = await render()
    const view = wrapper.findComponent(AccessManagementView).vm
    const state = (view.$ as unknown as { setupState: { grants: AccessRole['grants'] } }).setupState
    state.grants = [{ permission: 'customers.view_customeraccount', scope: 'ALL' }]
    await flushPromises()
    expect(view.canClose()).toBe(false)
    expect(ElMessage.warning).toHaveBeenLastCalledWith('请先保存或撤销当前修改。')
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
    await button(wrapper, '撤销修改').trigger('click')
    expect(view.canClose()).toBe(true)
  })
  it('角色部门正在保存时拒绝关闭，完成刷新后可关闭', async () => {
    let finish!: (value: AccessRole) => void
    api.setRoleDepartment.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const { wrapper } = await render()
    const view = wrapper.findComponent(AccessManagementView).vm
    await button(wrapper, '调整部门').trigger('click')
    await button(wrapper, '确认保存').trigger('click')
    expect(view.canClose()).toBe(false)
    expect(ElMessage.warning).toHaveBeenLastCalledWith('请先保存或撤销当前修改。')
    finish(role); await flushPromises()
    expect(view.canClose()).toBe(true)
  })
  it('销售团队客户经理使用可搜索下拉，只列业务部且不显示编号', async () => {
    api.getDepartments.mockResolvedValue([{id:'business', unit_code:'DEPT_BUSINESS', unit_name:'业务部', status:'ACTIVE'}])
    api.getEmployees.mockResolvedValue([{...employee(1), department:'业务部', department_ids:['business']}, employee(2)])
    const { wrapper } = await render()
    await button(wrapper, '销售团队').trigger('click')
    await button(wrapper, '＋ 新建团队').trigger('click')
    expect(wrapper.findComponent(ElSelect).props('filterable')).toBe(true)
    const options = wrapper.findAllComponents(ElOption)
    expect(options).toHaveLength(1)
    expect(options[0]!.props('value')).toBe(employee(1).id)
    expect(options[0]!.props('label')).toBe('同名员工 · 业务部')
    expect(options.some(option => /EMP-/.test(String(option.props('label'))))).toBe(false)
  })
  it('组织管理员可以读取三栏，但授权和账号操作禁用', async () => {
    const auth = useAuthStore()
    auth.user = { ...auth.user!, username: 'organization-manager', is_superuser: false,
      effective_access: { active: true, is_superuser: false, roles: [], legacy_sources: [], version: 'org',
        actions: { 'organizations.manage_organization': { scopes: ['MODULE'], sources: [{ type: 'ROLE', scope: 'MODULE' }] } } } }
    const { wrapper } = await render()
    expect(wrapper.find('.access-department-layout').exists()).toBe(true)
    expect(wrapper.findAll('.access-tabs button').map(item => item.text())).toEqual(['角色与权限'])
    expect(api.getTeams).not.toHaveBeenCalled()
    expect(button(wrapper, '修改资料').attributes('disabled')).toBeDefined()
    expect(button(wrapper, '复制为新角色').attributes('disabled')).toBeDefined()
    expect(button(wrapper, '调整部门').attributes('disabled')).toBeUndefined()
  })
  it('部门筛选显示空部门和未分类，切换不产生写请求', async () => {
    const { wrapper } = await render()
    await wrapper.findAll('.access-department-list button').find(b=>b.text().includes('技术支持'))!.trigger('click')
    expect(wrapper.get('.access-role-list:not(.access-department-list)').text()).toContain('此部门暂无角色')
    expect(wrapper.find('.access-editor').exists()).toBe(false)
    await wrapper.findAll('.access-department-list button').find(b=>b.text().includes('未分类'))!.trigger('click')
    expect(wrapper.get('.access-editor').text()).toContain('测试角色')
    expect(api.setRoleDepartment).not.toHaveBeenCalled()
    expect(wrapper.findAll('.access-tabs button').map(b=>b.text())).toEqual(['角色与权限','销售团队','授权记录'])
  })
  it('调整角色部门使用角色版本，保留授权内容并定位到新部门', async () => {
    api.setRoleDepartment.mockResolvedValue({ ...role, department_id:'department-production', etag:'role-v2' })
    const { wrapper } = await render()
    await button(wrapper,'调整部门').trigger('click')
    wrapper.findAllComponents(ElSelect).find(select => select.props('ariaLabel') === '所属部门')!.vm.$emit('update:modelValue', 'department-production')
    await flushPromises()
    api.getRoles.mockResolvedValue([{ ...role, department_id:'department-production', etag:'role-v2' }])
    await button(wrapper,'确认保存').trigger('click'); await flushPromises()
    expect(api.setRoleDepartment).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ id:role.id, etag:'role-v1', grants:[] }), 'department-production')
    expect(wrapper.get('.access-department-list .current').text()).toContain('生产部')
  })
  it('普通入口仍默认角色页，不自动弹窗或保存', async () => {
    const { wrapper } = await render()
    expect(wrapper.get('.access-tabs .active').text()).toBe('角色与权限')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(api.assignRoles).not.toHaveBeenCalled()
  })
  it('旧权限员工链接转到行政员工页，不默认选择员工', async () => {
    const { wrapper, router } = await render()
    await router.push({ path: '/settings/access', query: { tab: 'employees' } }); await flushPromises()
    expect(router.currentRoute.value.path).toBe('/employees')
    expect(wrapper.find('.access-tabs').exists()).toBe(false)
    expect(wrapper.get('.access-pagination .el-pager .is-active').text()).toBe('1')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })
  it('等列表完成后按ID定位第三页同名员工，保留原ETag，不自动保存', async () => {
    api.getRoles.mockResolvedValue([{ ...role, department_id: 'department-production' }])
    let resolveEmployees!: (employees: AccessEmployee[]) => void
    api.getEmployees.mockImplementationOnce(() => new Promise(resolve => { resolveEmployees = resolve }))
    const { wrapper, router } = await render({ tab: 'employees', employee_id: target.id })
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    resolveEmployees(Array.from({ length: 101 }, (_, index) => employee(index + 1))); await flushPromises()
    expect(wrapper.find('.access-tabs').exists()).toBe(false)
    expect(wrapper.get('.access-pagination .el-pager .is-active').text()).toBe('3')
    expect(wrapper.get('tbody').text()).toContain(target.username)
    expect(wrapper.get('[role="dialog"]').text()).toContain('分配员工角色')
    expect(router.currentRoute.value.query).toEqual({ tab: 'employees' })
    expect(api.assignRoles).not.toHaveBeenCalled()
    await wrapper.get('[role="dialog"] input[type="checkbox"]').setValue(true)
    await button(wrapper, '确认保存').trigger('click'); await flushPromises()
    expect(api.assignRoles).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ id: target.id, etag: target.etag }), [role.id])
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(api.getEmployees).toHaveBeenCalledTimes(2)
  })
  it('同路由新目标清除旧搜索和账号筛选并重新定位，关闭或刷新不再自动弹窗', async () => {
    const { wrapper, router } = await render({ tab: 'employees' })
    await wrapper.get('[aria-label="搜索员工"]').setValue('不会匹配')
    await wrapper.get('[aria-label="搜索员工"]').trigger('keyup.enter')
    wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === '账号状态')!.vm.$emit('update:modelValue', 'none'); await flushPromises()
    await router.push({ query: { tab: 'employees', employee_id: target.id } }); await flushPromises()
    expect((wrapper.get('[aria-label="搜索员工"]').element as HTMLInputElement).value).toBe('')
    expect(wrapper.findAllComponents(ElSelect).find(c => c.props('ariaLabel') === '账号状态')!.props('modelValue')).toBe('all')
    expect(wrapper.get('.access-pagination .el-pager .is-active').text()).toBe('3')
    await button(wrapper, '取消').trigger('click')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    const consumedQuery = { ...router.currentRoute.value.query }
    wrapper.unmount(); wrappers.splice(wrappers.indexOf(wrapper), 1)
    const refreshed = await render(consumedQuery)
    expect(refreshed.wrapper.find('.access-tabs').exists()).toBe(false)
    expect(refreshed.wrapper.find('[role="dialog"]').exists()).toBe(false)
    await refreshed.router.push({ query: { tab: 'employees', employee_id: employee(51).id } }); await flushPromises()
    expect(refreshed.wrapper.get('.access-pagination .el-pager .is-active').text()).toBe('2')
    expect(refreshed.wrapper.get('[role="dialog"]').text()).toContain('员工：员工51')
  })
  it('已打开页面收到新目标时重新读取员工，读取失败不消费目标或误报不存在', async () => {
    api.getEmployees.mockResolvedValueOnce([employee(1)])
    const { wrapper, router } = await render({ tab: 'employees' })
    api.getEmployees.mockRejectedValueOnce(new Error('offline'))
    await router.push({ query: { tab: 'employees', employee_id: target.id } }); await flushPromises()
    expect(api.getEmployees).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[role="alert"]').text()).toContain('暂时无法加载权限管理')
    expect(router.currentRoute.value.query.employee_id).toBe(target.id)
    expect(ElMessage.warning).not.toHaveBeenCalled()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    await button(wrapper, '重新加载').trigger('click'); await flushPromises()
    expect(wrapper.get('.access-pagination .el-pager .is-active').text()).toBe('3')
    expect(wrapper.get('[role="dialog"]').text()).toContain('分配员工角色')
    expect(router.currentRoute.value.query.employee_id).toBeUndefined()
  })
  it('同路由目标的新读取先完成时，旧读取不能覆盖目标员工或关闭窗口', async () => {
    let finishOld!: (rows: AccessEmployee[]) => void
    let finishNew!: (rows: AccessEmployee[]) => void
    api.getEmployees.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
      .mockImplementationOnce(() => new Promise(resolve => { finishNew = resolve }))
    const { wrapper, router } = await render({ tab: 'employees' })
    await router.push({ query: { tab: 'employees', employee_id: target.id } }); await flushPromises()
    finishNew(Array.from({ length: 101 }, (_, index) => employee(index + 1))); await flushPromises()
    expect(wrapper.get('.access-pagination .el-pager .is-active').text()).toBe('3')
    finishOld([employee(1)]); await flushPromises()
    expect(wrapper.get('tbody').text()).toContain(target.username)
    expect(wrapper.get('[role="dialog"]').text()).toContain('分配员工角色')
    expect(api.assignRoles).not.toHaveBeenCalled()
  })
  it('从同名员工A切到B时立即关闭A窗口，B加载期间不能误保存A', async () => {
    api.getRoles.mockResolvedValue([{ ...role, department_id: 'department-production' }])
    const { wrapper, router } = await render({ tab: 'employees', employee_id: employee(1).id })
    expect(wrapper.get('[role="dialog"]').text()).toContain('员工：同名员工')
    await wrapper.get('[role="dialog"] input[type="checkbox"]').setValue(true)
    let finishEmployees!: (rows: AccessEmployee[]) => void
    api.getEmployees.mockImplementationOnce(() => new Promise(resolve => { finishEmployees = resolve }))
    await router.push({ query: { tab: 'employees', employee_id: target.id } }); await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(button(wrapper, '确认保存')).toBeUndefined()
    expect(api.assignRoles).not.toHaveBeenCalled()
    finishEmployees(Array.from({ length: 101 }, (_, index) => employee(index + 1))); await flushPromises()
    expect(wrapper.get('.access-pagination .el-pager .is-active').text()).toBe('3')
    expect((wrapper.get('[role="dialog"] input[type="checkbox"]').element as HTMLInputElement).checked).toBe(false)
    await wrapper.get('[role="dialog"] input[type="checkbox"]').setValue(true)
    await button(wrapper, '确认保存').trigger('click'); await flushPromises()
    expect(api.assignRoles).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ id: target.id, etag: target.etag }), [role.id])
  })
  it.each(['bad-id', '', [target.id, employee(1).id], null].map(value => [value]))('无效员工ID明确提示且不打开分配窗口：%j', async employeeId => {
    const { wrapper, router } = await render({ tab: 'employees', employee_id: employeeId })
    expect(wrapper.find('.access-tabs').exists()).toBe(false)
    expect(ElMessage.warning).toHaveBeenCalledWith('员工定位参数无效，请从员工管理重新进入。')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(router.currentRoute.value.query).toEqual({ tab: 'employees' })
    expect(api.assignRoles).not.toHaveBeenCalled()
  })
  it('目标员工不存在时保留真实列表并明确提示，不以同名替代', async () => {
    api.getEmployees.mockResolvedValueOnce([employee(1)])
    const { wrapper } = await render({ tab: 'employees', employee_id: target.id })
    expect(wrapper.get('tbody').text()).toContain(employee(1).username)
    expect(ElMessage.warning).toHaveBeenCalledWith('未找到该员工，可能已归档或记录已变化，请核对员工与账号列表。')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })
  it('非在职目标可定位但不能绕过原分配限制', async () => {
    api.getEmployees.mockResolvedValueOnce([{ ...target, status: 'INACTIVE' }])
    const { wrapper } = await render({ tab: 'employees', employee_id: target.id })
    expect(ElMessage.warning).toHaveBeenCalledWith('该员工当前非在职状态，不能分配角色。')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(button(wrapper, '分配角色').attributes('disabled')).toBeDefined()
  })
  it('无管理权限时不读取员工或打开目标弹窗', async () => {
    useAuthStore().user!.is_superuser = false
    const { wrapper } = await render({ tab: 'employees', employee_id: target.id })
    expect(wrapper.text()).toContain('无权限管理权限')
    expect(api.getEmployees).not.toHaveBeenCalled()
    expect(api.assignRoles).not.toHaveBeenCalled()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })
})
