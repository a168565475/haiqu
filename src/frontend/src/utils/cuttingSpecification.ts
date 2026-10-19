// 与公共库存身份的占位值保持一致，避免裁剪明细保存后无法入库。
const emptyValues = new Set(['', '/', '—', '-', '--', '–', 'N/A', 'n/a', 'NULL', 'null'])

export function cuttingSpecificationError(value: string | null | undefined): string {
  return emptyValues.has((value || '').trim())
    ? '请填写有效规格，不能使用“/”“—”等占位符。'
    : ''
}
