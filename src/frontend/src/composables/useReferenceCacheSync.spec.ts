import { defineComponent, reactive } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useReferenceCacheSync } from './useReferenceCacheSync'
import { useReferenceOptionsStore } from '@/stores/referenceOptions'
import { fetchPublishedOptions, fetchPublishedConfigVersion } from '@/api/referenceData'

const auth = reactive({ user: { id: 'one' } })
vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('@/api/referenceData', () => ({ fetchPublishedOptions: vi.fn(), fetchPublishedConfigVersion: vi.fn() }))

describe('全局配置不轮询', () => {
  afterEach(() => vi.useRealTimers())
  it('等待 90 秒、聚焦和恢复可见均不发配置请求；身份改变仍清理上下文', async () => {
    setActivePinia(createPinia()); vi.useFakeTimers(); vi.clearAllMocks()
    const wrapper = mount(defineComponent({ setup() { useReferenceCacheSync(); return {} }, template: '<div />' }))
    await vi.advanceTimersByTimeAsync(90000)
    window.dispatchEvent(new Event('focus')); document.dispatchEvent(new Event('visibilitychange'))
    expect(fetchPublishedConfigVersion).not.toHaveBeenCalled()
    expect(fetchPublishedOptions).not.toHaveBeenCalled()
    const store = useReferenceOptionsStore(), generation = store.identityGeneration
    auth.user = { id: 'two' }
    expect(store.identityGeneration).toBe(generation + 1)
    wrapper.unmount()
  })
})
