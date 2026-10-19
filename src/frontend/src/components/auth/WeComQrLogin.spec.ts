import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { cancelWeComQrSession, createWeComQrSession, ExistingAuthSessionError } from '@/api/auth'
import type { WeComQrSession } from '@/types/auth'
import WeComQrLogin from './WeComQrLogin.vue'
import { loadWeComLoginSdk } from './wecomLoginSdk'
import type { WeComLoginSdk } from './wecomLoginSdk'

vi.mock('@/api/auth', async original => ({ ...await original<typeof import('@/api/auth')>(), createWeComQrSession: vi.fn(), cancelWeComQrSession: vi.fn() }))
vi.mock('./wecomLoginSdk', async original => ({ ...await original<typeof import('./wecomLoginSdk')>(), loadWeComLoginSdk: vi.fn() }))

let panelUnmount = vi.fn()
let createPanel = vi.fn<WeComLoginSdk['createWWLoginPanel']>()
let autoReady = true
function session(state = 'a'.repeat(43)): WeComQrSession {
  return { login_type: 'CorpApp', appid: 'ww123456789', agentid: '1000010', state, redirect_uri: `${window.location.origin}/api/auth/wecom/callback/`, expires_at: new Date(Date.now() + 300_000).toISOString() }
}

describe('企业微信扫码组件的会话生命周期', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    vi.mocked(createWeComQrSession).mockResolvedValue(session())
    vi.mocked(cancelWeComQrSession).mockResolvedValue()
    autoReady = true
    panelUnmount = vi.fn()
    createPanel = vi.fn(options => {
      const iframe = document.createElement('iframe')
      options.el.append(iframe)
      panelUnmount.mockImplementation(() => iframe.remove())
      if (autoReady) queueMicrotask(() => options.onCheckWeComLogin?.({ isWeComLogin: false }))
      return { el: iframe, unmount: panelUnmount }
    })
    vi.mocked(loadWeComLoginSdk).mockResolvedValue({ createWWLoginPanel: createPanel })
  })
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })

  it('挂载真实官方面板，保留完整small尺寸和内存state', async () => {
    const wrapper = mount(WeComQrLogin, { props: { nextPath: '/customers' } })
    await flushPromises()
    expect(createWeComQrSession).toHaveBeenCalledWith('/customers')
    expect(createPanel.mock.calls[0]![0].params).toMatchObject({ panel_size: 'small', redirect_type: 'callback', state: 'a'.repeat(43) })
    expect(wrapper.find('iframe').exists()).toBe(true)
    wrapper.unmount()
    await flushPromises()
    expect(panelUnmount).toHaveBeenCalled()
    expect(cancelWeComQrSession).toHaveBeenCalledWith('a'.repeat(43))
  })

  it('申请过程中切走：等待申请结果并取消，不让迟到结果挂载SDK', async () => {
    let resolve!: (value: WeComQrSession) => void
    vi.mocked(createWeComQrSession).mockReturnValue(new Promise(done => { resolve = done }))
    const wrapper = mount(WeComQrLogin, { props: { nextPath: '/' } })
    const cancelled = wrapper.vm.cancel()
    resolve(session())
    expect(await cancelled).toBe(true)
    await flushPromises()
    expect(cancelWeComQrSession).toHaveBeenCalledWith('a'.repeat(43))
    expect(loadWeComLoginSdk).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('取消失败阻止切换及新建，保留state供重试', async () => {
    const wrapper = mount(WeComQrLogin, { props: { nextPath: '/' } })
    await flushPromises()
    vi.mocked(cancelWeComQrSession).mockRejectedValueOnce(new Error('offline'))
    expect(await wrapper.vm.cancel()).toBe(false)
    expect(wrapper.text()).toContain('旧二维码取消失败')
    expect(createWeComQrSession).toHaveBeenCalledTimes(1)
    expect(await wrapper.vm.cancel()).toBe(true)
    expect(cancelWeComQrSession).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('到期销毁面板，刷新先取消旧state再申请新state', async () => {
    const wrapper = mount(WeComQrLogin, { props: { nextPath: '/' } })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(300_001)
    expect(wrapper.text()).toContain('二维码已失效')
    expect(panelUnmount).toHaveBeenCalled()
    createPanel.mock.calls[0]![0].onLoginFail({ errCode: 1 })
    expect(wrapper.text()).toContain('二维码已失效')
    vi.mocked(createWeComQrSession).mockResolvedValueOnce(session('b'.repeat(43)))
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(cancelWeComQrSession).toHaveBeenCalledWith('a'.repeat(43))
    expect(createPanel.mock.calls[1]![0].params.state).toBe('b'.repeat(43))
    wrapper.unmount()
  })

  it('取消后忽略旧面板迟到的成功和失败回调', async () => {
    const wrapper = mount(WeComQrLogin, { props: { nextPath: '/' } })
    await flushPromises()
    const callbacks = createPanel.mock.calls[0]![0]
    await wrapper.vm.cancel()
    callbacks.onLoginFail({ errCode: 1 })
    callbacks.onLoginSuccess({ code: 'old-code' })
    expect(wrapper.text()).not.toContain('正在验证登录信息')
    expect(wrapper.text()).not.toContain('扫码登录未完成')
    wrapper.unmount()
  })

  it('已有浏览器会话时复用会话，不加载扫码SDK', async () => {
    const response = { authenticated: true, user: null }
    vi.mocked(createWeComQrSession).mockRejectedValue(new ExistingAuthSessionError(response))
    const wrapper = mount(WeComQrLogin, { props: { nextPath: '/' } })
    await flushPromises()
    expect(wrapper.emitted('authenticated')).toEqual([[response]])
    expect(loadWeComLoginSdk).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('SDK加载过程中切走：取消state后迟到SDK不再创建面板', async () => {
    let resolve!: (value: WeComLoginSdk) => void
    vi.mocked(loadWeComLoginSdk).mockReturnValue(new Promise(done => { resolve = done }))
    const wrapper = mount(WeComQrLogin, { props: { nextPath: '/' } })
    await flushPromises()
    expect(await wrapper.vm.cancel()).toBe(true)
    wrapper.unmount()
    resolve({ createWWLoginPanel: createPanel })
    await flushPromises()
    expect(createPanel).not.toHaveBeenCalled()
    expect(cancelWeComQrSession).toHaveBeenCalledWith('a'.repeat(43))
    expect(cancelWeComQrSession).toHaveBeenCalledOnce()
  })

  it('iframe立即可见，桌面端探测回调只确认通讯，false同样有效', async () => {
    autoReady = false
    const wrapper = mount(WeComQrLogin, { props: { nextPath: '/' } })
    await flushPromises()
    expect(wrapper.get('.wecom-panel').isVisible()).toBe(true)
    expect(wrapper.attributes('data-panel-communication')).toBe('pending')
    expect(wrapper.get('.wecom-refresh').text()).toBe('刷新二维码')
    createPanel.mock.calls[0]![0].onCheckWeComLogin({ isWeComLogin: false })
    await flushPromises()
    expect(wrapper.attributes('data-panel-communication')).toBe('confirmed')
    expect(wrapper.get('.wecom-refresh').text()).toBe('刷新二维码')
    wrapper.unmount()
  })

  it('桌面探测慢时不隐藏二维码，长时间无回调仅软提示，迟到回调仍确认通讯', async () => {
    autoReady = false
    const wrapper = mount(WeComQrLogin, { props: { nextPath: '/' } })
    await flushPromises()
    const oldCallbacks = createPanel.mock.calls[0]![0]
    await vi.advanceTimersByTimeAsync(60_001)
    expect(wrapper.get('.wecom-panel').isVisible()).toBe(true)
    expect(wrapper.find('.wecom-panel-hint').exists()).toBe(false)
    await vi.advanceTimersByTimeAsync(15_000)
    expect(wrapper.text()).toContain('若二维码未显示')
    expect(wrapper.get('.wecom-panel').isVisible()).toBe(true)
    expect(panelUnmount).not.toHaveBeenCalled()
    oldCallbacks.onCheckWeComLogin({ isWeComLogin: true })
    await flushPromises()
    expect(wrapper.find('.wecom-panel-hint').exists()).toBe(false)
    expect(wrapper.attributes('data-panel-communication')).toBe('confirmed')
    expect(createPanel).toHaveBeenCalledOnce()
    expect(wrapper.get('.wecom-refresh').text()).toBe('刷新二维码')
    wrapper.unmount()
  })

  it('软提示后仍可刷新，先取消旧state，旧面板握手不能确认新面板', async () => {
    autoReady = false
    const wrapper = mount(WeComQrLogin, { props: { nextPath: '/' } })
    await flushPromises()
    const oldCallbacks = createPanel.mock.calls[0]![0]
    await vi.advanceTimersByTimeAsync(75_001)
    vi.mocked(createWeComQrSession).mockResolvedValueOnce(session('b'.repeat(43)))
    await wrapper.get('.wecom-refresh').trigger('click')
    await flushPromises()
    expect(cancelWeComQrSession).toHaveBeenCalledWith('a'.repeat(43))
    expect(createPanel.mock.calls[1]![0].params.state).toBe('b'.repeat(43))
    oldCallbacks.onCheckWeComLogin({ isWeComLogin: true })
    expect(wrapper.attributes('data-panel-communication')).toBe('pending')
    createPanel.mock.calls[1]![0].onCheckWeComLogin({ isWeComLogin: false })
    await flushPromises()
    expect(wrapper.attributes('data-panel-communication')).toBe('confirmed')
    wrapper.unmount()
  })

  it('合法扫码成功可以早于桌面端探测回调，不等待onCheck再进入后端验证', async () => {
    autoReady = false
    const wrapper = mount(WeComQrLogin, { props: { nextPath: '/' } })
    await flushPromises()
    const actualWindow = window
    const navigate = vi.fn()
    vi.stubGlobal('window', new Proxy(actualWindow, {
      get(target, key) {
        if (key === 'location') return { origin: actualWindow.location.origin, assign: navigate }
        return Reflect.get(target, key)
      },
    }))
    try {
      createPanel.mock.calls[0]![0].onLoginSuccess({ code: 'valid-code-before-desktop-probe' })
      await flushPromises()
      expect(navigate).toHaveBeenCalledOnce()
      const callback = new URL(navigate.mock.calls[0]![0] as string)
      expect(callback.origin).toBe(actualWindow.location.origin)
      expect(callback.pathname).toBe('/api/auth/wecom/callback/')
      expect(callback.searchParams.get('state')).toBe('a'.repeat(43))
      expect(callback.searchParams.get('code')).toBe('valid-code-before-desktop-probe')
      expect(wrapper.text()).toContain('正在验证登录信息')
    } finally {
      vi.unstubAllGlobals()
      wrapper.unmount()
    }
    expect(cancelWeComQrSession).not.toHaveBeenCalled()
  })

  it('初始化等待中卸载清除两个定时器，迟到握手不能更新页面', async () => {
    autoReady = false
    const wrapper = mount(WeComQrLogin, { props: { nextPath: '/' } })
    await flushPromises()
    expect(vi.getTimerCount()).toBe(2)
    const callback = createPanel.mock.calls[0]![0]
    wrapper.unmount()
    await flushPromises()
    expect(vi.getTimerCount()).toBe(0)
    callback.onCheckWeComLogin({ isWeComLogin: false })
    await vi.advanceTimersByTimeAsync(16_000)
    expect(createPanel).toHaveBeenCalledOnce()
    expect(cancelWeComQrSession).toHaveBeenCalledOnce()
  })
})
