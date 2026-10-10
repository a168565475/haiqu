import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import EmailAccountSettingsView from './EmailAccountSettingsView.vue'

const api = vi.hoisted(() => ({ fetchEmailAccounts: vi.fn() }))

vi.mock('@/api/emailAccounts', () => ({
  fetchEmailAccounts: api.fetchEmailAccounts,
  fetchEmailAccount: vi.fn(),
  createEmailAccount: vi.fn(),
  updateEmailAccount: vi.fn(),
  deleteEmailAccount: vi.fn(),
  setDefaultEmailAccount: vi.fn(),
  sendEmailAccountTest: vi.fn(),
}))

describe('EmailAccountSettingsView', () => {
  beforeEach(() => {
    api.fetchEmailAccounts.mockReset()
  })

  it('展示当前账户邮箱、默认状态和测试入口', async () => {
    api.fetchEmailAccounts.mockResolvedValueOnce([{
      id: 'mail-1', display_name: '业务工作邮箱', sender_name: '业务员 A', sender_email: 'sales@example.test',
      smtp_host: 'smtp.example.test', smtp_port: 587, smtp_username: 'sales@example.test', smtp_security: 'STARTTLS',
      is_enabled: true, is_default: true, password_configured: true, last_test_status: 'SUCCESS',
      last_tested_at: '2026-08-28T08:00:00Z', created_at: '2026-08-28T08:00:00Z', updated_at: '2026-08-28T08:00:00Z',
    }])

    const wrapper = mount(EmailAccountSettingsView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain('业务工作邮箱')
    expect(wrapper.text()).toContain('sales@example.test')
    expect(wrapper.text()).toContain('默认')
    expect(wrapper.text()).toContain('更多')
  })

  it('明确提示授权码会加密保存', async () => {
    api.fetchEmailAccounts.mockResolvedValueOnce([])

    const wrapper = mount(EmailAccountSettingsView, { global: { plugins: [ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain('密码会加密保存且不会再次显示')
    expect(wrapper.text()).toContain('新增邮件账户')
  })

  it('在新增邮件账户时展示服务商教程并应用公开参数', async () => {
    api.fetchEmailAccounts.mockResolvedValueOnce([])

    const wrapper = mount(EmailAccountSettingsView, {
      global: {
        plugins: [ElementPlus],
        stubs: { teleport: true, ElSelect: true, ElOption: true },
      },
    })
    await flushPromises()
    await wrapper.get('[data-testid="create-email-account"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('第 1 步：选择邮箱服务商')
    expect(wrapper.text()).toContain('第 2 步：获取 授权码')
    expect(wrapper.text()).toContain('smtp.qq.com')
    expect(wrapper.text()).toContain('自行命名，仅用于系统内识别')

    await wrapper.get('[data-testid="provider-gmail"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('第 2 步：获取 应用专用密码')
    expect(wrapper.text()).toContain('smtp.gmail.com')
    expect(wrapper.text()).toContain('先开启两步验证')
  })

  it('明确阻止使用当前不兼容的 Outlook 现代授权', async () => {
    api.fetchEmailAccounts.mockResolvedValueOnce([])

    const wrapper = mount(EmailAccountSettingsView, {
      global: {
        plugins: [ElementPlus],
        stubs: { teleport: true, ElSelect: true, ElOption: true },
      },
    })
    await flushPromises()
    await wrapper.get('[data-testid="create-email-account"]').trigger('click')
    await wrapper.get('[data-testid="provider-outlook"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('当前系统暂不支持该邮箱')
    expect(wrapper.text()).toContain('当前 Haiqu ERP 只支持 SMTP 用户名和授权码')
    const saveButton = wrapper.findAll('button').find((button) => button.text() === '保存')
    expect(saveButton?.attributes('disabled')).toBeDefined()
  })
})
