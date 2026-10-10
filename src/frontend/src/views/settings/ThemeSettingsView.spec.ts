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

  it('exposes only the approved warm theme and keeps it after initialization', async () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark')
    const wrapper = mount(ThemeSettingsView, {
      global: { plugins: [createPinia(), ElementPlus] },
    })
    await flushPromises()

    expect(wrapper.findAll('[data-theme-option]')).toHaveLength(1)
    expect(wrapper.get('[data-theme-option="warm"]').attributes('aria-pressed')).toBe('true')
    expect(document.documentElement.dataset.theme).toBe('warm')
  })

  it('persists the selected theme from the settings control', async () => {
    const wrapper = mount(ThemeSettingsView, {
      global: { plugins: [createPinia(), ElementPlus] },
    })
    await wrapper.get('[data-theme-option="warm"]').trigger('click')

    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('warm')
    expect(document.documentElement.dataset.theme).toBe('warm')
  })
})
