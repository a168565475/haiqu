import { DOMWrapper, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

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
})
