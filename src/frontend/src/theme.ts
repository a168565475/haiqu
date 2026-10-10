export const THEME_STORAGE_KEY = 'haiqu:theme:v1'
export const DEFAULT_THEME = 'warm' as const

// These IDs are the extension seam for later approved palettes. Only warm is
// enabled until a separate design decision supplies the other token values.
export const THEME_IDS = ['warm', 'blue-gray', 'dark'] as const
export type ThemeId = (typeof THEME_IDS)[number]
export type EnabledThemeId = typeof DEFAULT_THEME

export interface ThemeDefinition {
  id: EnabledThemeId
  label: string
  description: string
}

export const AVAILABLE_THEMES: readonly ThemeDefinition[] = [
  {
    id: DEFAULT_THEME,
    label: '暖色 ERP',
    description: '使用 HAIQU ERP 第 10 节确认的暖色界面规范。',
  },
]

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && (THEME_IDS as readonly string[]).includes(value)
}

export function isEnabledTheme(value: unknown): value is EnabledThemeId {
  return value === DEFAULT_THEME
}

function readStorage(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function readStoredTheme(storage: Storage | null = readStorage()): EnabledThemeId {
  try {
    const value = storage?.getItem(THEME_STORAGE_KEY)
    return isEnabledTheme(value) ? value : DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}

export function applyTheme(theme: ThemeId): EnabledThemeId {
  const resolved = isEnabledTheme(theme) ? theme : DEFAULT_THEME
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = resolved
    document.documentElement.dataset.themeReady = 'true'
  }
  return resolved
}

export function persistTheme(theme: EnabledThemeId, storage: Storage | null = readStorage()): void {
  try {
    storage?.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // Private browsing and blocked storage should not prevent the theme from applying.
  }
}

export function initializeTheme(): EnabledThemeId {
  const theme = readStoredTheme()
  persistTheme(theme)
  return applyTheme(theme)
}

export function setTheme(theme: ThemeId): EnabledThemeId {
  const resolved = applyTheme(theme)
  persistTheme(resolved)
  return resolved
}
