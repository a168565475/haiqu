export interface AttendancePage<T> {
  data: T[]
  count: number
  page: number
  page_size: number
}

export type AttendanceTab = 'monthly' | 'daily' | 'raw'
export interface AttendanceQuery {
  month: string
  search?: string
  department?: string
  user_id?: string
  binding?: 'BOUND' | 'UNBOUND'
  status?: 'RETURNED' | 'NOT_RETURNED'
  date?: string
  page?: number
  page_size?: number
}

export interface SyncRun {
  id: string
  month: string
  status: 'PENDING' | 'RUNNING' | 'FAILED' | 'SUCCESS' | 'INVALIDATED'
  phase: string
  completed_steps: number
  total_steps: number
  scanned_members: number
  error_code: string
  error_message: string
  can_retry: boolean
  etag: string
  created_at: string
  updated_at: string
}

export interface AttendanceOverview {
  month: string
  corp_id: string
  has_data: boolean
  last_synced_at: string | null
  scanned_members: number
  attendance_members: number
  raw_count: number
  daily_count: number
  monthly_count: number
  source_start: string | null
  source_end: string | null
  departments: string[]
  current_run: SyncRun | null
  history_notice: string
}

export interface MonthlyRow {
  user_id: string
  name: string
  department_name: string
  employee_id: string | null
  employee_name: string | null
  record_status: 'RETURNED' | 'NOT_RETURNED'
  work_days: number | null
  standard_work_sec: number | null
  regular_work_sec: number | null
  late_count: number | null
  early_count: number | null
  missing_count: number | null
  sp_items?: AbsenceItem[] | null
  overwork_info?: MonthlyOvertime | null
}

export interface ExceptionItem { type: number; count: number | null }
export interface AbsenceItem {
  type: number
  vacation_id: number | null
  count: number | null
  duration: number | null
  time_type: number | null
  name: string | null
}
export interface DailyOvertime {
  ot_status?: number | null
  ot_duration?: number | null
  exception_duration?: number[] | null
  workday_over_as_vacation?: number | null
  workday_over_as_money?: number | null
  restday_over_as_vacation?: number | null
  restday_over_as_money?: number | null
  holiday_over_as_vacation?: number | null
  holiday_over_as_money?: number | null
}
export interface MonthlyOvertime {
  workday_over_sec?: number | null
  restdays_over_sec?: number | null
  holidays_over_sec?: number | null
  workdays_over_as_vacation?: number | null
  workdays_over_as_money?: number | null
  restdays_over_as_vacation?: number | null
  restdays_over_as_money?: number | null
  holidays_over_as_vacation?: number | null
  holidays_over_as_money?: number | null
}
export interface DailyRow {
  id: string
  date: string
  user_id: string
  name: string
  department_name: string
  group_name: string
  schedule_name: string
  checkin_count: number | null
  standard_work_sec: number | null
  regular_work_sec: number | null
  exceptions: ExceptionItem[] | null
  sp_items?: AbsenceItem[] | null
  ot_info?: DailyOvertime | null
}

export interface RawRow {
  id: string
  date: string
  user_id: string
  name: string
  department_name: string
  checkin_time: string
  checkin_type: string
  group_name: string
  exceptions: string[]
}

export interface CalendarDay {
  date: string
  report_returned: boolean
  checkin_count: number | null
  states: string[]
  exceptions: ExceptionItem[] | null
  raw: RawRow[]
  schedule: ScheduleDay | null
  source_summaries?: CalendarSourceSummary[] | null
}
export interface CalendarSourceSummary {
  record_id: string | null
  sp_items?: AbsenceItem[] | null
  ot_info?: DailyOvertime | null
}
export interface AttendanceCalendar {
  month: string
  user_id: string
  name: string
  days: CalendarDay[]
}

export interface VacationItem {
  id: number
  name: string | null
  time_attr: number | null
  duration_type: number | null
  quota_type: number | null
  perday_duration: number | null
  assignduration: number | null
  real_assignduration: number | null
  usedduration: number | null
  leftduration: number | null
}
export interface AttendanceVacation {
  user_id: string
  fetched_at: string
  is_current: true
  items: VacationItem[]
}

export type ScheduleKind = 'WORK' | 'REST' | 'UNSET'
export interface SchedulePeriod { start_sec: number; end_sec: number }
export interface ScheduleDay { date: string; kind: ScheduleKind; periods: SchedulePeriod[] }
export interface ScheduleSource { rule_id: number; rule_name: string; fetched_at: string; warnings: string[] }
export interface AttendanceSchedule {
  month: string
  configured: boolean
  days: ScheduleDay[]
  source: ScheduleSource | null
  import_token: string | null
  etag: string
}
export interface AttendanceRuleOption {
  id: number
  name: string
  type: number
  can_import: boolean
  reason: string
  days: ScheduleDay[]
  warnings: string[]
  import_token: string | null
}
export interface AttendanceRules { rules: AttendanceRuleOption[]; fetched_at: string }
