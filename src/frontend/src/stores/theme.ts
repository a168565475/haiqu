import { defineStore } from 'pinia'

import {
  applyTheme,
  AVAILABLE_THEMES,
  DEFAULT_THEME,
  initializeTheme,
  persistTheme,
  readStoredTheme,
  setTheme,
  type EnabledThemeId,
  type ThemeId,
} from '@/theme'

export const useThemeStore = defineStore('theme', {
  state: () => ({
    current: readStoredTheme() as EnabledThemeId,
    initialized: false,
  }),
  getters: {
    availableThemes: () => AVAILABLE_THEMES,
    isWarm: (state) => state.current === 'warm',
  },
  actions: {
    initialize() {
      this.current = initializeTheme()
      this.initialized = true
      return this.current
    },
    select(theme: ThemeId) {
      this.current = setTheme(theme)
      this.initialized = true
      return this.current
    },
    reset() {
      this.current = DEFAULT_THEME
      applyTheme(DEFAULT_THEME)
      persistTheme(DEFAULT_THEME)
      this.initialized = true
    },
  },
})
