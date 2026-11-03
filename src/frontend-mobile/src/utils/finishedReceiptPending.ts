interface ReceiptIdentity { userId: number | null; generation: number }

/** 所有权固定在打开页面时；刷新可恢复同账号记录，旧页面不能操作新身份的记录。 */
export function createFinishedReceiptPending(planId: string, owner: ReceiptIdentity, currentIdentity: () => ReceiptIdentity) {
  const captured = { ...owner }
  // 与 ERP 使用同一 session key，切回 ERP 也能核对这笔原请求。
  const key = `assembly-receipt:${planId}:user:${captured.userId}`
  const legacyKey = `assembly-receipt:${planId}`
  function isCurrent() {
    const current = currentIdentity()
    return captured.userId !== null && Number.isSafeInteger(captured.userId) && captured.userId > 0
      && current.userId === captured.userId && current.generation === captured.generation
  }
  function assertCurrent() { if (!isCurrent()) throw new Error('身份已变化，请重新打开成品入库页面。') }
  function storage() { assertCurrent(); return window.sessionStorage }
  function read() {
    const target = storage()
    if (target.getItem(legacyKey) !== null) throw new Error('发现历史无主待核对记录，已保留并暂停提交，请联系管理员核对。')
    return target.getItem(key)
  }
  function write(raw: string) {
    if (read() !== null) throw new Error('已有待核对记录，请重新打开本页核对，暂勿另建单据。')
    storage().setItem(key, raw)
    if (read() !== raw) throw new Error('提交编号未能保存，已暂停提交，请重新打开本页核对。')
  }
  function assertUnchanged(raw: string) {
    if (read() !== raw) throw new Error('待核对记录已变化，请重新打开本页并联系管理员核对。')
  }
  function consume(raw: string) { assertUnchanged(raw); storage().removeItem(key) }
  return { isCurrent, assertCurrent, read, write, assertUnchanged, consume }
}
