import { describe, expect, it } from 'vitest'
import type { AbsenceItem, CalendarSourceSummary, VacationItem } from '@/types/attendance'
import { absenceItemLabel, absenceItemsState, dailyOvertimeDetails, formatAbsenceDuration, formatOvertimeOriginal, formatVacationBalance, hasAbsenceActivity, hasDailyOvertimeActivity, monthlyOvertimeDetails, overtimeStatusLabel } from './attendanceAbsencePresentation'

function item(overrides: Partial<AbsenceItem> = {}): AbsenceItem {
  return { type: 1, vacation_id: 2, name: '年假', count: 1, duration: 43200, time_type: 0, ...overrides }
}
function vacation(overrides: Partial<VacationItem> = {}): VacationItem {
  return { id: 2, name: '年假', time_attr: 0, duration_type: 1, quota_type: 1, perday_duration: 28800, assignduration: 259200, real_assignduration: 259200, usedduration: 43200, leftduration: 216000, ...overrides }
}

describe('假勤来源展示', () => {
  it('缺失、明确空数组和明确零值分别保留', () => {
    expect(absenceItemsState(undefined)).toBe('missing')
    expect(absenceItemsState(null)).toBe('missing')
    expect(absenceItemsState([])).toBe('empty')
    expect(absenceItemsState([item({ count: 0, duration: 0 })])).toBe('returned')
    expect(formatAbsenceDuration(null, 0)).toBe('未返回')
    expect(formatAbsenceDuration(0, 0)).toBe('0 天')
    expect(formatAbsenceDuration(0, 1)).toBe('0 小时')
  })
  it('来源按天除86400、按小时除3600，小数不按8小时工作日改算', () => {
    expect(formatAbsenceDuration(43200, 0)).toBe('0.5 天')
    expect(formatAbsenceDuration(5400, 1)).toBe('1.5 小时')
    expect(formatAbsenceDuration(1, 0)).not.toBe('0 天')
    expect(formatAbsenceDuration(3600, 9)).toContain('3,600 秒')
    expect(formatAbsenceDuration(3600, 9)).toContain('未换算')
    expect(formatAbsenceDuration(3600, null)).not.toContain('小时')
    expect(formatAbsenceDuration(Number.NaN, 0)).toBe('未返回')
  })
  it('只有正次数或正时长才标发生，未知类型保留名称且外出不当出差', () => {
    expect(hasAbsenceActivity(item({ count: 0, duration: null }))).toBe(false)
    expect(hasAbsenceActivity(item({ count: null, duration: 0 }))).toBe(false)
    expect(hasAbsenceActivity(item({ count: 0, duration: 1 }))).toBe(true)
    expect(hasAbsenceActivity(item({ count: 1, duration: null }))).toBe(true)
    expect(absenceItemLabel(item())).toBe('请假 · 年假')
    expect(absenceItemLabel(item({ type: 4, name: '外出' }))).toBe('外出')
    expect(absenceItemLabel(item({ type: 15, name: null }))).toBe('审批打卡')
    expect(absenceItemLabel(item({ type: 999, name: '来源自定义假勤' }))).toBe('来源自定义假勤')
    expect(absenceItemLabel(item({ type: 999, name: null }))).toBe('来源类型 999')
  })
  it('同日多日报及同类重复项独立保留，不按名称或假种合并', () => {
    const sources: CalendarSourceSummary[] = [
      { record_id: 'source-1', sp_items: [item(), item({ duration: 86400 })], ot_info: null },
      { record_id: 'source-2', sp_items: [item({ duration: 7200, time_type: 1 })], ot_info: null },
    ]
    expect(sources.map(source => source.sp_items?.map(value => formatAbsenceDuration(value.duration, value.time_type)))).toEqual([['0.5 天', '1 天'], ['2 小时']])
    expect(sources.map(source => source.record_id)).toEqual(['source-1', 'source-2'])
  })
  it('加班状态独立，单位未明原值和数组不标成小时或相加', () => {
    expect(overtimeStatusLabel(undefined)).toBe('未返回')
    expect(overtimeStatusLabel(0)).toBe('无加班')
    expect(overtimeStatusLabel(1)).toBe('加班正常')
    expect(overtimeStatusLabel(2)).toBe('加班缺时长')
    expect(overtimeStatusLabel(99)).toBe('来源状态 99')
    expect(formatOvertimeOriginal(3600)).toBe('3,600（来源单位待核实）')
    expect(formatOvertimeOriginal([120, 240])).toBe('120、240（来源单位待核实）')
    expect(formatOvertimeOriginal(null)).toBe('未返回')
    expect(formatOvertimeOriginal([])).toBe('来源返回空数组')
    expect(hasDailyOvertimeActivity({ ot_status: 1 })).toBe(true)
    expect(hasDailyOvertimeActivity({ ot_status: 2, ot_duration: 0 })).toBe(true)
    expect(hasDailyOvertimeActivity({ ot_status: 99 })).toBe(false)
    expect(hasDailyOvertimeActivity({ ot_status: 1, ot_duration: 1 })).toBe(true)
    expect(hasDailyOvertimeActivity({ ot_status: 0, ot_duration: 1 })).toBe(false)
  })
  it('日报单数与月报复数分项字段分别取值，未知不补零，计加班费仍是时长', () => {
    expect(dailyOvertimeDetails(null)).toBeNull()
    const daily = dailyOvertimeDetails({ workday_over_as_vacation: 7200, workday_over_as_money: 0 })!
    expect(daily.find(row => row.key === 'workday_over_as_vacation')).toMatchObject({ label: '工作日加班转调休', value: '2 小时' })
    expect(daily.find(row => row.key === 'workday_over_as_money')).toMatchObject({ label: '工作日计加班费时长', value: '0 小时' })
    expect(daily.find(row => row.key === 'restday_over_as_money')?.value).toBe('未返回')
    const monthly = monthlyOvertimeDetails({ workday_over_sec: 10800, workdays_over_as_vacation: 7200, workdays_over_as_money: 3600 })!
    expect(monthly.find(row => row.key === 'workday_over_sec')?.value).toBe('3 小时')
    expect(monthly.find(row => row.key === 'workdays_over_as_vacation')?.value).toBe('2 小时')
    expect(monthly.find(row => row.key === 'workdays_over_as_money')?.value).toBe('1 小时')
    expect(monthly).toHaveLength(9)
  })
  it('当前余额按time_attr而非每天工时，额度不限额与未知分别显示', () => {
    expect(formatVacationBalance(vacation())).toBe('2.5 天')
    expect(formatVacationBalance(vacation({ time_attr: 1, leftduration: 5400 }))).toBe('1.5 小时')
    expect(formatVacationBalance(vacation({ leftduration: 0 }))).toBe('0 天')
    expect(formatVacationBalance(vacation({ quota_type: 0, leftduration: 0 }))).toBe('不限额')
    expect(formatVacationBalance(vacation({ leftduration: null }))).toBe('未返回')
    expect(formatVacationBalance(vacation({ time_attr: null }))).toContain('未换算')
  })
})
