import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { AxiosRequestConfig } from 'axios'
import { apiClient } from './request'
import { getAttendanceCalendar, getAttendanceDaily, getAttendanceMonthly, getAttendanceOverview, getAttendanceRaw, getAttendanceRules, getAttendanceSchedule, getAttendanceVacation, saveAttendanceSchedule, startAttendanceSync, stepAttendanceSync } from './attendance'

const originalAdapter = apiClient.defaults.adapter
let requests: AxiosRequestConfig[] = []
let responseData: unknown
let responseHeaders: Record<string, string>
beforeEach(() => {
  requests = []; responseHeaders = {}; responseData = { data: [] }
  apiClient.defaults.adapter = async config => {
    requests.push(config)
    return { status: 200, statusText: 'OK', config, headers: responseHeaders, data: responseData }
  }
})
afterEach(() => { apiClient.defaults.adapter = originalAdapter })

describe('考勤API请求边界', () => {
  it('余额只读接口保留精确成员和当前读取时间，不补历史月份或缺失余额', async () => {
    const signal = new AbortController().signal
    const current = { user_id: 'User.Case', fetched_at: '2026-10-20T03:00:00Z', is_current: true, items: [{ id: 2, name: '年假', time_attr: 0, leftduration: null }] }
    responseData = { data: current }
    expect(await getAttendanceVacation('2026-09', 'User.Case', signal)).toEqual(current)
    expect(requests[0]?.url).toBe('/api/v1/attendance/vacation/')
    expect(requests[0]?.method).toBe('get')
    expect(requests[0]?.params).toEqual({ month: '2026-09', user_id: 'User.Case' })
    expect(requests[0]?.signal).toBe(signal)
    expect(requests).toHaveLength(1)
  })
  it('排班读取使用响应版本，保存携带月份、来源与If-Match，不自动读外部规则', async () => {
    responseData = { data: { month: '2026-09', days: [], etag: 'body-v1' } }
    responseHeaders = { etag: 'header-v1' }
    const schedule = await getAttendanceSchedule('2026-09')
    expect(schedule.etag).toBe('header-v1')
    expect(requests[0]?.params).toEqual({ month: '2026-09' })
    await saveAttendanceSchedule('2026-09', { days: [], import_token: 'signed-source' }, schedule.etag)
    expect(requests[1]?.url).toBe('/api/v1/attendance/schedule/')
    expect(requests[1]?.method).toBe('put')
    expect(requests[1]?.headers?.['If-Match']).toBe('header-v1')
    expect(JSON.parse(String(requests[1]?.data))).toEqual({ days: [], import_token: 'signed-source' })
    expect(requests).toHaveLength(2)
    await expect(saveAttendanceSchedule('2026-09', { days: [], import_token: null }, '')).rejects.toThrow('版本')
    expect(requests).toHaveLength(2)
    const rules = { rules: [], fetched_at: '2026-10-20T00:00:00Z' }
    responseData = { data: rules }
    expect(await getAttendanceRules('2026-09')).toEqual(rules)
    expect(requests[2]?.url).toBe('/api/v1/attendance/rules/')
  })
  it('解包单对象，分页保留服务端总数，筛选保留UserID精确值', async () => {
    responseData = { data: { month: '2026-09', has_data: false } }
    expect(await getAttendanceOverview('2026-09')).toEqual({ month: '2026-09', has_data: false })
    expect(requests[0]?.url).toBe('/api/v1/attendance/overview/')
    const page = { data: [{ user_id: 'User.Case' }], count: 256, page: 2, page_size: 20 }
    responseData = page
    expect(await getAttendanceMonthly({ month: '2026-09', user_id: 'User.Case', binding: 'UNBOUND', status: 'NOT_RETURNED', page: 2, page_size: 20 })).toEqual(page)
    expect(requests[1]?.params).toMatchObject({ user_id: 'User.Case', binding: 'UNBOUND', status: 'NOT_RETURNED', page: 2 })
  })
  it('日报、明细和月历使用正确路由、日期和取消信号', async () => {
    const signal = new AbortController().signal
    await getAttendanceDaily({ month: '2026-09', date: '2026-09-15' }, signal)
    await getAttendanceRaw({ month: '2026-09', date: '2026-09-15' }, signal)
    await getAttendanceCalendar('2026-09', 'User.Case', signal)
    expect(requests.map(request => request.url)).toEqual(['/api/v1/attendance/records/daily/', '/api/v1/attendance/records/raw/', '/api/v1/attendance/calendar/'])
    expect(requests[2]?.params).toEqual({ month: '2026-09', user_id: 'User.Case' })
    expect(requests.every(request => request.signal === signal)).toBe(true)
  })
  it('同步创建沿用幂等键，推进携带If-Match并优先使用响应头新版本', async () => {
    responseData = { data: { id: 'run-1', status: 'PENDING', etag: 'body-v1' } }
    responseHeaders = { etag: 'header-v1' }
    const run = await startAttendanceSync('2026-09', '00000000-0000-4000-8000-000000000001')
    expect(run.etag).toBe('header-v1')
    expect(JSON.parse(String(requests[0]?.data))).toEqual({ month: '2026-09', idempotency_key: '00000000-0000-4000-8000-000000000001' })
    await stepAttendanceSync(run.id, run.etag)
    expect(requests[1]?.headers?.['If-Match']).toBe('header-v1')
    expect(requests[1]?.url).toBe('/api/v1/attendance/sync-runs/run-1/step/')
  })
  it('缺少版本不得推进写请求，也不把无版本响应冒充可继续', async () => {
    await expect(stepAttendanceSync('run-1', '')).rejects.toThrow('版本')
    expect(requests).toHaveLength(0)
    responseData = { data: { id: 'run-1', status: 'PENDING' } }
    await expect(startAttendanceSync('2026-09', '00000000-0000-4000-8000-000000000001')).rejects.toThrow('版本')
  })
})
