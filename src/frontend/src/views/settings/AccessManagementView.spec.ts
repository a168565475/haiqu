import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type LocationQueryRaw } from 'vue-router'
import { ElMessage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AccessManagementView from './AccessManagementView.vue'
import { useAuthStore } from '@/stores/auth'
import { pageInstanceKey } from '@/utils/pageInstanceKey'
import type { AccessEmployee, AccessRole } from '@/types/access'

const api = vi.hoisted(() => ({ getRoles: vi.fn(), getEmployees: vi.fn(), getTeams: vi.fn(), getCatalog: vi.fn(), assignRoles: vi.fn() }))
vi.mock('@/api/access', async original => ({ ...await original<object>(), ...api }))
vi.mock('@/directives/horizontalOverflow', () => ({ vHorizontalOverflow: {} }))
const dialogStub = { props: ['modelValue', 'title'], template: '<section v-if="modelValue" role="dialog"><h2>{{ title }}</h2><slot /><slot name="footer" /></section>' }
const role: AccessRole = { id: '10000000-0000-4000-8000-000000000001', role_code: 'ROLE_ONE', display_name: '测试角色', description: '', archived: false, assigned_employee_count: 0, grants: [], etag: 'role-v1' }
function employee(index: number): AccessEmployee {
  return { id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`, employee_code: `EMP-${index}`,
    display_name: index === 1 || index === 31 ? '同名员工' : `员工${index}`, status: 'ACTIVE', username: `account_${index}`,
    account_active: true, account_protected: false, team_id: null, department: '', role_ids: [], etag: `employee-${index}-v1` }
}
const target = employee(31)
const wrappers: ReturnType<typeof mount>[] = []
let pinia: ReturnType<typeof createPinia>
async function render(query: LocationQueryRaw = {}) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/settings/access', name: 'access-management', component: AccessManagementView }] })
  await router.push({ name: 'access-management', query }); await router.isReady()
  const wrapper = mount({ setup: () => ({ pageInstanceKey }), template: '<RouterView v-slot="{ Component, route }"><div :key="pageInstanceKey(route, 1)"><component :is="Component" /></div></RouterView>' }, { global: { plugins: [pinia, router], stubs: { AppWindowDialog: dialogStub, PermissionCell: true } } })
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
  api.getRoles.mockResolvedValue([role]); api.getEmployees.mockResolvedValue(Array.from({ length: 31 }, (_, index) => employee(index + 1)))
  api.getTeams.mockResolvedValue([]); api.getCatalog.mockResolvedValue([]); api.assignRoles.mockResolvedValue(target)
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('企微成员进入现有员工角色分配', () => {
  it('普通入口仍默认角色页，不自动弹窗或保存', async () => {
    const { wrapper } = await render()
    expect(wrapper.get('.access-tabs .active').text()).toBe('角色与权限')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(api.assignRoles).not.toHaveBeenCalled()
  })
  it('总入口切换员工页，不默认选择员工', async () => {
    const { wrapper } = await render({ tab: 'employees' })
    expect(wrapper.get('.access-tabs .active').text()).toBe('员工与账号')
    expect(wrapper.get('.access-pagination').text()).toContain('1 / 3')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  })
  it('等列表完成后按ID定位第三页同名员工，保留原ETag，不自动保存', async () => {
    let resolveEmployees!: (employees: AccessEmployee[]) => void
    api.getEmployees.mockImplementationOnce(() => new Promise(resolve => { resolveEmployees = resolve }))
    const { wrapper, router } = await render({ tab: 'employees', employee_id: target.id })
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    resolveEmployees(Array.from({ length: 31 }, (_, index) => employee(index + 1))); await flushPromises()
    expect(wrapper.get('.access-tabs .active').text()).toBe('员工与账号')
    expect(wrapper.get('.access-pagination').text()).toContain('3 / 3')
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
    await wrapper.get('[aria-label="账号状态"]').setValue('none')
    await router.push({ query: { tab: 'employees', employee_id: target.id } }); await flushPromises()
    expect((wrapper.get('[aria-label="搜索员工"]').element as HTMLInputElement).value).toBe('')
    expect((wrapper.get('[aria-label="账号状态"]').element as HTMLSelectElement).value).toBe('all')
    expect(wrapper.get('.access-pagination').text()).toContain('3 / 3')
    await button(wrapper, '取消').trigger('click')
    await button(wrapper, '角色与权限').trigger('click'); await button(wrapper, '员工与账号').trigger('click')
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    const consumedQuery = { ...router.currentRoute.value.query }
    wrapper.unmount(); wrappers.splice(wrappers.indexOf(wrapper), 1)
    const refreshed = await render(consumedQuery)
    expect(refreshed.wrapper.get('.access-tabs .active').text()).toBe('员工与账号')
    expect(refreshed.wrapper.find('[role="dialog"]').exists()).toBe(false)
    await refreshed.router.push({ query: { tab: 'employees', employee_id: employee(16).id } }); await flushPromises()
    expect(refreshed.wrapper.get('.access-pagination').text()).toContain('2 / 3')
    expect(refreshed.wrapper.get('[role="dialog"]').text()).toContain('员工：员工16')
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
    expect(wrapper.get('.access-pagination').text()).toContain('3 / 3')
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
    finishNew(Array.from({ length: 31 }, (_, index) => employee(index + 1))); await flushPromises()
    expect(wrapper.get('.access-pagination').text()).toContain('3 / 3')
    finishOld([employee(1)]); await flushPromises()
    expect(wrapper.get('tbody').text()).toContain(target.username)
    expect(wrapper.get('[role="dialog"]').text()).toContain('分配员工角色')
    expect(api.assignRoles).not.toHaveBeenCalled()
  })
  it('从同名员工A切到B时立即关闭A窗口，B加载期间不能误保存A', async () => {
    const { wrapper, router } = await render({ tab: 'employees', employee_id: employee(1).id })
    expect(wrapper.get('[role="dialog"]').text()).toContain('员工：同名员工')
    await wrapper.get('[role="dialog"] input[type="checkbox"]').setValue(true)
    let finishEmployees!: (rows: AccessEmployee[]) => void
    api.getEmployees.mockImplementationOnce(() => new Promise(resolve => { finishEmployees = resolve }))
    await router.push({ query: { tab: 'employees', employee_id: target.id } }); await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(button(wrapper, '确认保存')).toBeUndefined()
    expect(api.assignRoles).not.toHaveBeenCalled()
    finishEmployees(Array.from({ length: 31 }, (_, index) => employee(index + 1))); await flushPromises()
    expect(wrapper.get('.access-pagination').text()).toContain('3 / 3')
    expect((wrapper.get('[role="dialog"] input[type="checkbox"]').element as HTMLInputElement).checked).toBe(false)
    await wrapper.get('[role="dialog"] input[type="checkbox"]').setValue(true)
    await button(wrapper, '确认保存').trigger('click'); await flushPromises()
    expect(api.assignRoles).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ id: target.id, etag: target.etag }), [role.id])
  })
  it.each(['bad-id', '', [target.id, employee(1).id], null].map(value => [value]))('无效员工ID明确提示且不打开分配窗口：%j', async employeeId => {
    const { wrapper, router } = await render({ tab: 'employees', employee_id: employeeId })
    expect(wrapper.get('.access-tabs .active').text()).toBe('员工与账号')
    expect(ElMessage.warning).toHaveBeenCalledWith('员工定位参数无效，请从企业微信管理重新进入。')
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
