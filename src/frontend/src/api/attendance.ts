import { isAxiosError } from 'axios'
import { apiClient } from './request'
import type { AttendanceCalendar, AttendanceOverview, AttendancePage, AttendanceQuery, AttendanceRules, AttendanceSchedule, AttendanceVacation, DailyRow, MonthlyRow, RawRow, ScheduleDay, SyncRun } from '@/types/attendance'

const root = '/api/v1/attendance/'
const options = (signal?: AbortSignal) => ({ timeout: 20000, signal })

export async function getAttendanceOverview(month: string, signal?: AbortSignal): Promise<AttendanceOverview> {
  return (await apiClient.get<{ data: AttendanceOverview }>(root + 'overview/', { ...options(signal), params: { month } })).data.data
}
export async function getAttendanceMonthly(params: AttendanceQuery, signal?: AbortSignal): Promise<AttendancePage<MonthlyRow>> {
  return (await apiClient.get<AttendancePage<MonthlyRow>>(root + 'records/monthly/', { ...options(signal), params })).data
}
export async function getAttendanceDaily(params: AttendanceQuery, signal?: AbortSignal): Promise<AttendancePage<DailyRow>> {
  return (await apiClient.get<AttendancePage<DailyRow>>(root + 'records/daily/', { ...options(signal), params })).data
}
export async function getAttendanceRaw(params: AttendanceQuery, signal?: AbortSignal): Promise<AttendancePage<RawRow>> {
  return (await apiClient.get<AttendancePage<RawRow>>(root + 'records/raw/', { ...options(signal), params })).data
}
export async function getAttendanceCalendar(month: string, userId: string, signal?: AbortSignal): Promise<AttendanceCalendar> {
  return (await apiClient.get<{ data: AttendanceCalendar }>(root + 'calendar/', { ...options(signal), params: { month, user_id: userId } })).data.data
}
export async function getAttendanceVacation(month: string, userId: string, signal?: AbortSignal): Promise<AttendanceVacation> {
  return (await apiClient.get<{ data: AttendanceVacation }>(root + 'vacation/', { ...options(signal), params: { month, user_id: userId } })).data.data
}
function scheduleResult(response: { data: { data: AttendanceSchedule }; headers: Record<string, unknown> }): AttendanceSchedule {
  const etag = response.headers.etag || response.data.data.etag
  if (typeof etag !== 'string' || !etag) throw new Error('排班版本缺失，请重新读取后重试。')
  return { ...response.data.data, etag }
}
export async function getAttendanceSchedule(month: string, signal?: AbortSignal): Promise<AttendanceSchedule> {
  return scheduleResult(await apiClient.get<{ data: AttendanceSchedule }>(root + 'schedule/', { ...options(signal), params: { month } }))
}
export async function saveAttendanceSchedule(month: string, payload: { days: ScheduleDay[]; import_token: string | null }, etag: string, signal?: AbortSignal): Promise<AttendanceSchedule> {
  if (!etag) throw new Error('排班版本缺失，请重新读取后重试。')
  return scheduleResult(await apiClient.put<{ data: AttendanceSchedule }>(root + 'schedule/', { ...payload }, { ...options(signal), params: { month }, headers: { 'If-Match': etag } }))
}
export async function getAttendanceRules(month: string, signal?: AbortSignal): Promise<AttendanceRules> {
  return (await apiClient.get<{ data: AttendanceRules }>(root + 'rules/', { ...options(signal), params: { month } })).data.data
}
function runResult(response: { data: { data: SyncRun }; headers: Record<string, unknown> }): SyncRun {
  const etag = response.headers.etag || response.data.data.etag
  if (typeof etag !== 'string' || !etag) throw new Error('同步版本缺失，请刷新进度后重试。')
  return { ...response.data.data, etag }
}
export async function startAttendanceSync(month: string, idempotencyKey: string, signal?: AbortSignal): Promise<SyncRun> {
  return runResult(await apiClient.post<{ data: SyncRun }>(root + 'sync-runs/', { month, idempotency_key: idempotencyKey }, options(signal)))
}
export async function getAttendanceSync(id: string, signal?: AbortSignal): Promise<SyncRun> {
  return runResult(await apiClient.get<{ data: SyncRun }>(root + `sync-runs/${encodeURIComponent(id)}/`, options(signal)))
}
export async function stepAttendanceSync(id: string, etag: string, signal?: AbortSignal): Promise<SyncRun> {
  if (!etag) throw new Error('同步版本缺失，请刷新进度后重试。')
  return runResult(await apiClient.post<{ data: SyncRun }>(root + `sync-runs/${encodeURIComponent(id)}/step/`, {}, { ...options(signal), headers: { 'If-Match': etag } }))
}

export function attendanceError(error: unknown): string {
  if (!isAxiosError(error) || !error.response) return '请求结果未确认，请重新读取后再操作。'
  const status = error.response.status
  if (status === 401) return '登录状态已失效，请重新登录。'
  if (status === 403) return '当前账号无权访问考勤或执行此操作。'
  if (status === 409 || status === 412) return '数据或同步进度已变化，请重新读取最新版本后继续。'
  if (status === 428) return '缺少数据版本，请重新读取后再操作。'
  if (status === 429) return '请求频繁，请稍后重试。'
  if (status === 400) return '月份、筛选或月度安排无效，请核对；规则来源过期时请重新读取。'
  if (status === 404) return '未找到该月份或成员的可用记录。'
  if (status === 502) return '企业微信打卡接口读取失败，请检查打卡接口授权、应用可见范围和可信 IP，或稍后重试。'
  return '考勤服务暂时不可用，请稍后重试；已有成功数据仍保留。'
}
