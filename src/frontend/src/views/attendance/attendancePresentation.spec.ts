import { describe, expect, it } from 'vitest'
import { attendanceStates, calendarCells, currentMonth, departmentOptions, formatDuration, shanghaiTime } from './attendancePresentation'
import type { CalendarDay } from '@/types/attendance'

function day(overrides: Partial<CalendarDay> = {}): CalendarDay {
  return { date: '2026-09-15', report_returned: true, checkin_count: 2, states: ['normal'], exceptions: [], raw: [], schedule: null, ...overrides }
}

describe('考勤日期和来源展示', () => {
  it('部门标签去共同根并保留末级路径，选项身份始终是来源完整路径', () => {
    const paths = ['来源企业 / 总部 / 行政', '来源企业 / 工厂 / 行政', '来源企业 / 工厂 / 车间 / 装配']
    expect(departmentOptions(paths)).toEqual([
      { value: paths[0], label: '总部 / 行政' },
      { value: paths[1], label: '工厂 / 行政' },
      { value: paths[2], label: '车间 / 装配' },
    ])
    expect(departmentOptions(['来源企业 / 行政', '来源企业 / 生产']).map(option => option.label)).toEqual(['行政', '生产'])
  })
  it('同名异路径不合并，来源单项不按多部门分隔符拆成新身份', () => {
    const paths = ['来源企业 / 总部 / 运营 / 销售', '来源企业 / 工厂 / 运营 / 销售', '原样来源；仍是一个选项']
    const options = departmentOptions(paths)
    expect(options.map(option => option.value)).toEqual(paths)
    expect(new Set(options.map(option => option.label)).size).toBe(3)
    expect(options[2]).toEqual({ value: paths[2], label: paths[2] })
  })
  it('当月按北京时间确定，处理跨年和UTC月末', () => {
    expect(currentMonth(new Date('2026-12-31T16:10:00Z'))).toBe('2027-01')
    expect(currentMonth(new Date('2026-09-30T16:10:00Z'))).toBe('2026-10')
    expect(currentMonth(new Date('2026-09-30T15:59:00Z'))).toBe('2026-09')
  })
  it('完整月历以周一开始，闰年二月包含29天，无来源日期保留空来源', () => {
    const cells = calendarCells('2024-02', [])
    expect(cells.slice(0, 3)).toEqual([null, null, null])
    expect(cells[3]).toMatchObject({ date: '2024-02-01', report_returned: false, checkin_count: null })
    expect(cells.filter(Boolean)).toHaveLength(29)
    expect(cells.at(-1)?.date).toBe('2024-02-29')
  })
  it('不把未知时长、未知次数当成0，按秒精确展示时长和北京时间', () => {
    expect(formatDuration(null)).toBe('未返回')
    expect(formatDuration(0)).toBe('0 分钟')
    expect(formatDuration(3631)).toBe('1 小时 31 秒')
    expect(shanghaiTime('2026-09-15T01:12:00Z')).toBe('09:12:00')
  })
  it('日报未返回即使有流水也不冒充正常，来源异常同时保留', () => {
    expect(attendanceStates(day({ report_returned: false, checkin_count: null, exceptions: null, states: ['recorded', 'unknown', 'normal'] }))).toEqual(['recorded', 'unknown'])
    expect(attendanceStates(day({ states: ['late', 'early'], exceptions: [{ type: 1, count: 1 }, { type: 2, count: 1 }] }))).toEqual(['late', 'early'])
    expect(attendanceStates(day({ exceptions: null }))).toEqual(['unknown'])
    expect(attendanceStates(day({ exceptions: [{ type: 1, count: null }] }))).not.toContain('normal')
    expect(attendanceStates(day({ checkin_count: 0, states: ['zero'] }))).toEqual(['zero'])
  })
  it('ERP休息安排独立保留，不能覆盖企微同日迟到早退', () => {
    expect(attendanceStates(day({ states: ['late', 'early', 'rest'], exceptions: [{ type: 1, count: 1 }, { type: 2, count: 1 }], schedule: { date: '2026-09-15', kind: 'REST', periods: [] } }))).toEqual(['late', 'early', 'rest'])
  })
})
