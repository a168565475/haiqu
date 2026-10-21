import type { TubeDetailLine, TubeOrderDetail } from '@/types/tubeOutsourcing'
import type { TubeReceipt, TubeReceiptLine } from '@/types/tubeReceipts'
import { isCuttingSource } from './tubeOutsourcing'

export interface TubeEndedLine extends TubeReceiptLine {
  pieces_per_bar: string | null
  raw_bar_length_m: string | null
  stock_quantity: string | null
  meters: string | null
  unit_price: string | null
  planned_amount: string | null
}
export interface TubeEndedResult {
  available: boolean
  complete: boolean
  rows: TubeEndedLine[]
  issues: string[]
  dispatched: string | null
  received: string | null
  shortage: string | null
}

function pieceCount(value: unknown): number | null {
  if (typeof value !== 'string' || !/^\d+(?:\.0+)?$/.test(value)) return null
  const count = Number(value)
  return Number.isSafeInteger(count) && count >= 0 ? count : null
}
function positiveQuantity(value: unknown, integer = false): string | null {
  if (typeof value !== 'string' || !/^\d+(?:\.\d+)?$/.test(value)) return null
  const quantity = Number(value)
  return Number.isFinite(quantity) && quantity > 0 && (!integer || Number.isSafeInteger(quantity)) ? value : null
}
const attributeKeys = ['part_name', 'material', 'specification', 'thickness', 'cutting_length_mm', 'raw_color', 'spray_color', 'factory_name'] as const

