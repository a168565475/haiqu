import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import ThemeSettingsView from './ThemeSettingsView.vue'
import { THEME_STORAGE_KEY } from '@/theme'

describe('ThemeSettingsView', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('提供三种主题并恢复用户选择的深色主题', async () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark')
    const wrapper = mount(ThemeSettingsView, {
      global: { plugins: [createPinia(), ElementPlus] },
    })
    await flushPromises()

    expect(wrapper.findAll('[data-theme-option]').map(option => option.attributes('data-theme-option')))
      .toEqual(['blue-gray', 'warm', 'dark'])
    expect(wrapper.get('[data-theme-option="blue-gray"]').attributes('aria-pressed')).toBe('false')
    expect(wrapper.get('[data-theme-option="dark"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-theme-option="warm"]').attributes('aria-pressed')).toBe('false')
    expect(wrapper.get('[data-theme-option="blue-gray"] [data-theme-preview]').attributes('data-theme-preview')).toBe('blue-gray')
    expect(wrapper.get('[data-theme-option="warm"] [data-theme-preview]').attributes('data-theme-preview')).toBe('warm')
    expect(document.documentElement.dataset.theme).toBe('dark')
    wrapper.unmount()
  })

  it('通过设置切换后持久化，重新进入页面仍保留选择并可切回冷蓝银', async () => {
    const wrapper = mount(ThemeSettingsView, {
      global: { plugins: [createPinia(), ElementPlus] },
    })
    await wrapper.get('[data-theme-option="warm"]').trigger('click')

    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('warm')
    expect(document.documentElement.dataset.theme).toBe('warm')
    wrapper.unmount()
    const reopened = mount(ThemeSettingsView, {
      global: { plugins: [createPinia(), ElementPlus] },
    })
    await flushPromises()
    expect(reopened.get('[data-theme-option="warm"]').attributes('aria-pressed')).toBe('true')
    await reopened.get('[data-theme-option="blue-gray"]').trigger('click')
    expect(reopened.get('[data-theme-option="blue-gray"]').attributes('aria-pressed')).toBe('true')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('blue-gray')
    expect(document.documentElement.dataset.theme).toBe('blue-gray')
    reopened.unmount()
  })
})
