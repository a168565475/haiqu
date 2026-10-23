// 页面预览使用整数计算；最终金额以服务端Decimal结果为准。
export function previewLineAmount(quantity: string, price: string): bigint | null {
  if (!/^[1-9]\d*$/.test(quantity) || !/^(0|[1-9]\d*)(\.\d{1,4})?$/.test(price)) return null
  const [whole = '0', fraction = ''] = price.split('.')
  const scaled = BigInt(whole) * 10000n + BigInt(fraction.padEnd(4, '0'))
  if (scaled <= 0n || scaled >= 1000000000000000000n) return null
  return (BigInt(quantity) * scaled + 50n) / 100n
}
export function displayCents(value: bigint): string {
  return `${value / 100n}.${(value % 100n).toString().padStart(2, '0')}`
}