// 已结束只对应原单与最终凭证，不能按名称、数组顺序或当前BOM重新解释历史。
export function buildTubeEndedResult(order: TubeOrderDetail, receipt: TubeReceipt | null): TubeEndedResult {
  const result: TubeEndedResult = { available: false, complete: false, rows: [], issues: [], dispatched: null, received: null, shortage: null }
  if (!receipt) { result.issues.push('原单已结束，但最终入库凭证未能读取，请刷新核对。'); return result }
  if (order.status !== 'COMPLETED' || receipt.order_id !== order.id || receipt.status !== 'COMPLETED' || receipt.source_kind !== order.source_kind
    || !receipt.id || !receipt.receipt_number || !receipt.receipt_date || !Array.isArray(receipt.lines) || !Array.isArray(order.lines) || !order.lines.length) {
    result.issues.push('最终入库凭证与原单不一致或资料不完整，请重新加载核对。'); return result
  }
  if (order.lines.some(line => !line || typeof line !== 'object' || typeof line.id !== 'string' || !line.id)) {
    result.issues.push('原单历史明细结构不完整，请重新加载核对。'); return result
  }
  result.available = true
  const issues = new Set<string>()
  const byOrderLine = new Map<string, TubeReceiptLine>()
  const duplicate = new Set<string>()
  const originals = new Map<string, TubeDetailLine>()
  for (const original of order.lines) {
    if (!original.id || originals.has(original.id)) issues.add('原单历史明细编号缺失或重复。')
    originals.set(original.id, original)
  }
  for (const line of receipt.lines) {
    if (!line || typeof line.order_line_id !== 'string' || !line.order_line_id) { issues.add('入库凭证明细编号缺失。'); continue }
    if (byOrderLine.has(line.order_line_id)) { duplicate.add(line.order_line_id); issues.add('入库凭证明细编号重复。') }
    else byOrderLine.set(line.order_line_id, line)
    if (!originals.has(line.order_line_id)) issues.add('入库凭证存在无法对应原单的明细。')
  }
  let dispatched = 0, received = 0, shortage = 0, quantitiesMatch = true
  for (const original of order.lines) {
    const matched = duplicate.has(original.id) ? undefined : byOrderLine.get(original.id)
    if (!matched) { issues.add('部分原单明细缺少唯一对应的入库凭证。'); quantitiesMatch = false }
    const sent = pieceCount(matched?.dispatched_quantity), actual = pieceCount(matched?.received_quantity), difference = pieceCount(matched?.shortage_quantity)
    const expected = pieceCount(original.quantity)
    const validQuantity = matched && sent !== null && actual !== null && difference !== null && expected !== null
      && sent === expected && actual + difference === sent
    if (!validQuantity) { issues.add('部分明细实发、实收与差额无法对应，请核对原凭证。'); quantitiesMatch = false }
    else { dispatched += sent; received += actual; shortage += difference }
    const row: TubeEndedLine = {
      id: original.id, order_line_id: original.id, component_identity: matched?.component_identity || original.component_identity,
      part_name: '', material: '', specification: '', thickness: '', cutting_length_mm: '', raw_color: '', spray_color: '', factory_name: '',
      factory_id: matched?.factory_id || '', dispatched_quantity: validQuantity ? matched.dispatched_quantity : '',
      received_quantity: validQuantity ? matched.received_quantity : '', shortage_quantity: validQuantity ? matched.shortage_quantity : '',
      shortage_reason: typeof matched?.shortage_reason === 'string' ? matched.shortage_reason : '',
      zone_id: actual !== null && actual > 0 ? matched?.zone_id || null : null,
      zone_name: actual !== null && actual > 0 && typeof matched?.zone_name === 'string' ? matched.zone_name : '',
      stock_movement_id: matched?.stock_movement_id || null,
      pieces_per_bar: positiveQuantity(original.pieces_per_bar, true), raw_bar_length_m: positiveQuantity(original.raw_bar_length_m),
      stock_quantity: positiveQuantity(original.stock_quantity, true), meters: positiveQuantity(original.meters),
      unit_price: original.unit_price ?? null, planned_amount: original.planned_amount ?? null,
      fabric_material: matched?.fabric_material, fabric_specification: matched?.fabric_specification,
      fabric_color: matched?.fabric_color, pieces_per_set: matched?.pieces_per_set,
      completed_craft_name: matched?.completed_craft_name,
    }
    const requiredAttributes = isCuttingSource(order.source_kind)
      ? ['part_name', 'fabric_material', 'specification', 'fabric_color', 'factory_name'] as const
      : attributeKeys
    for (const key of requiredAttributes) {
      const value = matched?.[key]
      row[key] = typeof value === 'string' && value.trim() ? value : '—'
      if (row[key] === '—') issues.add('部分冻结的材料属性缺失，缺失字段显示“—”，不按当前BOM补算。')
    }
    if (difference !== null && difference > 0 && !row.shortage_reason.trim()) issues.add('部分少回明细缺少原差额原因。')
    if (actual !== null && actual > 0 && (!row.zone_id || !row.zone_name || !receipt.warehouse_id || !receipt.warehouse_name)) issues.add('部分实收入库明细缺少原仓库或库区。')
    if (order.source_kind === 'RAW_PIPE' && [row.pieces_per_bar, row.raw_bar_length_m, row.stock_quantity, row.meters].some(value => value === null)) issues.add('部分原材料发出历史明细缺失，缺失字段显示“—”，不补算扣根扣米。')
    result.rows.push(row)
  }
  if (duplicate.size || byOrderLine.size !== originals.size || [...byOrderLine.keys()].some(id => !originals.has(id))) quantitiesMatch = false
  const totalsMatch = quantitiesMatch && Number.isSafeInteger(dispatched) && Number.isSafeInteger(received) && Number.isSafeInteger(shortage)
    && pieceCount(receipt.total_dispatched_quantity) === dispatched && pieceCount(order.total_quantity) === dispatched
    && pieceCount(receipt.total_received_quantity) === received && pieceCount(receipt.total_shortage_quantity) === shortage
  if (!totalsMatch) issues.add('入库凭证汇总与全部明细无法完整对应，汇总暂不显示。')
  else { result.dispatched = String(dispatched); result.received = String(received); result.shortage = String(shortage) }
  result.issues = [...issues]
  result.complete = result.issues.length === 0
  return result
}
