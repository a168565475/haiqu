import { effectScope, reactive } from 'vue'
import { isCancel } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useIdentityOwnedStorage } from './useIdentityOwnedStorage'

const state = vi.hoisted(() => ({ auth: {} as { initialized: boolean; identityReady: boolean; user: { id: number } | null; identityGeneration: number; identityRequestGeneration: number } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => state.auth }))
const scopes: ReturnType<typeof effectScope>[] = []
function create(options: Parameters<typeof useIdentityOwnedStorage>[0] = { storage: 'session', key: 'pending', legacyKeys: ['pending'] }) {
  const scope = effectScope(); scopes.push(scope)
  return scope.run(() => useIdentityOwnedStorage(options))!
}
beforeEach(() => {
  sessionStorage.clear(); localStorage.clear()
  state.auth = reactive({ initialized: true, identityReady: true, user: { id: 7 }, identityGeneration: 0, identityRequestGeneration: 0 })
})
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); vi.restoreAllMocks() })
describe('identity-owned browser storage', () => {
  it.each(['', '{broken', 'old-bare-uuid', '{"payload":{"quantity":2}}'])('preserves ownerless bytes %j without restoring or claiming', raw => {
    sessionStorage.setItem('pending', raw)
    const owned = create()
    expect(owned.legacyExists()).toBe(true); expect(owned.read()).toBeNull()
    owned.write('new-owned')
    expect(sessionStorage.getItem('pending')).toBe(raw)
    expect(sessionStorage.getItem('pending:user:7')).toBe('new-owned')
  })
  it('isolates different verified users and preserves existing UID key functions exactly', () => {
    const first = create(); first.write('A')
    state.auth.user = { id: 8 }; state.auth.identityGeneration++
    const second = create(); expect(second.read()).toBeNull(); second.write('B')
    expect(first.isCurrent()).toBe(false)
    expect(sessionStorage.getItem('pending:user:7')).toBe('A')
    const compatible = create({ storage: 'local', key: uid => `existing:${uid}:source`, legacyKeys: ['existing:unknown:source'] })
    compatible.write('exact-key'); expect(localStorage.getItem('existing:8:source')).toBe('exact-key')
  })
  it('consumes only the exact captured raw and leaves later replacements intact', () => {
    const owned = create(); owned.write('original')
    sessionStorage.setItem('pending:user:7', 'newer')
    expect(owned.removeIfUnchanged('original')).toBe(false)
    expect(owned.read()).toBe('newer')
    expect(owned.removeIfUnchanged('newer')).toBe(true); expect(owned.read()).toBeNull()
  })
  it.each(['user', 'generation', 'request', 'ready', 'disposed'])('rejects every storage operation after %s invalidation without touching values', reason => {
    const owned = create(); owned.write('original')
    if (reason === 'user') state.auth.user = { id: 8 }
    if (reason === 'generation') state.auth.identityGeneration++
    if (reason === 'request') state.auth.identityRequestGeneration++
    if (reason === 'ready') state.auth.identityReady = false
    if (reason === 'disposed') scopes.at(-1)!.stop()
    for (const operation of [owned.read, () => owned.write('wrong'), () => owned.removeIfUnchanged('original'), owned.legacyExists, owned.assertCurrent]) {
      let error: unknown; try { operation() } catch (cause) { error = cause }
      expect(isCancel(error)).toBe(true)
    }
    expect(sessionStorage.getItem('pending:user:7')).toBe('original')
  })
  it('an unverified setup never arms itself when /me later completes', () => {
    state.auth.identityReady = false
    const owned = create(); state.auth.identityReady = true
    expect(owned.owner.userId).toBeNull(); expect(owned.isCurrent()).toBe(false)
    expect(() => owned.write('unsafe')).toThrow('重新打开')
  })
  it.each([0, -1, 1.5, Number.NaN, Number.MAX_SAFE_INTEGER + 1, '7', null])('only a verified numeric positive safe-integer uid can own storage: %j', id => {
    state.auth.user = { id: id as number }
    const owned = create(); expect(owned.isCurrent()).toBe(false)
    expect(() => owned.read()).toThrow('重新打开')
  })
  it('storage property-access exceptions propagate instead of falling back to an in-memory UUID', () => {
    const owned = create()
    vi.spyOn(window, 'sessionStorage', 'get').mockImplementation(() => { throw new Error('security policy') })
    expect(owned.read).toThrow('security policy'); expect(() => owned.write('unsafe')).toThrow('security policy')
  })
  it('ordinary /me authentication generation does not invalidate the capability', () => {
    const owned = create(); Object.assign(state.auth, { authenticationGeneration: 99 })
    expect(owned.isCurrent()).toBe(true)
  })
  it.each(['getItem', 'setItem', 'removeItem'] as const)('storage %s exceptions fail closed', method => {
    const owned = create(); owned.write('original')
    vi.spyOn(Storage.prototype, method).mockImplementation(() => { throw new Error('denied') })
    const action = method === 'setItem' ? () => owned.write('unsafe') : method === 'removeItem' ? () => owned.removeIfUnchanged('original') : owned.read
    expect(action).toThrow('denied')
  })
})
