import { beforeEach, describe, expect, it } from 'vitest'

import {
  DEFAULT_THEME,
  THEME_STORAGE_KEY,
  initializeTheme,
  readStoredTheme,
  setTheme,
} from './theme'

describe('theme runtime', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
    document.documentElement.removeAttribute('data-theme-ready')
  })

  it('falls back to warm when storage contains an unavailable theme', () => {
    localStorage.setItem(THEME_STORAGE_KEY, 'dark')

    expect(readStoredTheme()).toBe(DEFAULT_THEME)
    expect(initializeTheme()).toBe(DEFAULT_THEME)
    expect(document.documentElement.dataset.theme).toBe(DEFAULT_THEME)
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe(DEFAULT_THEME)
  })

  it('applies and persists the selected approved theme', () => {
    expect(setTheme(DEFAULT_THEME)).toBe(DEFAULT_THEME)

    expect(document.documentElement.dataset.theme).toBe(DEFAULT_THEME)
    expect(document.documentElement.dataset.themeReady).toBe('true')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe(DEFAULT_THEME)
  })
})
