import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import type { AccessScope } from '@/types/access'
import { canOpenSystemSetting, systemSettings, type SystemSettingsKey } from './systemSettings'

function available() {
  return systemSettings.filter(entry => canOpenSystemSetting(useAuthStore(), entry.key)).map(entry => entry.key)
}
function grantManagement(code: string, source = 'ROLE', scope: AccessScope = 'MODULE') {
  useAuthStore().user!.effective_access = { active: true, is_superuser: false, roles: [], legacy_sources: [], version: 'test',
    actions: { [code]: { scopes: [scope], sources: [{ type: source, scope }] } } }
}
beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'worker', display_name: '测试员工', is_superuser: false,
    employee: { id: 'worker', employee_code: 'EMP-TEST', display_name: '测试员工', status: 'ACTIVE' }, permissions: [], data_scope: 'OWN' } })
})

describe('系统配置卡片访问范围', () => {
  it('普通在职员工可管理自己的邮件和主题，不依赖字典权限', () => {
    expect(available()).toEqual(['email', 'theme'])
    useAuthStore().user!.employee = null
    expect(available()).toEqual(['theme'])
  })
  it('未登录与待分配角色状态不展示配置入口', () => {
    useAuthStore().user!.waiting_for_role = true
    expect(available()).toEqual([])
    useAuthStore().clearAuthentication()
    expect(available()).toEqual([])
  })
  it.each([
    ['reference_data.view_tubeshape', 'production'],
    ['reference_data.view_country', 'masterData'],
    ['workflow.view_slapolicy', 'inquiry'],
    ['reference_data.view_numberrule', 'numberRules'],
    ['reference_data.view_dictionarytype', 'dictionary'],
    ['reference_data.view_referencedictionary', 'dictionary'],
    ['reference_data.view_systemparameterdefinition', 'parameters'],
  ] as const)('%s 只新增对应的 %s 入口', (permission, key) => {
    useAuthStore().user!.permissions = [permission]
    expect(available().filter(value => value !== 'email' && value !== 'theme')).toEqual([key])
  })
  it.each([
    ['access_control.manage_wecom', 'wecom'],
    ['access_control.manage_notifications', 'notifications'],
  ] as const)('%s 只能通过有效角色的模块范围访问', (permission, key) => {
    const auth = useAuthStore()
    auth.user!.permissions = [permission]
    expect(canOpenSystemSetting(auth, key)).toBe(false)
    grantManagement(permission, 'DIRECT')
    expect(canOpenSystemSetting(auth, key)).toBe(false)
    grantManagement(permission, 'ROLE', 'OWN')
    expect(canOpenSystemSetting(auth, key)).toBe(false)
    grantManagement(permission)
    expect(canOpenSystemSetting(auth, key)).toBe(true)
    auth.user!.effective_access!.active = false
    expect(canOpenSystemSetting(auth, key)).toBe(false)
    auth.user!.effective_access!.active = true
    auth.user!.employee!.status = 'INACTIVE'
    expect(canOpenSystemSetting(auth, key)).toBe(false)
  })
  it.each(['organizations.manage_organization', 'access_control.manage_access', 'access_control.manage_accounts', 'access_control.manage_wecom'])('%s 可以读取权限目录，不需字典权限', permission => {
    grantManagement(permission)
    expect(canOpenSystemSetting(useAuthStore(), 'access')).toBe(true)
    expect(canOpenSystemSetting(useAuthStore(), 'dictionary')).toBe(false)
  })
  it('非admin超级用户不能越过管理角色判定，admin仍沿用现有管理例外', () => {
    const auth = useAuthStore()
    auth.user!.is_superuser = true
    const managementKeys: SystemSettingsKey[] = ['wecom', 'notifications', 'access']
    expect(managementKeys.map(key => canOpenSystemSetting(auth, key))).toEqual([false, false, false])
    auth.user!.username = 'admin'
    expect(managementKeys.map(key => canOpenSystemSetting(auth, key))).toEqual([true, true, true])
  })
})
