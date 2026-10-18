// v1 曾自动保存唯一的暖色主题；使用新键让首次升级采用已确认的新默认值。
export const THEME_STORAGE_KEY = 'haiqu:theme:v2'
export const DEFAULT_THEME = 'blue-gray' as const

// 深色保留扩展标识，取得配色确认前不加入可用主题。
export const THEME_IDS = ['warm', 'blue-gray', 'dark'] as const
export type ThemeId = (typeof THEME_IDS)[number]
const ENABLED_THEME_IDS = ['blue-gray', 'warm'] as const
export type EnabledThemeId = (typeof ENABLED_THEME_IDS)[number]

export interface ThemeDefinition {
  id: EnabledThemeId
  label: string
  description: string
}

export const AVAILABLE_THEMES: readonly ThemeDefinition[] = [
  {
    id: DEFAULT_THEME,
    label: '冷蓝银',
    description: '冷蓝银渐变、通透卡片与钢蓝强调色。',
  },
  {
    id: 'warm',
    label: '暖色 ERP',
    description: '米白底色、暖灰边框与橙色强调色。',
  },
]

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === 'string' && (THEME_IDS as readonly string[]).includes(value)
}

export function isEnabledTheme(value: unknown): value is EnabledThemeId {
  return typeof value === 'string' && (ENABLED_THEME_IDS as readonly string[]).includes(value)
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
    // 隐私模式或存储受限时，仍允许本次界面切换。
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
