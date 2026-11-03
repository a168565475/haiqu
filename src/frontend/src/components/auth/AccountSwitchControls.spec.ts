import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick, ref } from 'vue'
import { ElMessage, ElSelect } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AccountSwitchControls from './AccountSwitchControls.vue'
import { useAuthStore } from '@/stores/auth'
import type { SwitchTarget, SwitchTargetsResponse } from '@/types/auth'
import type { AccountSwitchPhase } from '@/composables/useAccountSwitchFlow'

let flow: {
  busy: ReturnType<typeof ref<boolean>>
  phase: ReturnType<typeof ref<AccountSwitchPhase>>
  error: ReturnType<typeof ref<string>>
  switchAccount: ReturnType<typeof vi.fn>
  returnAdmin: ReturnType<typeof vi.fn>
  verifyIdentity: ReturnType<typeof vi.fn>
}
vi.mock('@/composables/useAccountSwitchFlow', () => ({ useAccountSwitchFlow: () => flow }))
const dialogStub = {
  name: 'AppWindowDialog', props: ['modelValue', 'showClose', 'minimizable', 'closeOnClickModal', 'closeOnPressEscape', 'beforeClose'],
  template: '<section v-if="modelValue" role="dialog"><slot /><footer><slot name="footer" /></footer></section>',
}
const employee: SwitchTarget = { departments: [{ id: 'dep', name: '生产部' }], roles: [{ id: 'role', name: '厂长' }], employee_id: 'employee-2', user_id: 2, username: 'worker', employee_code: 'E002', display_name: '李员工' }
const wrappers: VueWrapper[] = []
function render() {
  const wrapper = mount(AccountSwitchControls, { global: { stubs: { AppWindowDialog: dialogStub } } })
  wrappers.push(wrapper)
  return wrapper
}
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
async function open(wrapper: VueWrapper) {
  await (wrapper.vm as unknown as { openSwitchDialog: () => void }).openSwitchDialog()
  await flushPromises()
}
async function select(wrapper: VueWrapper) {
  await wrapper.get('input[type="radio"]').setValue(true)
}
function confirmDisabled(wrapper: VueWrapper) {
  return (wrapper.get('[data-confirm-switch]').element as HTMLButtonElement).disabled
}

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  flow = { busy: ref(false), phase: ref<AccountSwitchPhase>('idle'), error: ref(''),
    switchAccount: vi.fn().mockResolvedValue(false), returnAdmin: vi.fn().mockResolvedValue(false), verifyIdentity: vi.fn().mockResolvedValue(false) }
  useAuthStore().applyAuthResponse({ authenticated: true, user: {
    id: 1, username: 'admin', display_name: '真实管理员名称', is_superuser: true, employee: null, permissions: [], data_scope: 'ALL',
  }, account_switch: { active: false, can_return: false, identity_version: 'v1' } })
  vi.spyOn(useAuthStore(), 'loadSwitchTargets').mockResolvedValue({ results: [employee], identity_version: 'v1' })
  vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
})
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('全局弹窗控制器和操作边界', () => {
  it('管理员通过公开方法打开弹窗，无顶部身份栏，表格仅显示部门角色名称', async () => {
    const wrapper = render()
    expect(wrapper.find('[data-account-switch-banner]').exists()).toBe(false)
    await open(wrapper)
    expect(useAuthStore().loadSwitchTargets).toHaveBeenCalledWith(undefined, expect.any(AbortSignal), { department_id: undefined, role_id: undefined })
    const dialog = wrapper.getComponent({ name: 'AppWindowDialog' })
    expect(dialog.props('minimizable')).toBe(false)
    expect(dialog.props('closeOnClickModal')).toBe(false)
    expect(wrapper.get('input[type="radio"]').attributes('aria-label')).toBe('选择李员工')
    expect(wrapper.findAll('th').map(th => th.text())).toEqual(['名称', '部门', '角色'])
    expect(wrapper.findAll('tbody tr:first-child td').map(td => td.text())).toEqual(['李员工', '生产部', '厂长'])
    expect(wrapper.get('tbody').text()).toContain('生产部')
    expect(wrapper.get('tbody').text()).toContain('厂长')
    expect(wrapper.get('tbody').text()).not.toMatch(/E002|worker|工号|用户名/)
    expect(confirmDisabled(wrapper)).toBe(true)
    await select(wrapper)
    expect(confirmDisabled(wrapper)).toBe(false)
  })

  it('匿名也保留raw can_return入口，返回只通过flow', async () => {
    const auth = useAuthStore()
    auth.applyAuthResponse({ authenticated: false, user: null, account_switch: { active: true, can_return: true, identity_version: 'v2' } })
    const directWrite = vi.spyOn(auth, 'returnAdmin')
    const wrapper = render()
    expect(wrapper.find('[data-account-switch-banner]').exists()).toBe(false)
    await (wrapper.vm as unknown as { returnAdmin: () => Promise<void> }).returnAdmin()
    await flushPromises()
    expect(flow.returnAdmin).toHaveBeenCalledTimes(1)
    expect(directWrite).not.toHaveBeenCalled()
    expect(ElMessage.success).not.toHaveBeenCalled()
  })

  it('blocked保留返回但禁用，显示显式核验入口，失败不报成功', async () => {
    const auth = useAuthStore()
    auth.accountSwitch = { active: true, can_return: true, identity_version: 'v1' }
    auth.requireIdentityRevalidation()
    const initialize = vi.spyOn(auth, 'initialize')
    const wrapper = render()
    await (wrapper.vm as unknown as { returnAdmin: () => Promise<void> }).returnAdmin()
    expect(flow.returnAdmin).not.toHaveBeenCalled()
    expect(wrapper.find('[data-switch-entry]').exists()).toBe(false)
    expect(auth.identityRevalidationRequired).toBe(true)
    await (wrapper.vm as unknown as { verifyIdentity: () => Promise<void> }).verifyIdentity()
    await flushPromises()
    expect(flow.verifyIdentity).toHaveBeenCalledTimes(1)
    expect(initialize).not.toHaveBeenCalled()
    expect(ElMessage.success).not.toHaveBeenCalled()
    flow.verifyIdentity.mockResolvedValueOnce(true)
    await (wrapper.vm as unknown as { verifyIdentity: () => Promise<void> }).verifyIdentity()
    await flushPromises()
    expect(ElMessage.success).toHaveBeenCalledWith('已核验当前身份')
  })

  it('整个flow busy期间锁定重复切换、返回、取消、Esc及蒙层关闭', async () => {
    useAuthStore().accountSwitch = { active: true, can_return: true, identity_version: 'v1' }
    const wrapper = render()
    await open(wrapper)
    await select(wrapper)
    const mutation = deferred<boolean>()
    flow.switchAccount.mockImplementation(() => { flow.busy.value = true; flow.phase.value = 'leaving'; return mutation.promise })
    await wrapper.get('[data-confirm-switch]').trigger('click')
    expect(flow.switchAccount).toHaveBeenCalledWith('employee-2')
    await wrapper.get('[data-confirm-switch]').trigger('click')
    await (wrapper.vm as unknown as { returnAdmin: () => Promise<void> }).returnAdmin()
    await wrapper.get('[data-cancel-switch]').trigger('click')
    expect(flow.switchAccount).toHaveBeenCalledTimes(1)
    expect(flow.returnAdmin).not.toHaveBeenCalled()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    const dialog = wrapper.getComponent({ name: 'AppWindowDialog' })
    expect(dialog.props('showClose')).toBe(false)
    expect(dialog.props('minimizable')).toBe(false)
    expect(dialog.props('closeOnPressEscape')).toBe(false)
    expect(dialog.props('closeOnClickModal')).toBe(false)
    expect(wrapper.text()).toContain('正在安全离开当前页面')
    flow.busy.value = false
    mutation.resolve(false)
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(ElMessage.success).not.toHaveBeenCalled()
  })

  it('switch=false保留窗口，只有true才关闭并显示成功', async () => {
    const directWrite = vi.spyOn(useAuthStore(), 'switchAccount')
    const wrapper = render()
    await open(wrapper)
    await select(wrapper)
    await wrapper.get('[data-confirm-switch]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(ElMessage.success).not.toHaveBeenCalled()
    flow.switchAccount.mockResolvedValueOnce(true)
    await wrapper.get('[data-confirm-switch]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(ElMessage.success).toHaveBeenCalledWith('已切换员工身份')
    expect(directWrite).not.toHaveBeenCalled()
  })

  it('返回确定性失败但身份仍ready时也能显式核验，false不成功也不关闭', async () => {
    const auth = useAuthStore()
    auth.accountSwitch = { active: true, can_return: true, identity_version: 'v1' }
    const initialize = vi.spyOn(auth, 'initialize')
    flow.returnAdmin.mockImplementationOnce(async () => {
      flow.error.value = '当前无法返回管理员，请重新核验身份后再试。'
      return false
    })
    const wrapper = render()
    await open(wrapper)
    expect(wrapper.find('[data-verify-identity]').exists()).toBe(false)
    await (wrapper.vm as unknown as { returnAdmin: () => Promise<void> }).returnAdmin()
    await flushPromises()
    expect(auth.identityReady).toBe(true)
    expect(auth.canReturnAdmin).toBe(true)
    expect(auth.accountSwitch?.can_return).toBe(true)
    expect(auth.identityRevalidationRequired).toBe(false)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(ElMessage.success).not.toHaveBeenCalled()
    await (wrapper.vm as unknown as { verifyIdentity: () => Promise<void> }).verifyIdentity()
    await flushPromises()
    expect(flow.verifyIdentity).toHaveBeenCalledTimes(1)
    expect(initialize).not.toHaveBeenCalled()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(ElMessage.success).not.toHaveBeenCalled()
  })

  it('返回只有flow=true显示成功并关闭已开的选择器', async () => {
    useAuthStore().accountSwitch = { active: true, can_return: true, identity_version: 'v1' }
    flow.returnAdmin.mockResolvedValueOnce(true)
    const wrapper = render()
    await open(wrapper)
    await (wrapper.vm as unknown as { returnAdmin: () => Promise<void> }).returnAdmin()
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(ElMessage.success).toHaveBeenCalledWith('已返回管理员身份')
  })
})

describe('真实候选调用的本地竞态隔离', () => {
  it('部门/角色变化立即清除选择，中止旧请求并忽略迟到筛选结果', async () => {
    const auth = useAuthStore()
    vi.mocked(auth.loadSwitchTargets).mockResolvedValue({
      results: [employee], identity_version: 'v1', departments: employee.departments, roles: employee.roles, has_more: true,
    })
    const wrapper = render()
    await open(wrapper)
    expect(wrapper.text()).not.toContain('当前显示前')
    expect(wrapper.text()).not.toContain('选择员工后仍需确认')
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(wrapper.get('.account-switch-picker__search input').attributes('aria-describedby')).toBeUndefined()
    await select(wrapper)
    const late = deferred<SwitchTargetsResponse>()
    vi.mocked(auth.loadSwitchTargets).mockReturnValueOnce(late.promise)
    wrapper.getComponent<typeof ElSelect>('[data-department-filter]').vm.$emit('update:modelValue', 'dep')
    await nextTick()
    expect(confirmDisabled(wrapper)).toBe(true)
    await vi.advanceTimersByTimeAsync(200)
    expect(auth.loadSwitchTargets).toHaveBeenLastCalledWith(undefined, expect.any(AbortSignal), { department_id: 'dep', role_id: undefined })
    const signal = vi.mocked(auth.loadSwitchTargets).mock.calls.at(-1)![1]!
    wrapper.getComponent<typeof ElSelect>('[data-role-filter]').vm.$emit('update:modelValue', 'role')
    await nextTick()
    expect(signal.aborted).toBe(true)
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    late.resolve({ results: [{ ...employee, display_name: '旧筛选员工' }], identity_version: 'v1' })
    await flushPromises()
    expect(wrapper.text()).not.toContain('旧筛选员工')
    expect(auth.loadSwitchTargets).toHaveBeenLastCalledWith(undefined, expect.any(AbortSignal), { department_id: 'dep', role_id: 'role' })
    expect(confirmDisabled(wrapper)).toBe(true)
    await wrapper.get('[data-clear-query]').trigger('click')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    expect(auth.loadSwitchTargets).toHaveBeenLastCalledWith(undefined, expect.any(AbortSignal), { department_id: undefined, role_id: undefined })
  })

  it('搜索更改立即清除选择并禁确认，debounce尚未发出也不能提交旧员工', async () => {
    const wrapper = render()
    await open(wrapper)
    await select(wrapper)
    expect(confirmDisabled(wrapper)).toBe(false)
    await wrapper.get('input:not([type="radio"])').setValue('新搜索')
    expect(confirmDisabled(wrapper)).toBe(true)
    expect(wrapper.find('input[type="radio"]').exists()).toBe(false)
    await wrapper.get('[data-confirm-switch]').trigger('click')
    expect(flow.switchAccount).not.toHaveBeenCalled()
    expect(useAuthStore().loadSwitchTargets).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    expect(useAuthStore().loadSwitchTargets).toHaveBeenLastCalledWith('新搜索', expect.any(AbortSignal), { department_id: undefined, role_id: undefined })
    expect(confirmDisabled(wrapper)).toBe(true)
  })

  it('AbortController以外的本地序号也能丢弃后到达的旧查询', async () => {
    const oldQuery = deferred<SwitchTargetsResponse>()
    const newQuery = deferred<SwitchTargetsResponse>()
    vi.mocked(useAuthStore().loadSwitchTargets).mockReturnValueOnce(oldQuery.promise).mockReturnValueOnce(newQuery.promise)
    const wrapper = render()
    await open(wrapper)
    const oldSignal = vi.mocked(useAuthStore().loadSwitchTargets).mock.calls[0]![1]!
    expect(wrapper.text()).toContain('正在查询员工')
    await wrapper.get('input').setValue('next')
    expect(oldSignal.aborted).toBe(true)
    await vi.advanceTimersByTimeAsync(200)
    newQuery.resolve({ results: [{ ...employee, employee_id: 'new', display_name: '新查询员工' }], identity_version: 'v1' })
    await flushPromises()
    oldQuery.resolve({ results: [employee], identity_version: 'v1' })
    await flushPromises()
    expect(wrapper.text()).toContain('新查询员工')
    expect(wrapper.text()).not.toContain('李员工')
  })

  it.each(['identityVersion', 'identityGeneration', 'identityRequestGeneration'] as const)('%s改变立即使已选候选失效', async key => {
    const auth = useAuthStore()
    const wrapper = render()
    await open(wrapper)
    await select(wrapper)
    if (key === 'identityVersion') auth.accountSwitch!.identity_version = 'changed'
    else auth[key] += 1
    await nextTick()
    expect(confirmDisabled(wrapper)).toBe(true)
    expect(wrapper.find('input[type="radio"]').exists()).toBe(false)
    await wrapper.get('[data-confirm-switch]').trigger('click')
    expect(flow.switchAccount).not.toHaveBeenCalled()
  })

  it('关闭后到达的响应不恢复候选；重开不复用旧选择', async () => {
    const late = deferred<SwitchTargetsResponse>()
    vi.mocked(useAuthStore().loadSwitchTargets).mockReturnValueOnce(late.promise)
    const wrapper = render()
    await open(wrapper)
    const signal = vi.mocked(useAuthStore().loadSwitchTargets).mock.calls[0]![1]!
    await wrapper.get('[data-cancel-switch]').trigger('click')
    expect(signal.aborted).toBe(true)
    late.resolve({ results: [{ ...employee, display_name: '过期员工' }], identity_version: 'v1' })
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    await open(wrapper)
    expect(wrapper.text()).not.toContain('过期员工')
    expect(confirmDisabled(wrapper)).toBe(true)
  })

  it('身份在pending请求期间变化，迟到结果被丢弃且不会恢复选择', async () => {
    const late = deferred<SwitchTargetsResponse>()
    vi.mocked(useAuthStore().loadSwitchTargets).mockReturnValueOnce(late.promise)
    const wrapper = render()
    await open(wrapper)
    useAuthStore().identityRequestGeneration += 1
    await nextTick()
    late.resolve({ results: [employee], identity_version: 'v1' })
    await flushPromises()
    expect(wrapper.find('input[type="radio"]').exists()).toBe(false)
    expect(confirmDisabled(wrapper)).toBe(true)
  })

  it('同上下文403显示权限状态，只通过全局flow核验，不泄露后端payload', async () => {
    const auth = useAuthStore()
    const initialize = vi.spyOn(auth, 'initialize')
    vi.mocked(auth.loadSwitchTargets).mockRejectedValueOnce({
      isAxiosError: true, response: { status: 403, data: { detail: 'sensitive-backend-payload' } },
    })
    const wrapper = render()
    await open(wrapper)
    expect(wrapper.text()).toContain('当前身份无权查询可切换员工')
    expect(wrapper.text()).not.toContain('sensitive-backend-payload')
    expect(confirmDisabled(wrapper)).toBe(true)
    expect(auth.identityRevalidationRequired).toBe(false)
    await wrapper.get('[data-verify-targets]').trigger('click')
    await flushPromises()
    expect(flow.verifyIdentity).toHaveBeenCalledTimes(1)
    expect(initialize).not.toHaveBeenCalled()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    expect(ElMessage.success).not.toHaveBeenCalled()
  })

  it('失败有重试，重试后的空列表不是加载失败', async () => {
    vi.mocked(useAuthStore().loadSwitchTargets).mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ results: [], identity_version: 'v1' })
    const wrapper = render()
    await open(wrapper)
    expect(wrapper.text()).toContain('员工列表加载失败')
    await wrapper.get('[data-retry-targets]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('暂无可切换员工')
    expect(wrapper.find('[data-retry-targets]').exists()).toBe(false)
    expect(confirmDisabled(wrapper)).toBe(true)
  })

  it('搜索无结果提供清除条件，并重新调用服务器查询', async () => {
    vi.mocked(useAuthStore().loadSwitchTargets).mockResolvedValue({ results: [], identity_version: 'v1' })
    const wrapper = render()
    await open(wrapper)
    await wrapper.get('input').setValue('not-found')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    expect(wrapper.text()).toContain('没有匹配的员工')
    await wrapper.get('[data-clear-query]').trigger('click')
    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    expect(useAuthStore().loadSwitchTargets).toHaveBeenLastCalledWith(undefined, expect.any(AbortSignal), { department_id: undefined, role_id: undefined })
  })

  it('响应版本不匹配不允许确认，卸载会中止仍在进行的查询', async () => {
    vi.mocked(useAuthStore().loadSwitchTargets).mockResolvedValueOnce({ results: [employee], identity_version: 'wrong' })
    const wrapper = render()
    await open(wrapper)
    expect(wrapper.text()).toContain('身份版本已变化')
    expect(wrapper.find('input[type="radio"]').exists()).toBe(false)
    expect(confirmDisabled(wrapper)).toBe(true)
    expect(wrapper.find('[data-verify-targets]').exists()).toBe(true)
    expect(wrapper.find('[data-retry-targets]').exists()).toBe(false)
    const pending = deferred<SwitchTargetsResponse>()
    vi.mocked(useAuthStore().loadSwitchTargets).mockReturnValueOnce(pending.promise)
    flow.verifyIdentity.mockResolvedValueOnce(true)
    await wrapper.get('[data-verify-targets]').trigger('click')
    await flushPromises()
    expect(flow.verifyIdentity).toHaveBeenCalledTimes(1)
    const signal = vi.mocked(useAuthStore().loadSwitchTargets).mock.calls.at(-1)![1]!
    wrapper.unmount()
    expect(signal.aborted).toBe(true)
    pending.resolve({ results: [employee], identity_version: 'v1' })
    await flushPromises()
  })
})
