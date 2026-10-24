import { DOMWrapper, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import AppWindowDialog from './AppWindowDialog.vue'

afterEach(() => {
  document.body.innerHTML = ''
  document.body.style.overflow = ''
})

describe('AppWindowDialog', () => {
  it('支持调用方尺寸、最小化、最大化和关闭', async () => {
    const wrapper = mount(AppWindowDialog, {
      attachTo: document.body,
      props: { modelValue: true, title: '客户窗口', width: 520, height: 360 },
      slots: { default: '<div>窗口内容</div>', footer: '<button>保存</button>' },
    })

    const dialog = document.querySelector<HTMLElement>('.app-window-dialog')
    expect(dialog).not.toBeNull()
    expect(dialog?.style.width).toBe('520px')
    expect(dialog?.style.height).toBe('360px')

    await new DOMWrapper(document.querySelector('[aria-label="最小化"]') as Element).trigger('click')
    expect(dialog?.classList.contains('is-minimized')).toBe(true)
    expect(document.querySelector<HTMLElement>('.app-window-dialog__body')?.style.display).toBe('none')

    await new DOMWrapper(document.querySelector('[aria-label="最大化"]') as Element).trigger('click')
    expect(dialog?.classList.contains('is-maximized')).toBe(true)

    await new DOMWrapper(document.querySelector('[aria-label="关闭"]') as Element).trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    wrapper.unmount()
  })

  it('提供拖动和缩放控制并在关闭时恢复页面滚动', async () => {
    const wrapper = mount(AppWindowDialog, {
      attachTo: document.body,
      props: { modelValue: true, title: '可调整窗口', minWidth: 400, minHeight: 260 },
    })

    expect(document.body.style.overflow).toBe('hidden')
    expect(document.querySelector('.app-window-dialog__header')?.classList.contains('app-window-dialog__header')).toBe(true)
    expect(document.querySelector('.app-window-dialog__resize-handle')?.getAttribute('aria-label')).toBe('调整窗口大小')

    await wrapper.setProps({ modelValue: false })
    expect(document.body.style.overflow).toBe('')
    wrapper.unmount()
  })

  it('多个窗口分别持有页面滚动锁，最后一个关闭后才恢复', async () => {
    document.body.style.overflow = 'scroll'
    const first = mount(AppWindowDialog, {
      attachTo: document.body,
      props: { modelValue: true, title: '第一个窗口' },
    })
    const second = mount(AppWindowDialog, {
      attachTo: document.body,
      props: { modelValue: true, title: '第二个窗口' },
    })

    expect(document.body.style.overflow).toBe('hidden')
    first.unmount()
    expect(document.body.style.overflow).toBe('hidden')
    second.unmount()
    expect(document.body.style.overflow).toBe('scroll')
  })

  it('showClose 只隐藏关闭按钮，不阻断 Escape 关闭，并保留遮罩类', async () => {
    const wrapper = mount(AppWindowDialog, {
      attachTo: document.body,
      props: {
        modelValue: true,
        title: '无关闭按钮窗口',
        showClose: false,
        closeOnPressEscape: true,
        modalClass: 'custom-window-backdrop',
      },
    })

    const overlay = document.querySelector('.app-window-overlay') as Element
    expect(document.querySelector('[aria-label="关闭"]')).toBeNull()
    expect(overlay.classList.contains('custom-window-backdrop')).toBe(true)
    await new DOMWrapper(overlay).trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    wrapper.unmount()
  })

  it('支持调用方以 fullscreen 初始最大化，并可还原到传入尺寸', async () => {
    const wrapper = mount(AppWindowDialog, {
      attachTo: document.body,
      props: { modelValue: true, title: '初始全屏窗口', width: 520, height: 360, fullscreen: true },
    })
    await wrapper.vm.$nextTick()
    await wrapper.vm.$nextTick()

    const dialog = document.querySelector<HTMLElement>('.app-window-dialog')
    expect(dialog?.classList.contains('is-maximized')).toBe(true)
    expect(dialog?.style.left).toBe('16px')
    expect(dialog?.style.top).toBe('16px')
    expect(document.querySelector<HTMLElement>('.app-window-dialog__resize-handle')?.style.display).toBe('none')

    await new DOMWrapper(document.querySelector('[aria-label="还原"]') as Element).trigger('click')
    expect(dialog?.classList.contains('is-normal')).toBe(true)
    expect(dialog?.style.width).toBe('520px')
    expect(dialog?.style.height).toBe('360px')
    wrapper.unmount()
  })

  it('配置窗口可铺满视口并还原后再最大化', async () => {
    const wrapper = mount(AppWindowDialog, {
      attachTo: document.body,
      props: { modelValue: true, title: '配置窗口', width: 520, height: 360, fullscreen: true, edgeToEdge: true },
    })
    await nextTick()
    const dialog = document.querySelector<HTMLElement>('.app-window-dialog')!
    expect([dialog.style.left, dialog.style.top, dialog.style.width, dialog.style.height])
      .toEqual(['0px', '0px', `${window.innerWidth}px`, `${window.innerHeight}px`])
    await new DOMWrapper(document.querySelector('[aria-label="还原"]') as Element).trigger('click')
    expect([dialog.style.width, dialog.style.height]).toEqual(['520px', '360px'])
    await new DOMWrapper(document.querySelector('[aria-label="最大化"]') as Element).trigger('click')
    expect([dialog.style.left, dialog.style.top, dialog.style.width, dialog.style.height])
      .toEqual(['0px', '0px', `${window.innerWidth}px`, `${window.innerHeight}px`])
    wrapper.unmount()
  })

  it('兼容抽屉迁移的 header 插槽，并支持无标题栏的详情窗口', async () => {
    const wrapper = mount(AppWindowDialog, {
      attachTo: document.body,
      props: { modelValue: true, title: '迁移窗口', width: 520, height: 300 },
      slots: { header: '<div class="legacy-header">任职历史</div>' },
    })

    expect(document.querySelector('.legacy-header')?.textContent).toBe('任职历史')
    expect(document.querySelector('.app-window-dialog__header')).not.toBeNull()

    await wrapper.setProps({ withHeader: false })
    expect(document.querySelector('.app-window-dialog__header')).toBeNull()
    wrapper.unmount()
  })
})

describe('AppWindowDialog 普通窗口高度计算', () => {
  const mountedWindows: Array<{ unmount: () => void }> = []

  afterEach(() => {
    mountedWindows.splice(0).forEach(wrapper => wrapper.unmount())
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  // jsdom 不排版：这里提供受控几何，只验证窗口算法；滚动和 CSS 仍需真实浏览器验收。
  function measuredWindow(contentHeight: number, height: number | 'auto' = 'auto', fullscreen = false, autoMaxHeightRatio?: number) {
    vi.stubGlobal('innerWidth', 1200)
    vi.stubGlobal('innerHeight', 900)
    let naturalHeight = contentHeight
    let frameId = 0
    const frames = new Map<number, FrameRequestCallback>()
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.set(++frameId, callback)
      return frameId
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id))

    const observers = new Set<ControlledResizeObserver>()
    class ControlledResizeObserver implements ResizeObserver {
      readonly targets = new Set<Element>()
      constructor(readonly callback: ResizeObserverCallback) { observers.add(this) }
      observe(target: Element) { this.targets.add(target) }
      unobserve(target: Element) { this.targets.delete(target) }
      disconnect() { this.targets.clear() }
    }
    vi.stubGlobal('ResizeObserver', ControlledResizeObserver)

    const originalRect = HTMLElement.prototype.getBoundingClientRect
    const originalClientRects = HTMLElement.prototype.getClientRects
    const originalStyle = window.getComputedStyle.bind(window)
    const naturalWindowHeight = () => 44 + 20 + naturalHeight + 20 + 47 + 2
    const dialogRect = (element: HTMLElement) => new DOMRect(
      Number.parseFloat(element.style.left) || 0,
      Number.parseFloat(element.style.top) || 0,
      Number.parseFloat(element.style.width) || 520,
      Number.parseFloat(element.style.height) || naturalWindowHeight(),
    )
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('app-window-dialog')) return dialogRect(this)
      const dialog = this.closest<HTMLElement>('.app-window-dialog')
      if (!dialog) return originalRect.call(this)
      const bounds = dialogRect(dialog)
      if (this.classList.contains('app-window-dialog__header')) {
        return new DOMRect(bounds.x + 1, bounds.y + 1, bounds.width - 2, 44)
      }
      if (this.classList.contains('app-window-dialog__footer')) {
        return new DOMRect(bounds.x + 1, bounds.bottom - 48, bounds.width - 2, 47)
      }
      if (this.classList.contains('app-window-dialog__body')) {
        return new DOMRect(bounds.x + 1, bounds.y + 45, bounds.width - 2, Math.max(0, bounds.height - 93))
      }
      if (this.hasAttribute('data-geometry-content')) {
        const body = this.parentElement as HTMLElement
        return new DOMRect(bounds.x + 25, bounds.y + 65 - body.scrollTop, bounds.width - 50, naturalHeight)
      }
      return originalRect.call(this)
    })
    vi.spyOn(HTMLElement.prototype, 'getClientRects').mockImplementation(function (this: HTMLElement) {
      if (!this.hasAttribute('data-geometry-content')) return originalClientRects.call(this)
      const bounds = this.getBoundingClientRect()
      return Object.assign([bounds], { item: (index: number) => index === 0 ? bounds : null })
    })
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('app-window-dialog__header')) return 44
      if (this.classList.contains('app-window-dialog__footer')) return 47
      return Math.round(this.getBoundingClientRect().height)
    })
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function (this: HTMLElement) {
      const border = this.classList.contains('app-window-dialog') ? 2 : 0
      return Math.max(0, Math.round(this.getBoundingClientRect().height) - border)
    })
    vi.spyOn(window, 'getComputedStyle').mockImplementation((element, pseudo) => {
      const style = originalStyle(element, pseudo)
      if (element.classList.contains('app-window-dialog__body')) {
        style.paddingTop = '20px'
        style.paddingBottom = '20px'
      }
      return style
    })

    const wrapper = mount(AppWindowDialog, {
      attachTo: document.body,
      props: { modelValue: true, title: '受控几何窗口', width: 520, height, fullscreen, autoMaxHeightRatio },
      slots: { default: '<article data-geometry-content>受控内容</article>', footer: '<button>确定</button>' },
    })
    mountedWindows.push(wrapper)
    const dialog = document.querySelector<HTMLElement>('.app-window-dialog')!

    async function settleFrames() {
      for (let index = 0; index < 12; index++) {
        await nextTick()
        const pending = [...frames.entries()]
        frames.clear()
        pending.forEach(([, callback]) => callback(index * 16))
        await Promise.resolve()
      }
      await nextTick()
      expect(frames.size, '尺寸稳定后不应持续排队动画帧').toBe(0)
    }
    function resizeContent(value: number) {
      naturalHeight = value
      const content = dialog.querySelector('[data-geometry-content]')!
      observers.forEach(observer => {
        if (observer.targets.has(content)) observer.callback([], observer)
      })
    }
    function resizeViewport(value: number) {
      vi.stubGlobal('innerHeight', value)
      window.dispatchEvent(new Event('resize'))
    }
    async function clickWindowAction(label: string) {
      await new DOMWrapper(dialog.querySelector(`[aria-label="${label}"]`)!).trigger('click')
      await settleFrames()
    }
    function geometry() {
      return {
        height: Number.parseFloat(dialog.style.height),
        width: Number.parseFloat(dialog.style.width),
        top: Number.parseFloat(dialog.style.top),
        left: Number.parseFloat(dialog.style.left),
      }
    }
    return { dialog, settleFrames, resizeContent, resizeViewport, clickWindowAction, geometry }
  }

  it('短内容按自然高度向上取整，不撑满 80vh，内容增减后仍能收缩', async () => {
    const window = measuredWindow(140.5)
    await window.settleFrames()
    expect(window.geometry()).toMatchObject({ height: 274, top: 313 })
    window.resizeContent(300.25)
    await window.settleFrames()
    expect(window.geometry()).toMatchObject({ height: 434, top: 233 })
    window.resizeContent(140.5)
    await window.settleFrames()
    expect(window.geometry()).toMatchObject({ height: 274, top: 313 })
  })

  it('auto 长内容限制到 80vh，并用限制后的高度居中', async () => {
    const window = measuredWindow(1000)
    await window.settleFrames()
    expect(window.geometry()).toMatchObject({ height: 720, top: 90 })
  })

  it('调用方可将自动限高提高到 94vh，缩小视口后仍保留上下 16px 边距', async () => {
    const window = measuredWindow(1000, 'auto', false, 0.94)
    expect(window.dialog.style.maxHeight).toBe('min(94vh, calc(100vh - 32px))')
    await window.settleFrames()
    expect(window.geometry()).toMatchObject({ height: 846, top: 27 })
    window.resizeViewport(400)
    await window.settleFrames()
    expect(window.geometry()).toMatchObject({ height: 368, top: 16 })
  })

  it('显式高度可随自然内容扩展，但内容变少后保留请求高度下限', async () => {
    const window = measuredWindow(300.25, 240)
    await window.settleFrames()
    expect(window.geometry()).toMatchObject({ height: 434, top: 233 })
    window.resizeContent(40)
    await window.settleFrames()
    expect(window.geometry()).toMatchObject({ height: 240, top: 330 })
  })

  it('视口缩小和放大时重新计算 80vh 上限与居中位置', async () => {
    const window = measuredWindow(1000)
    await window.settleFrames()
    window.resizeViewport(700)
    await window.settleFrames()
    expect(window.geometry()).toMatchObject({ height: 560, top: 70 })
    window.resizeViewport(900)
    await window.settleFrames()
    expect(window.geometry()).toMatchObject({ height: 720, top: 90 })
  })

  it('正文已有滚动偏移时重新测量，不重复增加 scrollTop', async () => {
    const window = measuredWindow(1000)
    await window.settleFrames()
    window.dialog.querySelector<HTMLElement>('.app-window-dialog__body')!.scrollTop = 120
    window.resizeContent(300.25)
    await window.settleFrames()
    expect(window.geometry()).toMatchObject({ height: 434, top: 233 })
  })

  it('最大化不受 80vh 限制，还原后根据当前内容适配普通高度', async () => {
    const window = measuredWindow(200)
    await window.settleFrames()
    await window.clickWindowAction('最大化')
    expect(window.geometry()).toMatchObject({ height: 868, top: 16 })
    window.resizeContent(500)
    await window.settleFrames()
    expect(window.geometry()).toMatchObject({ height: 868, top: 16 })
    await window.clickWindowAction('还原')
    expect(window.geometry()).toMatchObject({ height: 633, top: 133.5 })
  })

  it('初始最大化窗口还原时同时考虑显式下限和自然内容', async () => {
    const window = measuredWindow(300.25, 240, true)
    await window.settleFrames()
    expect(window.geometry()).toMatchObject({ height: 868, top: 16 })
    await window.clickWindowAction('还原')
    expect(window.geometry()).toMatchObject({ height: 434, top: 233 })
  })

  it.each(['auto', 300] as const)('height=%s 的窗口手动缩放后，内容更新和最大化还原保留用户尺寸', async height => {
    const measured = measuredWindow(250, height)
    await measured.settleFrames()
    expect(measured.geometry().height).toBe(383)
    await new DOMWrapper(measured.dialog.querySelector('.app-window-dialog__resize-handle')!).trigger('pointerdown', { button: 0, clientX: 100, clientY: 100 })
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 180, clientY: 180 }))
    window.dispatchEvent(new MouseEvent('pointerup'))
    await measured.settleFrames()
    const resized = measured.geometry()
    expect(resized).toMatchObject({ width: 600, height: 463 })
    measured.resizeContent(1000)
    await measured.settleFrames()
    expect(measured.geometry()).toEqual(resized)
    await measured.clickWindowAction('最大化')
    await measured.clickWindowAction('还原')
    expect(measured.geometry()).toEqual(resized)
  })
})
