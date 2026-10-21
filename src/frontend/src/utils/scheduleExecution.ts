import type { ScheduleOutsourcingOrderSummary, ScheduleOutsourcingQuantityField, ScheduleOutsourcingRecord } from '@/types/scheduleExecution'

// 金额以十进制字符串处理，避免大金额转成浮点数后丢失精度。
function formatDecimal(value: string | null | undefined, digits: number, trimFraction: boolean): string {
  if (typeof value !== 'string' || !/^\d+(?:\.\d+)?$/.test(value)) return '—'
  const [whole = '0', fraction = ''] = value.split('.')
  const scale = 10n ** BigInt(digits)
  let scaled = BigInt(whole) * scale + BigInt(fraction.slice(0, digits).padEnd(digits, '0'))
  if (Number(fraction[digits] || '0') >= 5) scaled += 1n
  const integer = (scaled / scale).toLocaleString('zh-CN')
  const decimals = String(scaled % scale).padStart(digits, '0')
  const displayed = trimFraction ? decimals.replace(/0+$/, '') : decimals
  return `${integer}${displayed ? `.${displayed}` : ''}`
}

export function formatScheduleMoney(value: string | null | undefined): string {
  const text = formatDecimal(value, 2, false)
  return text === '—' ? text : `¥${text}`
}

export function formatScheduleUnitPrice(value: string | null | undefined): string {
  const text = formatDecimal(value, 4, true)
  return text === '—' ? text : `¥${text}`
}

export function formatScheduleQuantity(value: string | null | undefined, unit = ''): string {
  if (typeof value !== 'string' || !/^\d+(?:\.\d+)?$/.test(value)) return '—'
  const [whole = '0', fraction = ''] = value.split('.')
  const decimals = fraction.replace(/0+$/, '')
  return `${BigInt(whole).toLocaleString('zh-CN')}${decimals ? `.${decimals}` : ''}${unit ? ` ${unit}` : ''}`
}

export function scheduleAmountReason(status: string | undefined): string {
  return ({
    NOT_APPLICABLE: '本产品没有内部作业计划。',
    QUANTITY_BASIS_MISMATCH: '排产数量与工价计价基数不同，暂无法计算本排产预计金额。',
    FORBIDDEN: '当前账号没有查看该金额的权限。',
    NOT_CREATED: '尚未建立工价方案。',
    NOT_CONFIGURED: '工价尚未配置完整。',
    NO_EFFECTIVE_VERSION: '当前日期没有适用的已批准工价方案。',
    CONFLICT: '当前存在多个适用工价版本，暂无法计算。',
    UNAVAILABLE: '当前数据不足，暂无法计算。',
    PARTIAL: '部分工艺的金额不可用，暂不显示不完整合计。',
  } as Record<string, string>)[status || ''] || '金额暂不可用，请查看对应计划或权限。'
}

function decimalKey(value: string | null): string | null {
  if (value === null || !/^\d+(?:\.\d+)?$/.test(value)) return null
  const [whole = '0', fraction = ''] = value.split('.')
  const decimals = fraction.replace(/0+$/, '')
  return `${BigInt(whole)}${decimals ? `.${decimals}` : ''}`
}

function sumDecimals(values: Array<string | null>, minimumPlaces = 0): string | null {
  if (!values.length || values.some(value => decimalKey(value) === null)) return null
  const parts = values.map(value => value!.split('.'))
  const places = Math.max(minimumPlaces, ...parts.map(([, fraction = '']) => fraction.length))
  const scale = 10n ** BigInt(places)
  const total = parts.reduce((sum, [whole = '0', fraction = '']) => (
    sum + BigInt(whole) * scale + BigInt(fraction.padEnd(places, '0') || '0')
  ), 0n)
  return `${total / scale}${places ? `.${String(total % scale).padStart(places, '0')}` : ''}`
}

