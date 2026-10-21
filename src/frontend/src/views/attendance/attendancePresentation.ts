import type { CalendarDay, ExceptionItem } from '@/types/attendance'

export const stateLabels: Record<string, string> = {
  normal: '正常打卡', zero: '明确未打卡', late: '迟到', early: '早退', missing: '缺卡', absent: '旷工',
  location: '地点异常', device: '设备异常', unknown: '未返回数据', future: '未来日期', recorded: '有打卡记录', rest: '休息安排',
}
export const exceptionLabels: Record<number, string> = { 1: '迟到', 2: '早退', 3: '缺卡', 4: '旷工', 5: '地点异常', 6: '设备异常' }
const exceptionStates: Record<number, string> = { 1: 'late', 2: 'early', 3: 'missing', 4: 'absent', 5: 'location', 6: 'device' }

export function shanghaiDate(date = new Date()): string {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}
export function currentMonth(date = new Date()): string { return shanghaiDate(date).slice(0, 7) }
export function departmentOptions(paths: string[]): { value: string; label: string }[] {
  // 路径只用于缩短展示，完整来源值始终作为选项身份，不在前端拆分多部门。
  const parts = paths.map(path => path.split('/').map(part => part.trim()).filter(Boolean))
  const commonRoot = parts.length > 0 && parts.every(path => path[0] === parts[0]?.[0])
  const labels = parts.map((path, index) => {
    const visible = commonRoot && path.length > 1 ? path.slice(1) : path
    return { value: paths[index]!, label: visible.slice(-2).join(' / ') || paths[index]!, fullLabel: visible.join(' / ') }
  })
  return labels.map(option => ({ value: option.value, label: labels.filter(item => item.label === option.label).length > 1 ? option.fullLabel : option.label }))
}
export function monthLabel(month: string): string {
  const [year, number] = month.split('-')
  return `${year} 年 ${Number(number)} 月`
}
export function validMonth(month: string): boolean { return /^\d{4}-(0[1-9]|1[0-2])$/.test(month) && Number(month.slice(0, 4)) >= 2000 }
export function calendarCells(month: string, days: CalendarDay[]): (CalendarDay | null)[] {
  if (!validMonth(month)) return []
  const [year, number] = month.split('-').map(Number) as [number, number]
  const count = new Date(Date.UTC(year, number, 0)).getUTCDate()
  const offset = (new Date(Date.UTC(year, number - 1, 1)).getUTCDay() + 6) % 7
  const indexed = new Map(days.map(day => [day.date, day]))
  return [...Array<null>(offset).fill(null), ...Array.from({ length: count }, (_, index) => {
    const date = `${month}-${String(index + 1).padStart(2, '0')}`
    return indexed.get(date) ?? { date, report_returned: false, checkin_count: null, states: [date > shanghaiDate() ? 'future' : 'unknown'], exceptions: null, raw: [], schedule: null }
  })]
}
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '未返回'
  const hours = Math.floor(seconds / 3600), minutes = Math.floor(seconds % 3600 / 60), remainder = seconds % 60
  const parts = [hours ? `${hours} 小时` : '', minutes ? `${minutes} 分钟` : '', remainder ? `${remainder} 秒` : ''].filter(Boolean)
  return parts.join(' ') || '0 分钟'
}
export function sourceNumber(value: number | null | undefined, unit = ''): string { return value == null ? '未返回' : `${value.toLocaleString('zh-CN')}${unit}` }
export function shanghaiTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间未返回' : new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).format(date)
}
export function shanghaiDateTime(value: string | null | undefined): string {
  if (!value) return '尚无成功同步'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间未返回' : `${shanghaiDate(date)} ${shanghaiTime(value)}`
}
export function attendanceStates(day: CalendarDay): string[] {
  // 展示正常必须有日报次数和完整无异常证据；原始流水不能代替全天统计。
  const complete = day.report_returned && day.checkin_count !== null && day.exceptions !== null && day.exceptions.every(item => item.count !== null)
  const normal = complete && (day.checkin_count ?? 0) > 0 && day.exceptions!.every(item => item.count === 0)
  const states = day.states.filter(state => Object.hasOwn(stateLabels, state) && (state !== 'rest' || day.schedule?.kind === 'REST') && (state !== 'normal' || normal) && (state !== 'zero' || day.report_returned && day.checkin_count === 0))
  for (const item of day.exceptions ?? []) {
    const state = exceptionStates[item.type]
    if (state && item.count !== null && item.count > 0 && !states.includes(state)) states.push(state)
  }
  if (!states.length) states.push('unknown')
  if (day.schedule?.kind === 'REST' && !states.includes('rest')) states.push('rest')
  return states
}
export function exceptionText(items: ExceptionItem[] | null): string {
  if (items === null) return '未返回'
  if (!items.length) return '来源无异常'
  return items.map(item => `${exceptionLabels[item.type] || `来源类型 ${item.type}`}：${sourceNumber(item.count, ' 次')}`).join('；')
}
