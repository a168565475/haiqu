import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import LoginFlowIllustration from './LoginFlowIllustration.vue'

describe('登录业务流程动效', () => {
  it('图片与光流使用同一坐标，页面隐藏时暂停，卸载后移除监听', async () => {
    const remove = vi.spyOn(document, 'removeEventListener')
    const wrapper = mount(LoginFlowIllustration)
    try {
      expect(wrapper.get('svg').attributes('viewBox')).toBe('0 0 1448 1086')
      expect(wrapper.findAll('.flow-node')).toHaveLength(4)
      Object.defineProperty(document, 'hidden', { configurable: true, value: true })
      document.dispatchEvent(new Event('visibilitychange'))
      await wrapper.vm.$nextTick()
      expect(wrapper.classes()).toContain('is-paused')
      Object.defineProperty(document, 'hidden', { configurable: true, value: false })
      document.dispatchEvent(new Event('visibilitychange'))
      await wrapper.vm.$nextTick()
      expect(wrapper.classes()).not.toContain('is-paused')
    } finally { wrapper.unmount() }
    expect(remove).toHaveBeenCalledWith('visibilitychange', expect.any(Function))
    remove.mockRestore()
  })
})
