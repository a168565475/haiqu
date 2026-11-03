import { CanceledError } from 'axios'
import { getCurrentScope, onScopeDispose } from 'vue'
import { useAuthStore } from '@/stores/auth'

interface IdentityOwnedStorageOptions {
  storage: 'session' | 'local'
  /** A string receives the user suffix; a function preserves an existing UID namespace. */
  key: string | ((userId: number) => string)
  legacyKeys?: readonly string[] | (() => readonly string[])
}

/** A component-lifetime capability, never rebound to a later authenticated identity. */
export function useIdentityOwnedStorage(options: IdentityOwnedStorageOptions) {
  const auth = useAuthStore()
  const verified = auth.initialized === true && auth.identityReady === true
    && typeof auth.user?.id === 'number' && Number.isSafeInteger(auth.user.id) && auth.user.id > 0
  const owner = Object.freeze({
    userId: verified ? auth.user!.id : null,
    generation: auth.identityGeneration,
    requestGeneration: auth.identityRequestGeneration,
  })
  let alive = true
  if (getCurrentScope()) onScopeDispose(() => { alive = false })
  function isCurrent(): boolean {
    return alive && owner.userId !== null && auth.initialized === true && auth.identityReady === true
      && auth.user?.id === owner.userId && auth.identityGeneration === owner.generation
      && auth.identityRequestGeneration === owner.requestGeneration
  }
  function assertCurrent(): void {
    if (!isCurrent()) throw new CanceledError('身份尚未核验或已变化，请核验身份后重新打开本页。')
  }
  function storage(): Storage {
    assertCurrent()
    // Access itself can throw (privacy policy/security settings); never fall back to an unpersisted ID.
    return options.storage === 'session' ? window.sessionStorage : window.localStorage
  }
  function key(): string {
    assertCurrent()
    return typeof options.key === 'function' ? options.key(owner.userId!) : `${options.key}:user:${owner.userId}`
  }
  function read(): string | null { return storage().getItem(key()) }
  function write(raw: string): void { storage().setItem(key(), raw) }
  function removeIfUnchanged(expectedRaw: string): boolean {
    const target = storage(), targetKey = key()
    if (target.getItem(targetKey) !== expectedRaw) return false
    assertCurrent()
    target.removeItem(targetKey)
    return true
  }
  function legacyExists(): boolean {
    const target = storage()
    const keys = typeof options.legacyKeys === 'function' ? options.legacyKeys() : options.legacyKeys || []
    // Existence only: do not parse, claim, rewrite, or delete ownerless historical values (even empty/corrupt).
    return keys.some(legacyKey => target.getItem(legacyKey) !== null)
  }
  return { owner, isCurrent, assertCurrent, read, write, removeIfUnchanged, legacyExists }
}
