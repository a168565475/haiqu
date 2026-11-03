import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WaitingRoleView from './WaitingRoleView.vue'
import { useAuthStore } from '@/stores/auth'

const env = vi.hoisted(() => ({ inWeCom: false }))
vi.mock('vue-router', () => ({ useRouter: () => ({ replace: vi.fn() }) }))
vi.mock('@/utils/wecom', () => ({ isWeComBrowser: () => env.inWeCom }))
beforeEach(() => {
  env.inWeCom = false
  setActivePinia(createPinia())
  useAuthStore().applyAuthResponse({ authenticated: true, user: {
    id: 2, username: 'waiting-worker', display_name: '等待授权员工', is_superuser: false,
    employee: { id: 'employee-2', employee_code: 'E002', display_name: '等待授权员工', status: 'ACTIVE' },
    permissions: [], data_scope: 'NONE', waiting_for_role: true,
  }, account_switch: { active: false, can_return: false, identity_version: 'v1' } })
})

describe('等待角色文案不误导切换身份来源', () => {
  it('切换后的员工账号不冒充企业微信身份，返回使用上方全局控制器', () => {
    useAuthStore().accountSwitch = { active: true, can_return: true, identity_version: 'v2' }
    const wrapper = mount(WaitingRoleView)
    expect(wrapper.text()).toContain('当前正在使用切换后的员工账号')
    expect(wrapper.text()).toContain('使用上方入口返回管理员')
    expect(wrapper.text()).not.toContain('当前账号已关联企业微信身份')
    expect(wrapper.get('dl').text()).toContain('当前身份切换后的员工账号')
    expect(wrapper.find('[data-return-admin]').exists()).toBe(false)
    wrapper.unmount()
  })
  it('未切换仍保留既有企业微信待授权含义', () => {
    const wrapper = mount(WaitingRoleView)
    expect(wrapper.text()).toContain('当前账号已关联企业微信身份')
    expect(wrapper.get('dl').text()).toContain('关联身份企业微信')
    expect(wrapper.text()).toContain('等待授权员工')
    wrapper.unmount()
  })
  it('企业微信禁止退出不影响全局切换身份来源文案', () => {
    env.inWeCom = true
    useAuthStore().accountSwitch = { active: true, can_return: true, identity_version: 'v2' }
    const wrapper = mount(WaitingRoleView)
    expect(wrapper.find('[data-action="logout"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('切换后的员工账号')
    expect(wrapper.text()).toContain('返回管理员')
    wrapper.unmount()
  })
})
