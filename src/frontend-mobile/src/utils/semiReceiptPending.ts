import type { SemiReceiptCategory } from '@/types/semiReceipts'
interface ReceiptIdentity { userId: number | null; generation: number }
export function createSemiReceiptPending(planId: string, category: SemiReceiptCategory, owner: ReceiptIdentity, currentIdentity: () => ReceiptIdentity) {
  const captured = { ...owner }
  const legacyKey = `internal-receipt-pending:${planId}:${category}`
  const key = `${legacyKey}:user:${captured.userId}`
  function isCurrent() {
    const current = currentIdentity()
    return captured.userId !== null && Number.isSafeInteger(captured.userId) && captured.userId > 0
      && current.userId === captured.userId && current.generation === captured.generation
  }
  function storage() { if (!isCurrent()) throw new Error('身份已变化，请重新打开半成品入库页面。'); return window.sessionStorage }
  function read() {
    const target = storage()
    if (target.getItem(legacyKey) !== null) throw new Error('发现历史无主待核对记录，已保留并暂停提交，请联系管理员核对。')
    return target.getItem(key)
  }
  function assertUnchanged(raw: string) { if (read() !== raw) throw new Error('待核对记录已变化，请重新打开本页并联系管理员核对。') }
  function write(raw: string) {
    if (read() !== null) throw new Error('已有待核对记录，请重新打开本页核对，暂勿另建单据。')
    storage().setItem(key, raw)
    assertUnchanged(raw)
  }
  function replace(expected: string, raw: string) { assertUnchanged(expected); storage().setItem(key, raw); assertUnchanged(raw) }
  function consume(raw: string) { assertUnchanged(raw); storage().removeItem(key) }
  return { isCurrent, read, write, replace, assertUnchanged, consume }
}
