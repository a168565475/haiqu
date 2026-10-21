import type { AbsenceItem, DailyOvertime, MonthlyOvertime, VacationItem } from '@/types/attendance'

const absenceTypes: Record<number, string> = { 1: '请假', 2: '补卡', 3: '出差', 4: '外出', 15: '审批打卡', 100: '外勤' }
const numberText = (value: number) => value.toLocaleString('zh-CN', { maximumFractionDigits: 6 })
const positive = (value: number | null | undefined) => typeof value === 'number' && Number.isFinite(value) && value > 0

export function absenceItemsState(items: AbsenceItem[] | null | undefined): 'missing' | 'empty' | 'returned' {
  return items == null ? 'missing' : items.length ? 'returned' : 'empty'
}
export function absenceItemLabel(item: AbsenceItem): string {
  const type = absenceTypes[item.type], name = item.name?.trim()
  return type ? name && name !== type ? `${type} · ${name}` : type : name || `来源类型 ${item.type}`
}
export function absenceTypeLabel(item: AbsenceItem): string { return absenceTypes[item.type] || item.name?.trim() || `来源类型 ${item.type}` }
export function hasAbsenceActivity(item: AbsenceItem): boolean { return positive(item.count) || positive(item.duration) }
export function formatAbsenceDuration(seconds: number | null | undefined, unit: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return '未返回'
  if (seconds < 0) return `${numberText(seconds)} 秒（来源值异常）`
  if (unit === 0) return `${numberText(seconds / 86400)} 天`
  if (unit === 1) return `${numberText(seconds / 3600)} 小时`
  return `${numberText(seconds)} 秒（${unit == null ? '展示单位未返回' : `来源刻度 ${unit}`}，未换算）`
}
export function formatVacationBalance(item: VacationItem): string {
  // 余额接口的天/小时刻度独立于排班及 perday_duration，不能按 8 小时折算。
  return item.quota_type === 0 ? '不限额' : formatAbsenceDuration(item.leftduration, item.time_attr)
}
export function overtimeStatusLabel(status: number | null | undefined): string {
  if (status == null) return '未返回'
  return ({ 0: '无加班', 1: '加班正常', 2: '加班缺时长' } as Record<number, string>)[status] || `来源状态 ${status}`
}
export function formatOvertimeOriginal(value: number | readonly number[] | null | undefined): string {
  if (value == null) return '未返回'
  if (typeof value === 'number') return Number.isFinite(value) ? `${numberText(value)}（来源单位待核实）` : '未返回'
  return value.length ? `${value.map(numberText).join('、')}（来源单位待核实）` : '来源返回空数组'
}

type DailyOvertimeField = Exclude<keyof DailyOvertime, 'ot_status' | 'ot_duration' | 'exception_duration'>
const dailyFields: [DailyOvertimeField, string][] = [
  ['workday_over_as_vacation', '工作日加班转调休'], ['workday_over_as_money', '工作日计加班费时长'],
  ['restday_over_as_vacation', '休息日加班转调休'], ['restday_over_as_money', '休息日计加班费时长'],
  ['holiday_over_as_vacation', '节假日加班转调休'], ['holiday_over_as_money', '节假日计加班费时长'],
]
const monthlyFields: [keyof MonthlyOvertime, string][] = [
  ['workday_over_sec', '工作日加班总时长'], ['restdays_over_sec', '休息日加班总时长'], ['holidays_over_sec', '节假日加班总时长'],
  ['workdays_over_as_vacation', '工作日加班转调休'], ['workdays_over_as_money', '工作日计加班费时长'],
  ['restdays_over_as_vacation', '休息日加班转调休'], ['restdays_over_as_money', '休息日计加班费时长'],
  ['holidays_over_as_vacation', '节假日加班转调休'], ['holidays_over_as_money', '节假日计加班费时长'],
]
export function hasDailyOvertimeActivity(info: DailyOvertime | null | undefined): boolean {
  if (!info || info.ot_status === 0) return false
  return info.ot_status === 1 || info.ot_status === 2 || positive(info.ot_duration) || dailyFields.some(([key]) => positive(info[key]))
}
export function dailyOvertimeDetails(info: DailyOvertime | null | undefined) {
  if (info == null) return null
  return dailyFields.map(([key, label]) => ({ key, label, value: formatAbsenceDuration(info[key], 1) }))
}
export function monthlyOvertimeDetails(info: MonthlyOvertime | null | undefined) {
  if (info == null) return null
  // 原始总量与用途分项各自展示，永远不在这里相加。
  return monthlyFields.map(([key, label]) => ({ key, label, value: formatAbsenceDuration(info[key], 1) }))
}
