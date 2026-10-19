import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'

import LoginView from './LoginView.vue'

const mocks = vi.hoisted(() => ({ replace: vi.fn(), login: vi.fn(), applyAuthResponse: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ replace: mocks.replace }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => mocks }))

describe('登录方式切换', () => {
  it('默认账号密码，主动切换扫码，返回时保留输入', async () => {
    const wrapper = mount(LoginView, {
      global: { plugins: [ElementPlus], stubs: {
        LoginFlowIllustration: true,
        WeComQrLogin: { template: '<div data-qr-login />', methods: { cancel: async () => true } },
      } },
    })
    try {
      await wrapper.get('input[aria-label="账号"]').setValue('my-account')
      await wrapper.get('input[aria-label="密码"]').setValue('not-a-real-password')
      expect(wrapper.find('[data-qr-login]').exists()).toBe(false)
      expect(wrapper.find('button[aria-label="切换企业微信扫码登录"]').exists()).toBe(true)
      await wrapper.get('button[aria-label="切换企业微信扫码登录"]').trigger('click')
      await flushPromises()
      expect(wrapper.find('[data-qr-login]').exists()).toBe(true)
      await wrapper.get('button[aria-label="切换账号密码登录"]').trigger('click')
      await flushPromises()
      expect((wrapper.get('input[aria-label="账号"]').element as HTMLInputElement).value).toBe('my-account')
      expect((wrapper.get('input[aria-label="密码"]').element as HTMLInputElement).value).toBe('not-a-real-password')
    } finally { wrapper.unmount() }
  })

  it('二维码取消失败时保留扫码页，不能伪装已切换账号登录', async () => {
    const cancel = vi.fn().mockResolvedValue(false)
    const wrapper = mount(LoginView, {
      global: { plugins: [ElementPlus], stubs: {
        LoginFlowIllustration: true,
        WeComQrLogin: { template: '<div data-qr-login />', methods: { cancel } },
      } },
    })
    try {
      await wrapper.get('button[aria-label="切换企业微信扫码登录"]').trigger('click')
      await wrapper.get('button[aria-label="切换账号密码登录"]').trigger('click')
      await flushPromises()
      expect(cancel).toHaveBeenCalledOnce()
      expect(wrapper.find('[data-qr-login]').exists()).toBe(true)
      expect(wrapper.find('button[aria-label="切换账号密码登录"]').exists()).toBe(true)
    } finally { wrapper.unmount() }
  })
})
