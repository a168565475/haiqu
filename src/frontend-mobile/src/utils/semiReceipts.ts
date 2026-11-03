import type { PendingSemiReceipt, SemiReceiptCategory, SemiReceiptLine, SemiReceiptPreview } from '@/types/semiReceipts'
import { validProductionDate } from '@/utils/reporting'

export const semiReceiptUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
export function semiReceiptScope(query: Record<string, unknown>) {
  const { schedule_product_id, plan_category } = query
  return typeof schedule_product_id === 'string' && semiReceiptUuid.test(schedule_product_id) && (plan_category === 'METAL' || plan_category === 'SEWING')
    ? { schedule_product_id, plan_category } as { schedule_product_id: string; plan_category: SemiReceiptCategory } : null
}
export function semiWhole(value: unknown): bigint | null {
  const text = typeof value === 'string' ? value : typeof value === 'number' && Number.isSafeInteger(value) ? String(value) : ''
  if (!/^\d+$/.test(text)) return null
  const significant = text.replace(/^0+/, '') || '0'
  return significant.length <= 14 ? BigInt(significant) : null
}
export function semiPreviewWhole(value: unknown): bigint | null {
  return typeof value === 'string' ? semiWhole(value.replace(/\.0+$/, '')) : null
}
export function formatSemiQuantity(value: string, previous: string) { return /^\d*$/.test(value) ? value : previous }
export function semiLineName(line: SemiReceiptLine) { return line.attributes.part_name || line.output_material_selection_snapshot?.name || '未填写部位' }
export function semiPageBlockers(preview: SemiReceiptPreview): string[] {
  return preview.plan_category === 'METAL' ? [...(preview.metal_processing?.blockers ?? []), ...(preview.metal_processing?.future_blockers ?? [])] : []
}
export function semiLineError(preview: SemiReceiptPreview, line: SemiReceiptLine, quantity: string): string {
  if (quantity === '' || /^0+$/.test(quantity)) return ''
  const number = semiWhole(quantity)
  if (number === null) return '请填写整数，最多 14 位有效数字。'
  if (preview.plan_category === 'METAL' && !line.metal_processing?.basis_ready) return line.metal_processing?.blockers.join('；') || '该部位加工数量依据不完整。'
  const maximum = semiPreviewWhole(line.can_receive)
  if (maximum === null) return '可入数量不完整，请重新读取。'
  if (number > maximum) return `本次最多可入 ${maximum} ${line.attributes.unit_name}。`
  return ''
}
export function semiReceiptLines(preview: SemiReceiptPreview, quantities: Record<string, string>) {
  const blockers = semiPageBlockers(preview)
  if (blockers.length) throw new Error(blockers.join('；'))
  const lines = preview.lines.flatMap(line => {
    const quantity = quantities[line.bom_line_id] || ''
    const error = semiLineError(preview, line, quantity)
    if (error) throw new Error(`${semiLineName(line)}：${error}`)
    const amount = semiWhole(quantity)
    return amount !== null && amount > 0n ? [{ bom_line_id: line.bom_line_id, quantity: String(amount) }] : []
  })
  if (!lines.length) throw new Error('请至少填写一项大于 0 的本次入库数量。')
  if (lines.length > 300) throw new Error('每次最多提交 300 项入库明细。')
  return lines
}
export function parsePendingSemiReceipt(raw: string, planId: string, category: SemiReceiptCategory): PendingSemiReceipt {
  const invalid = () => new Error('本地待核对记录无法读取，已保留并暂停新提交，请联系管理员核对。')
  let value: PendingSemiReceipt
  try { value = JSON.parse(raw) as PendingSemiReceipt } catch { throw invalid() }
  const payload = value?.payload
  if (!value || typeof value.etag !== 'string' || !value.etag || (value.conflict !== undefined && typeof value.conflict !== 'boolean') || !payload
    || payload.schedule_product_id !== planId || payload.plan_category !== category
    || typeof payload.request_id !== 'string' || !semiReceiptUuid.test(payload.request_id)
    || typeof payload.zone_id !== 'string' || !semiReceiptUuid.test(payload.zone_id)
    || typeof payload.receipt_date !== 'string' || !validProductionDate(payload.receipt_date)
    || typeof payload.remark !== 'string' || payload.remark.length > 2000 || !Array.isArray(payload.lines) || !payload.lines.length || payload.lines.length > 300
    || !payload.lines.every(line => line && typeof line.bom_line_id === 'string' && semiReceiptUuid.test(line.bom_line_id)
      && (typeof line.quantity === 'string' || category === 'METAL' && typeof line.quantity === 'number') && (semiWhole(line.quantity) ?? 0n) > 0n)
    || new Set(payload.lines.map(line => line.bom_line_id)).size !== payload.lines.length) throw invalid()
  // ERP 历史金工 pending 的 quantity 可为 number，重放不转换原类型或改原内容。
  return value
}
export function semiReceiptFailure(error: unknown, recovering: boolean): 'deleted' | 'conflict' | 'rejected' | 'unknown' {
  const response = (error as { response?: { status?: number; data?: { error?: { code?: string } } } })?.response
  const status = response?.status
  if (status === 409) return response?.data?.error?.code === 'RECEIPT_REQUEST_DELETED' ? 'deleted' : 'conflict'
  if (recovering && [400, 403, 404].includes(status ?? 0)) return 'unknown'
  return [400, 403, 404, 412, 428].includes(status ?? 0) ? 'rejected' : 'unknown'
}
export const semiAttributeLabels: Record<string, string> = { material: '材质', color: '颜色', shape: '形状', section_size: '规格', thickness: '厚度', hardness: '硬度', length: '长度', fabric_spec: '面料规格', width: '门幅', size: '尺寸', model: '型号', process: '工艺版本', specification: '规格' }
