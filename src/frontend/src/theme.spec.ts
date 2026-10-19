import { createPinia } from 'pinia'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useThemeStore } from './stores/theme'

import {
  THEME_STORAGE_KEY,
  initializeTheme,
  readStoredTheme,
  setTheme,
} from './theme'

describe('主题运行时', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
    document.documentElement.removeAttribute('data-theme-ready')
  })
  afterEach(() => vi.restoreAllMocks())

  it('首次升级忽略旧版强制暖色值，之后保留用户在新版选择的暖色', () => {
    localStorage.setItem('haiqu:theme:v1', 'warm')
    expect(initializeTheme()).toBe('blue-gray')
    expect(localStorage.getItem('haiqu:theme:v2')).toBe('blue-gray')
    expect(localStorage.getItem('haiqu:theme:v1')).toBe('warm')

    setTheme('warm')
    expect(initializeTheme()).toBe('warm')
    expect(document.documentElement.dataset.theme).toBe('warm')
    expect(localStorage.getItem('haiqu:theme:v2')).toBe('warm')
  })

  it.each(['warm', 'blue-gray', 'dark'] as const)('应用并持久化可用的 %s 主题', (theme) => {
    expect(setTheme(theme)).toBe(theme)
    expect(document.documentElement.dataset.theme).toBe(theme)
    expect(document.documentElement.dataset.themeReady).toBe('true')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe(theme)
    expect(readStoredTheme()).toBe(theme)
    expect(initializeTheme()).toBe(theme)
  })

  it.each(['unknown-theme', '{broken-json'])('存储中的 %s 无效时回退冷蓝银并修正新版存储', (value) => {
    localStorage.setItem(THEME_STORAGE_KEY, value)
    expect(readStoredTheme()).toBe('blue-gray')
    expect(initializeTheme()).toBe('blue-gray')
    expect(document.documentElement.dataset.theme).toBe('blue-gray')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('blue-gray')
  })

  it('深色主题可从暖色切换并保留选择', () => {
    setTheme('warm')
    expect(setTheme('dark')).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(readStoredTheme()).toBe('dark')
  })

  it('浏览器禁止读取存储时仍应用默认主题', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('读取被阻止') })
    expect(initializeTheme()).toBe('blue-gray')
    expect(document.documentElement.dataset.theme).toBe('blue-gray')
  })

  it('无法取得localStorage时仍可初始化和切换已确认主题', () => {
    vi.spyOn(window, 'localStorage', 'get').mockImplementation(() => { throw new Error('存储不可访问') })
    expect(initializeTheme()).toBe('blue-gray')
    expect(setTheme('warm')).toBe('warm')
    expect(document.documentElement.dataset.theme).toBe('warm')
    expect(readStoredTheme(null)).toBe('blue-gray')
  })

  it('存储写入失败不阻止本次主题切换', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('配额已满') })
    expect(setTheme('warm')).toBe('warm')
    expect(document.documentElement.dataset.theme).toBe('warm')
  })

  it('暖色判断跟随当前主题，重置恢复冷蓝银并持久化', () => {
    const store = useThemeStore(createPinia())
    store.initialize()
    expect(store.isWarm).toBe(false)
    store.select('warm')
    expect(store.isWarm).toBe(true)
    store.reset()
    expect(store.current).toBe('blue-gray')
    expect(store.isWarm).toBe(false)
    expect(document.documentElement.dataset.theme).toBe('blue-gray')
    expect(readStoredTheme()).toBe('blue-gray')
  })

  it('业务弹窗不再被详情和表单路由注入玻璃材质', () => {
    const detailControls = readFileSync(resolve(__dirname, 'styles/theme/_detail-controls.scss'), 'utf8')
    expect(detailControls).not.toMatch(/\.app-window-dialog\.el-dialog[\s\S]*@include detail\.surface/)
    expect(detailControls).not.toMatch(/\.el-overlay :is\(\.el-dialog, \.el-drawer\)[\s\S]*@include detail\.surface/)
  })

  it('所有业务弹窗采用平面表单，表格仅保留紧凑尺寸，纸面保持例外', () => {
    const controls = readFileSync(resolve(__dirname, 'styles/theme/_controls.scss'), 'utf8')
    const popup = controls.slice(controls.indexOf('body .app-window-dialog'), controls.indexOf('\n.el-table {'))

    expect(popup).toContain('body .app-window-dialog.el-dialog, body .el-message-box, body .erp-table-editor, body .erp-flat-form {')
    expect(popup).toContain('height: 32px !important')
    expect(popup).toContain('padding: 0 10px !important')
    expect(popup).toContain('border-radius: 5px !important')
    expect(popup).toContain('font-size: 13px !important')
    expect(popup).toContain('background: var(--erp-color-surface) !important')
    expect(popup).not.toContain('var(--erp-input-shadow)')
    expect(popup).not.toContain('var(--erp-input-surface)')
    expect(popup).not.toContain('.customer-create-dialog')
    expect(popup).toContain('var(--erp-dialog-input-focus-border)')
    expect(popup).not.toContain('.contract-sheet *, .el-table *')
    expect(popup).toContain('&:not(:where(.el-table *, .erp-table-editor *))')
    expect(popup).toContain('.paper *')
    expect(controls).toContain('.el-input__wrapper, .el-select__wrapper { background: var(--erp-input-surface); }')
  })
})
