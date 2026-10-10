import { afterEach, expect, it, vi } from 'vitest'
import { createClientUuid } from './clientUuid'

afterEach(() => vi.restoreAllMocks())

it('安全环境复用浏览器提供的 UUID', () => {
  const uuid = '9fb374cc-5d07-43d5-84bc-d1c8042a3465'
  const native = vi.spyOn(globalThis.crypto, 'randomUUID').mockReturnValue(uuid)
  expect(createClientUuid()).toBe(uuid)
  expect(native).toHaveBeenCalledTimes(1)
})

it('局域网降级仍生成格式正确、互不重复的 UUID v4 幂等键', () => {
  vi.spyOn(globalThis.crypto, 'randomUUID')
  Object.defineProperty(globalThis.crypto, 'randomUUID', { value: undefined, configurable: true })
  const values = Array.from({ length: 100 }, () => createClientUuid())
  expect(new Set(values).size).toBe(100)
  expect(values.every(value => /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value))).toBe(true)
})
