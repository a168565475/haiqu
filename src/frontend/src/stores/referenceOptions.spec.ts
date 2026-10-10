import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchPublishedOptions, fetchPublishedConfigVersion } from '@/api/referenceData'
import { useReferenceOptionsStore } from './referenceOptions'
import type { PublishedOptionsResponse } from '@/types/referenceData'
vi.mock('@/api/referenceData', () => ({ fetchPublishedOptions: vi.fn(), fetchPublishedConfigVersion: vi.fn() }))
const response = (version: number): PublishedOptionsResponse => ({ data: [], meta: { config_version: version } })
describe('按需读取配置', () => {
  beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks() })
  it('相同在途请求合并，完成后再次使用重新读取，不核对版本', async () => {
    let finish!: (value: PublishedOptionsResponse) => void
    vi.mocked(fetchPublishedOptions).mockReturnValueOnce(new Promise(resolve => { finish = resolve })).mockResolvedValue(response(2))
    const store = useReferenceOptionsStore()
    const first = store.load('CUSTOMER_GRADE'), second = store.load('CUSTOMER_GRADE')
    finish(response(1)); await Promise.all([first, second])
    expect(fetchPublishedOptions).toHaveBeenCalledTimes(1)
    await store.load('CUSTOMER_GRADE')
    expect(fetchPublishedOptions).toHaveBeenCalledTimes(2)
    expect(fetchPublishedConfigVersion).not.toHaveBeenCalled()
    expect(store.configVersion).toBe(2)
  })
  it('身份失效后在途数据不能重新进入缓存或组件', async () => {
    let finish!: (value: PublishedOptionsResponse) => void
    vi.mocked(fetchPublishedOptions).mockReturnValue(new Promise(resolve => { finish = resolve }))
    const store = useReferenceOptionsStore(), loading = store.load('CUSTOMER_GRADE')
    store.resetForIdentity(); finish(response(1))
    await expect(loading).rejects.toThrow()
    expect(store.configVersion).toBeNull()
  })
  it('失败后下次使用可重试，历史项参数继续保留', async () => {
    vi.mocked(fetchPublishedOptions).mockRejectedValueOnce(new Error('offline')).mockResolvedValue(response(3))
    const store = useReferenceOptionsStore()
    await expect(store.load('CUSTOMER_GRADE')).rejects.toThrow('offline')
    await expect(store.load('CUSTOMER_GRADE', 'old-id')).resolves.toEqual([])
    expect(fetchPublishedOptions).toHaveBeenLastCalledWith('CUSTOMER_GRADE', 'old-id')
  })
})