function orderQuantity(rows: ScheduleOutsourcingRecord[], field: ScheduleOutsourcingQuantityField, unitFor: (row: ScheduleOutsourcingRecord) => string | null) {
  const units = rows.map(row => unitFor(row)?.trim() || '')
  const knownUnits = [...new Set(units.filter(Boolean))]
  if (knownUnits.length > 1 || knownUnits.includes('多种单位')) {
    return { quantity: null, unit: '多种单位', note: '本单明细包含多种单位，不能混合相加，请查看详情。' }
  }
  const quantity = units.some(unit => !unit) ? null : sumDecimals(rows.map(row => row[field]))
  return { quantity, unit: knownUnits[0] || '', note: quantity === null ? '部分明细数量或单位不可用，请查看外发详情。' : '' }
}

export function groupScheduleOutsourcingOrders(records: ScheduleOutsourcingRecord[]): ScheduleOutsourcingOrderSummary[] {
  const groups = new Map<string, Map<string, ScheduleOutsourcingRecord>>()
  for (const record of records) {
    const key = `${record.order_kind}:${record.order_id}`
    if (!groups.has(key)) groups.set(key, new Map())
    // 同一明细只累计一次，不能把重复接口行变成第二次加工或第二笔金额。
    if (!groups.get(key)!.has(record.id)) groups.get(key)!.set(record.id, record)
  }
  return [...groups].map(([id, recordsById]): ScheduleOutsourcingOrderSummary => {
    const rows = [...recordsById.values()]
    const first = rows[0]!
    const planned = orderQuantity(rows, 'planned_quantity', row => row.quantity_unit)
    const dispatched = orderQuantity(rows, 'dispatched_quantity', row => row.dispatched_unit)
    const received = orderQuantity(rows, 'received_quantity', row => row.received_unit)
    // 短少只累计来源明确记录的值；实发原材料与实收加工件不能相减推算。
    const shortage = orderQuantity(rows, 'shortage_quantity', row => row.received_unit || row.dispatched_unit)
    const prices = rows.map(row => decimalKey(row.unit_price))
    const priceUnits = [...new Set(rows.map(row => row.price_unit.trim()))]
    const priceUnknown = prices.some(price => price === null) || priceUnits.includes('')
    const multiplePrices = !priceUnknown && (new Set(prices).size > 1 || priceUnits.length > 1)
    const amount = sumDecimals(rows.map(row => row.planned_amount), 4)
    return {
      id, order_id: first.order_id, order_kind: first.order_kind, order_number: first.order_number,
      craft_name: first.craft_name,
      factory_name: [...new Set(rows.map(row => row.factory_name || '未录入'))].join('、'),
      planned_quantity: planned.quantity, quantity_unit: planned.unit,
      dispatched_quantity: dispatched.quantity, dispatched_unit: dispatched.unit,
      received_quantity: received.quantity, received_unit: received.unit,
      shortage_quantity: shortage.quantity, shortage_unit: shortage.unit,
      unit_price: priceUnknown || multiplePrices ? null : first.unit_price,
      price_unit: priceUnknown ? '按明细计价' : priceUnits.length > 1 ? '多种单位' : priceUnits[0]!,
      planned_amount: amount,
      expected_return_date: first.expected_return_date, status: first.status, status_display: first.status_display,
      detail_access: first.detail_access, reason: [...new Set(rows.map(row => row.reason).filter(Boolean))].join('；'),
      record_count: rows.length,
      quantity_notes: { planned_quantity: planned.note, dispatched_quantity: dispatched.note, received_quantity: received.note, shortage_quantity: shortage.note },
      unit_price_status: priceUnknown ? 'UNKNOWN' : multiplePrices ? 'MULTIPLE' : 'READY',
      unit_price_note: priceUnknown ? '部分明细缺少加工单价或计价单位，请查看详情。' : multiplePrices ? '本单存在不同加工单价或计价单位，按明细计价，不取平均。' : '',
      planned_amount_note: amount === null ? '部分明细计划加工金额不可用，暂不显示不完整合计。' : '',
    }
  })
}
