import type { IssueWriteLine, MaterialAttribute, MaterialIssueLine, MaterialRequirement } from '@/types/materialIssue'

export function decimalUnits(value: unknown): bigint | null {
  const text = String(value ?? '').trim()
  if (!/^\d{1,14}(?:\.\d{1,4})?$/.test(text)) return null
  const [whole = '0', fraction = ''] = text.split('.')
  return BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))
}
export function quantityText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  const text = String(value)
  return text.includes('.') ? text.replace(/0+$/, '').replace(/\.$/, '') : text
}
export function unitsText(value: bigint): string {
  return quantityText(`${value / 10000n}.${String(value % 10000n).padStart(4, '0')}`)
}
export function omittedQuantity(value: unknown): boolean {
  return String(value ?? '').trim() === '' || decimalUnits(value) === 0n
}
function pipeCuts(row: MaterialRequirement): bigint {
  const value = row.conversion_snapshot?.pieces_per_bar
  return Number.isSafeInteger(value) && Number(value) > 0 ? BigInt(value!) : 0n
}
export function pipePlan(value: string, row: MaterialRequirement) {
  const input = decimalUnits(value)
  const cuts = pipeCuts(row)
  const invalid = { error: '管材换算规则缺失，请联系管理员核对。', bars: '—', meters: '—' }
  if (cuts <= 0n) return invalid
  if (input === null || input <= 0n || input % 10000n || input / 10000n % cuts) {
    return { ...invalid, error: `申请支数须为 ${cuts} 的正整数倍（每根切 ${cuts} 支）。` }
  }
  const length = row.conversion_snapshot?.raw_bar_length_m || ''
  if (!/^\d{1,14}(?:\.\d{1,2})?$/.test(length)) return invalid
  const [whole, fraction = ''] = length.split('.')
  const cents = BigInt(whole!) * 100n + BigInt(fraction.padEnd(2, '0'))
  if (cents <= 0n) return invalid
  const bars = input / 10000n / cuts
  const meters = bars * cents
  return { error: '', bars: String(bars), meters: `${meters / 100n}.${String(meters % 100n).padStart(2, '0')}` }
}
export function quantityError(value: string, row: MaterialRequirement): string {
  const amount = decimalUnits(value)
  if (amount === null || amount <= 0n) return '请输入大于 0 的数量，最多四位小数。'
  const integerSemi = row.line_type === 'SEMI' && (['支', '套'].includes(row.unit)
    || ['SEMI_PIPE', 'SEMI_PIPE_PIECES'].includes(row.conversion_snapshot?.kind || '')
    || row.conversion_snapshot?.integer_required === true)
  if (integerSemi && amount % 10000n) return '半成品支数和套数必须为正整数。'
  if (row.line_type === 'RAW' && row.conversion_snapshot?.kind === 'PIPE') {
    const error = pipePlan(value, row).error
    if (error) return error
  }
  const maximum = decimalUnits(row.max_issue_quantity)
  if (maximum === null) return '可领上限缺失，请刷新材料后重试。'
  if (amount > maximum) return '申请数量超过当前可领上限。'
  return ''
}
export function selectedQuantityError(value: string, row: MaterialRequirement, rows: MaterialRequirement[], selected: Record<string, string>): string {
  if (omittedQuantity(value)) return ''
  const error = quantityError(value, row)
  if (error || !row.stock_item_id) return error
  const isPipe = row.line_type === 'RAW' && row.conversion_snapshot?.kind === 'PIPE'
  const cuts = isPipe ? pipeCuts(row) : 1n
  const maximum = decimalUnits(row.max_issue_quantity)!
  const total = rows.filter(item => item.line_type === row.line_type && item.stock_item_id === row.stock_item_id
    && item.unit === row.unit && item.stock_mode === row.stock_mode
    && (!isPipe || item.conversion_snapshot?.raw_bar_length_m === row.conversion_snapshot?.raw_bar_length_m))
    .reduce((sum, item) => {
      const amount = decimalUnits(item.requirement_id === row.requirement_id ? value : selected[item.requirement_id])
      const itemCuts = isPipe ? pipeCuts(item) : 1n
      return sum + (amount !== null && amount > 0n && itemCuts > 0n ? amount / itemCuts : 0n)
    }, 0n)
  return total > maximum / cuts ? '相同物料的合计申请数量超过扣除占用后的可用库存。' : ''
}
export function buildIssueLines(rows: MaterialRequirement[], selected: Record<string, string>): IssueWriteLine[] {
  return rows.flatMap((row) => {
    const value = selected[row.requirement_id]
    if (omittedQuantity(value)) return []
    const error = selectedQuantityError(value!, row, rows, selected)
    if (error) throw new Error(`${row.material_name}：${error}`)
    if (row.stock_mode === 'PUBLIC_V2' || row.line_type !== 'SEMI' || !row.semi_balance_allocations?.length) {
      return [{ requirement_id: row.requirement_id, requested_quantity: value!.trim() }]
    }
    let remaining = decimalUnits(value)!
    const lines: IssueWriteLine[] = []
    for (const allocation of row.semi_balance_allocations) {
      const capacity = decimalUnits(allocation.max_issue_quantity)
      if (capacity === null) throw new Error(`${row.material_name}：半成品库存分配数量无效，请刷新。`)
      const amount = remaining < capacity ? remaining : capacity
      if (amount > 0n) lines.push({ requirement_id: allocation.balance_id, requested_quantity: unitsText(amount) })
      remaining -= amount
      if (remaining === 0n) break
    }
    if (remaining > 0n) throw new Error(`${row.material_name}：半成品可分配库存不足，请刷新后重试。`)
    return lines
  })
}
export function restoreIssueQuantities(lines: MaterialIssueLine[], rows: MaterialRequirement[]): Record<string, string> {
  const restored: Record<string, string> = {}
  for (const line of lines) {
    const row = rows.find(item => item.requirement_id === line.requirement_id || (item.stock_mode !== 'PUBLIC_V2'
      && item.semi_balance_allocations?.some(allocation => allocation.balance_id === line.requirement_id)))
    if (!row) throw new Error('原申请有材料已不在当前可领范围。为避免丢失明细，已停止修改，请在 ERP 核对。')
    const amount = decimalUnits(line.requested_quantity)
    if (amount === null) throw new Error('原申请数量无效，请在 ERP 核对。')
    restored[row.requirement_id] = unitsText((decimalUnits(restored[row.requirement_id]) || 0n) + amount)
  }
  return restored
}

