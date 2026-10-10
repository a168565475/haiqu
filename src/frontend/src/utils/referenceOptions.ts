import type { ContactOption } from '@/types/contact'
import type { CustomerDictionaryOption } from '@/types/customer'
import type { PublishedOption } from '@/types/referenceData'

export function toCustomerDictionaryOptions(options: PublishedOption[]): CustomerDictionaryOption[] {
  return options.map((item) => ({
    id: item.id,
      item_code: item.code,
      display_name: item.label,
      description: typeof item.extra.description === 'string' ? item.extra.description : '',
    }))
}

export function withHistoricalCustomerOption(
  options: CustomerDictionaryOption[],
  current: { id?: string; item_code: string; display_name?: string } | null | undefined,
): CustomerDictionaryOption[] {
  if (!current?.item_code || options.some((item) => item.item_code === current.item_code)) return options
  return [...options, {
    id: current.id || `historical:${current.item_code}`,
    item_code: current.item_code,
    display_name: current.display_name || `${current.item_code}（已停用）`,
    description: '已停用，仅保留当前历史值',
    disabled: true,
  }]
}

export function toContactOptions(
  options: PublishedOption[],
  valueFromExtra?: string,
): ContactOption[] {
  return options.flatMap((item) => {
    const extraValue = valueFromExtra ? item.extra[valueFromExtra] : undefined
    const value = typeof extraValue === 'string' ? extraValue : item.code
    return value ? [{ value, label: item.label }] : []
  })
}

export function withHistoricalContactOption(options: ContactOption[], value: string): ContactOption[] {
  if (!value || options.some((item) => item.value === value)) return options
  return [...options, { value, label: `${value}（已停用）`, disabled: true }]
}