const attributeLabels: Record<string, string> = {
  material: '材质', color: '颜色', shape: '截面形状', section_size: '规格', thickness: '厚度', length: '长度',
  fabric_spec: '面料规格', width: '宽度', gram_weight: '克重', finish: '后处理', surface_finish: '表面处理',
  specification: '规格', size: '尺寸', thread: '螺纹规格', flow_unit: '流转单位', model: '型号', tube_size: '适配管材',
  layers: '层数', box_type: '箱子形状', printing: '印刷版本', bag_type: '袋型', process: '加工工艺',
}
export function materialAttributes(row: Pick<MaterialRequirement, 'material_selection_snapshot' | 'bom_attributes'>): MaterialAttribute[] {
  const snapshot = row.material_selection_snapshot
  if (snapshot?.schema_version === 1 && snapshot.attributes) {
    return [
      ...Object.entries(snapshot.attributes).map(([key, value]) => ({ key, label: attributeLabels[key] || key, value })),
      ...(snapshot.color_card ? [{ key: 'color_card', label: '色卡', value: snapshot.color_card }] : []),
      ...(snapshot.color_code ? [{ key: 'color_code', label: '色号', value: snapshot.color_code }] : []),
    ].filter(field => String(field.value).trim())
  }
  return row.bom_attributes || []
}
