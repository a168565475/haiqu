<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElButton } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { attendanceError, getAttendanceRules, getAttendanceSchedule, saveAttendanceSchedule } from '@/api/attendance'
import { useAuthStore } from '@/stores/auth'
import type { AttendanceRuleOption, AttendanceSchedule, ScheduleDay } from '@/types/attendance'
import { monthLabel } from './attendancePresentation'

const props = defineProps<{ modelValue: boolean; month: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: []; forbidden: [] }>()
const auth = useAuthStore()
const canManage = computed(() => auth.hasPermission('attendance.view_attendance') && auth.hasPermission('attendance.manage_schedule'))
const loading = ref(false), rulesLoading = ref(false), saving = ref(false), error = ref(''), saveBlocked = ref(false)
const schedule = ref<AttendanceSchedule | null>(null), days = ref<ScheduleDay[]>([]), rules = ref<AttendanceRuleOption[]>([])
const etag = ref(''), importToken = ref<string | null>(null), selectedRuleId = ref('')
const startTime = ref(''), endTime = ref(''), weekdays = ref<number[]>([])
const selectedDate = ref('')
const selectedDay = computed(() => days.value.find(day => day.date === selectedDate.value))
const calendarDays = computed(() => {
  const offset = (new Date(`${props.month}-01T00:00:00Z`).getUTCDay() + 6) % 7
  return [...Array.from<null>({ length: offset }).fill(null), ...days.value]
})
let requestNo = 0
const invalidTimes = new Set<string>()

function clone<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T }
function clearDraft() {
  requestNo += 1
  schedule.value = null; days.value = []; rules.value = []; etag.value = ''; importToken.value = null; selectedRuleId.value = ''
  startTime.value = ''; endTime.value = ''; weekdays.value = []
  selectedDate.value = ''
  loading.value = false; rulesLoading.value = false; saving.value = false; saveBlocked.value = false; error.value = ''
  invalidTimes.clear()
}
function isCurrent(current: number): boolean { return current === requestNo && props.modelValue && canManage.value }
function accessFailure(cause: unknown): boolean {
  const status = (cause as { response?: { status?: number } })?.response?.status
  if (status !== 401 && status !== 403) return false
  clearDraft(); saveBlocked.value = true; error.value = '当前账号已无权管理月度安排。'; emit('forbidden')
  return true
}
function resetDraft(value: AttendanceSchedule) {
  schedule.value = value; days.value = clone(value.days); etag.value = value.etag; importToken.value = value.import_token
  selectedRuleId.value = ''; error.value = ''; saveBlocked.value = false
  selectedDate.value = value.days[0]?.date ?? ''
  invalidTimes.clear()
}
function toSeconds(value: string): number | null {
  const match = /^(\d{2}):(\d{2})$/.exec(value)
  if (!match) return null
  const hour = Number(match[1]), minute = Number(match[2])
  return hour <= 23 && minute <= 59 ? hour * 3600 + minute * 60 : null
}
function timeText(seconds: number): string { return `${String(Math.floor(seconds / 3600)).padStart(2, '0')}:${String(Math.floor(seconds % 3600 / 60)).padStart(2, '0')}` }
function monthDates(month: string): string[] {
  const [year, number] = month.split('-').map(Number) as [number, number]
  const count = new Date(Date.UTC(year, number, 0)).getUTCDate()
  return Array.from({ length: count }, (_, index) => `${month}-${String(index + 1).padStart(2, '0')}`)
}
function dayLabel(kind: ScheduleDay['kind']): string { return kind === 'WORK' ? '工作' : kind === 'REST' ? '休息' : '未设置' }
function findDay(date: string): ScheduleDay | undefined { return days.value.find(item => item.date === date) }
function updateDay(date: string, value: Partial<ScheduleDay>) {
  const day = findDay(date); if (day) Object.assign(day, value)
  for (const key of invalidTimes) { if (key.startsWith(`${date}|`)) invalidTimes.delete(key) }
}
function setRest(date: string) { updateDay(date, { kind: 'REST', periods: [] }); error.value = '' }
function clearDay(date: string) { updateDay(date, { kind: 'UNSET', periods: [] }); error.value = '' }
function setWork(date: string) {
  const start = toSeconds(startTime.value), end = toSeconds(endTime.value)
  if (start === null || end === null || start >= end) { error.value = '请先设置有效的上下班时间。'; return }
  updateDay(date, { kind: 'WORK', periods: [{ start_sec: start, end_sec: end }] }); error.value = ''
}
function setPeriodTime(date: string, index: number, side: 'start_sec' | 'end_sec', value: string) {
  const seconds = toSeconds(value), day = findDay(date)
  if (!day?.periods[index]) return
  const key = `${date}|${index}|${side}`
  if (seconds === null) { invalidTimes.add(key); error.value = '请补全工作日的上下班时间。'; return }
  invalidTimes.delete(key)
  day.periods[index][side] = seconds
}
async function moveDate(event: KeyboardEvent, date: string) {
  const step: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }
  if (!Object.hasOwn(step, event.key)) return
  event.preventDefault()
  const index = days.value.findIndex(day => day.date === date)
  const next = days.value[Math.max(0, Math.min(days.value.length - 1, index + step[event.key]!))]
  if (!next) return
  selectedDate.value = next.date
  await nextTick()
  ;(event.target as HTMLElement).closest('.calendar-grid')?.querySelector<HTMLButtonElement>(`[data-schedule-date="${next.date}"]`)?.focus()
}
function applyMonth() {
  const start = toSeconds(startTime.value), end = toSeconds(endTime.value)
  if (start === null || end === null || start >= end) { error.value = '下班时间必须晚于上班时间，且当前不支持跨日时段。'; return }
  if (!weekdays.value.length) { error.value = '请至少选择一个工作日。'; return }
  const selected = new Set(weekdays.value)
  days.value = monthDates(props.month).map(date => {
    const weekday = new Date(`${date}T00:00:00Z`).getUTCDay() || 7
    return selected.has(weekday) ? { date, kind: 'WORK', periods: [{ start_sec: start, end_sec: end }] } : { date, kind: 'REST', periods: [] }
  })
  importToken.value = null; error.value = ''; invalidTimes.clear()
}
async function load() {
  if (!props.modelValue || !canManage.value) return
  const current = requestNo; loading.value = true; error.value = ''
  try { const value = await getAttendanceSchedule(props.month); if (isCurrent(current)) resetDraft(value) }
  catch (cause) { if (isCurrent(current) && !accessFailure(cause)) error.value = attendanceError(cause) }
  finally { if (isCurrent(current)) loading.value = false }
}
async function readRules() {
  if (rulesLoading.value || saving.value || !props.modelValue || !canManage.value) return
  const current = requestNo
  rulesLoading.value = true; error.value = ''
  try { const result = await getAttendanceRules(props.month); if (isCurrent(current)) rules.value = result.rules }
  catch (cause) { if (isCurrent(current) && !accessFailure(cause)) error.value = attendanceError(cause) }
  finally { if (isCurrent(current)) rulesLoading.value = false }
}
function applyRule() {
  const selected = rules.value.find(rule => String(rule.id) === selectedRuleId.value)
  if (!selected) { error.value = '请选择一个可导入的企业微信当前规则。'; return }
  if (!selected.can_import) { error.value = selected.reason || '当前规则不能直接导入，请手动设置。'; return }
  days.value = clone(selected.days); importToken.value = selected.import_token; error.value = ''; invalidTimes.clear()
}
function validateDays(): string {
  if (invalidTimes.size) return '请补全工作日的上下班时间。'
  if (days.value.length !== monthDates(props.month).length) return '必须为当月每一天设置状态。'
  for (const day of days.value) {
    if (day.kind !== 'WORK' && day.periods.length) return `${day.date} 的休息或未设置日期不能填写时段。`
    const periods = [...day.periods].sort((left, right) => left.start_sec - right.start_sec)
    if (day.kind === 'WORK' && !periods.length) return `${day.date} 的工作日缺少上下班时段。`
    if (periods.some(period => period.start_sec >= period.end_sec) || periods.some((period, index) => index > 0 && periods[index - 1]!.end_sec > period.start_sec)) return `${day.date} 的时段重叠或时间无效。`
  }
  return ''
}
async function save() {
  if (saving.value || loading.value || !etag.value || saveBlocked.value || !props.modelValue || !canManage.value) return
  error.value = validateDays(); if (error.value) return
  const current = requestNo
  saving.value = true
  try {
    const submittedDays = clone(days.value).map(day => ({ ...day, periods: day.periods.sort((left, right) => left.start_sec - right.start_sec) }))
    const result = await saveAttendanceSchedule(props.month, { days: submittedDays, import_token: importToken.value }, etag.value)
    if (!isCurrent(current)) return
    resetDraft(result); emit('saved'); emit('update:modelValue', false)
  } catch (cause) {
    if (!isCurrent(current)) return
    const status = (cause as { response?: { status?: number } })?.response?.status
    if (status === 412) { saveBlocked.value = true; error.value = '安排已被其他管理员修改，请重新打开并读取最新版本后再保存。' }
    else if (!accessFailure(cause)) error.value = attendanceError(cause)
  } finally { if (isCurrent(current)) saving.value = false }
}
function close() { clearDraft(); emit('update:modelValue', false) }
watch(() => [props.modelValue, props.month, canManage.value] as const, ([open, , allowed]) => {
  clearDraft()
  if (!open) return
  if (allowed) void load()
  else { error.value = '当前账号已无权管理月度安排。'; emit('forbidden') }
}, { immediate: true })
onBeforeUnmount(clearDraft)
</script>

<template>
  <AppWindowDialog :model-value="modelValue" title="设置当月上班时间" :width="1040" height="auto" :min-width="320" destroy-on-close @update:model-value="close">
    <div class="schedule-dialog">
      <p v-if="!canManage" class="schedule-error" role="alert">当前账号已无权管理月度安排。</p>
      <template v-else>
        <div v-if="loading" class="schedule-loading" role="status">正在读取 {{ month }} 安排…</div>
        <template v-else>
          <p class="schedule-intro">设置只用于 ERP，不修改企业微信规则。可设置当月时段，再单独调整日期。</p>
          <div class="schedule-fields"><div class="field"><span>生效月份</span><strong>{{ month }}</strong></div><div class="field"><span>适用范围</span><strong>{{ month }} · 全员统一</strong></div><div class="field"><span>判断口径</span><strong>沿用企微判断，不重算迟到、早退</strong></div></div>
          <p v-if="schedule?.source" class="schedule-source">已保存来源：{{ schedule.source.rule_name }}</p>
          <section class="rule-import" aria-label="导入企业微信当前规则">
            <div><strong>导入企业微信当前规则</strong><p>只读取当前规则，不能证明历史月份；请选择后应用到草稿，保存才会写入本月。</p></div>
            <div class="rule-actions"><ElButton data-testid="read-rules" :loading="rulesLoading" @click="readRules">读取当前规则</ElButton><select v-model="selectedRuleId" aria-label="企业微信当前规则"><option value="">请选择规则</option><option v-for="rule in rules" :key="rule.id" :value="String(rule.id)" :disabled="!rule.can_import">{{ rule.name }}{{ rule.can_import ? '' : `（${rule.reason}）` }}</option></select><ElButton data-testid="apply-rule" :disabled="!selectedRuleId" @click="applyRule">应用到草稿</ElButton></div>
            <ul v-if="rules.find(rule => String(rule.id) === selectedRuleId)?.warnings.length" class="schedule-warnings"><li v-for="warning in rules.find(rule => String(rule.id) === selectedRuleId)?.warnings" :key="warning">{{ warning }}</li></ul>
          </section>
          <section class="global-editor"><div><strong>按星期生成整月草稿</strong><p>未勾选日期会设为休息；可在下方逐日调整。</p></div><div class="weekday-list"><label v-for="weekday in [{ value: 1, label: '周一' }, { value: 2, label: '周二' }, { value: 3, label: '周三' }, { value: 4, label: '周四' }, { value: 5, label: '周五' }, { value: 6, label: '周六' }, { value: 7, label: '周日' }]" :key="weekday.value"><input v-model="weekdays" type="checkbox" :value="weekday.value" :aria-label="`${weekday.label}工作`">{{ weekday.label }}</label></div><div class="time-fields"><label>统一上班时间<input v-model="startTime" type="time" aria-label="统一上班时间"></label><label>统一下班时间<input v-model="endTime" type="time" aria-label="统一下班时间"></label><ElButton data-testid="apply-month" @click="applyMonth">应用整月草稿</ElButton></div></section>
          <p v-if="error" class="schedule-error" role="alert">{{ error }}</p>
          <div class="schedule-grid-layout">
            <section class="month-calendar">
              <div class="calendar-caption"><strong>{{ monthLabel(month) }}</strong><span>选中日期后调整安排</span></div>
              <div class="weekdays" aria-hidden="true"><span v-for="weekday in ['一', '二', '三', '四', '五', '六', '日']" :key="weekday">{{ weekday }}</span></div>
              <div class="calendar-grid" aria-label="月度安排日期">
                <template v-for="(day, index) in calendarDays" :key="day?.date ?? `blank-${index}`">
                  <button v-if="day" type="button" :data-schedule-date="day.date" class="calendar-day schedule-day" :aria-pressed="selectedDate === day.date" :tabindex="selectedDate === day.date ? 0 : -1" :aria-label="`${day.date} ${dayLabel(day.kind)}`" @click="selectedDate = day.date" @keydown="moveDate($event, day.date)"><span class="day-number">{{ Number(day.date.slice(-2)) }}</span><span class="day-dots" aria-hidden="true"><i v-if="day.kind !== 'UNSET'" class="status-dot" :class="day.kind.toLowerCase()" /></span><span class="day-label">{{ dayLabel(day.kind) }}</span></button>
                  <span v-else aria-hidden="true" />
                </template>
              </div>
              <p class="calendar-footnote">调整休息安排不会覆盖或删除企微返回的迟到、早退等异常。</p>
            </section>
            <aside v-if="selectedDay" class="day-adjustment" data-testid="day-adjustment" aria-live="polite">
              <h3>{{ selectedDay.date }} · 当日安排</h3>
              <p class="adjustment-description">仅修改选中日期，其余日期不变。工作按钮使用上方统一时间。</p>
              <div class="day-modes" aria-label="指定日期安排"><button type="button" data-testid="day-work" :aria-pressed="selectedDay.kind === 'WORK'" @click="setWork(selectedDay.date)">工作</button><button type="button" data-testid="day-rest" :aria-pressed="selectedDay.kind === 'REST'" @click="setRest(selectedDay.date)">休息</button></div>
              <div class="specific-periods"><div v-for="(period, index) in selectedDay.periods" :key="`${selectedDay.date}-${index}`" class="specific-times" data-testid="period-row"><label class="field"><span>第 {{ index + 1 }} 段上班</span><input :aria-label="`第${index + 1}段上班时间`" type="time" :value="timeText(period.start_sec)" @change="setPeriodTime(selectedDay.date, index, 'start_sec', ($event.target as HTMLInputElement).value)"></label><label class="field"><span>第 {{ index + 1 }} 段下班</span><input :aria-label="`第${index + 1}段下班时间`" type="time" :value="timeText(period.end_sec)" @change="setPeriodTime(selectedDay.date, index, 'end_sec', ($event.target as HTMLInputElement).value)"></label></div></div>
              <p class="schedule-feedback">{{ selectedDay.kind === 'UNSET' ? '该日未设置，不默认认定工作或休息。' : `已加入草稿：${dayLabel(selectedDay.kind)}日，保存后才生效。` }}</p>
              <button type="button" class="text-button" data-testid="day-clear" @click="clearDay(selectedDay.date)">清除当日调整</button>
              <p class="local-note">适用于全员；时间仅作安排，不重算企微异常，也不回写企业微信。</p>
            </aside>
          </div>
        </template>
      </template>
    </div>
    <template #footer><ElButton data-testid="cancel-schedule" @click="close">取消</ElButton><ElButton type="primary" data-testid="save-schedule" :loading="saving" :disabled="saveBlocked || !canManage || loading || !etag" @click="save">保存当月安排</ElButton></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.schedule-dialog { color: var(--erp-color-text-primary); font-size: 12px; min-width: 0; }
.schedule-intro { margin: 0 0 15px; color: var(--erp-color-text-secondary); line-height: 1.8; }
.schedule-fields { display: grid; grid-template-columns: 150px 1fr 1fr; gap: 12px; padding-bottom: 16px; margin-bottom: 16px; border-bottom: 1px solid var(--erp-color-border); }
.field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.field > span { color: var(--erp-color-text-secondary); }
.field strong { font-size: 12px; font-weight: 500; }
.schedule-source { color: var(--erp-color-text-secondary); margin: 0 0 12px; }
.rule-import, .global-editor { padding-bottom: 16px; margin-bottom: 16px; border-bottom: 1px solid var(--erp-color-border); }
.rule-import p, .global-editor p { color: var(--erp-color-text-secondary); margin: 4px 0 0; line-height: 1.7; }
.rule-import > div:first-child, .global-editor > div:first-child { margin-bottom: 10px; }
.rule-actions, .time-fields, .weekday-list { display: flex; align-items: end; flex-wrap: wrap; gap: 8px; }
.rule-actions select, .time-fields input, .specific-times input { height: 32px; min-width: 0; border: 1px solid var(--erp-control-border); border-radius: 6px; padding: 0 8px; background: var(--erp-input-surface); color: inherit; font: inherit; }
.rule-actions select { min-width: 220px; }
.weekday-list { align-items: center; gap: 8px 14px; margin-bottom: 10px; }
.weekday-list label { display: inline-flex; align-items: center; gap: 4px; }
.time-fields label { display: flex; flex-direction: column; gap: 4px; }
.schedule-warnings { margin: 10px 0 0; padding-left: 18px; color: var(--erp-color-warning); line-height: 1.8; }
.schedule-error { margin: 8px 0; color: var(--erp-color-danger); line-height: 1.7; }
.schedule-loading { padding: 24px 0; color: var(--erp-color-text-secondary); }
.schedule-grid-layout { display: grid; grid-template-columns: minmax(0, 1fr) 260px; gap: 20px; }
.month-calendar { min-width: 0; }
.calendar-caption { display: flex; align-items: center; justify-content: space-between; margin: 2px 0 12px; gap: 8px; }
.calendar-caption strong { font-size: 15px; font-weight: 600; }
.calendar-caption span { font-size: 11px; color: var(--erp-color-text-secondary); }
.weekdays, .calendar-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 5px; }
.weekdays { margin-bottom: 6px; }
.weekdays span { height: 24px; line-height: 24px; text-align: center; font-size: 11px; color: var(--erp-color-text-secondary); }
.calendar-day { min-width: 0; height: 64px; padding: 6px 2px; display: flex; flex-direction: column; align-items: center; justify-content: flex-start; gap: 3px; border: 1px solid transparent; border-radius: 8px; background: transparent; box-shadow: none; color: inherit; cursor: pointer; font: inherit; }
.calendar-day:hover { background: var(--erp-color-hover); }
.calendar-day[aria-pressed='true'] { border-color: var(--erp-color-brand); background: var(--erp-color-selected); }
.calendar-day:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 1px; }
.day-number { height: 25px; width: 25px; line-height: 25px; border-radius: 50%; text-align: center; font-size: 13px; font-weight: 500; }
.calendar-day[aria-pressed='true'] .day-number { color: var(--erp-color-text-inverse); background: var(--erp-color-brand); }
.day-dots { display: flex; align-items: center; justify-content: center; height: 5px; }
.status-dot { height: 5px; width: 5px; border-radius: 50%; background: var(--erp-color-success); }
.status-dot.rest { background: var(--erp-color-text-muted); }
.day-label { font-size: 10px; line-height: 12px; color: var(--erp-color-text-secondary); }
.calendar-footnote { margin: 10px 0 0; font-size: 11px; line-height: 1.8; color: var(--erp-color-text-secondary); }
.day-adjustment { min-width: 0; padding-left: 20px; border-left: 1px solid var(--erp-color-border); }
.day-adjustment h3 { margin: 2px 0 12px; font-size: 14px; font-weight: 600; }
.adjustment-description { font-size: 11px; line-height: 1.8; color: var(--erp-color-text-secondary); }
.day-modes { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 14px; }
.day-modes button { height: 30px; padding: 0 10px; border: 1px solid var(--erp-control-border); border-radius: 5px; box-shadow: none; color: inherit; background: var(--erp-input-surface); font: inherit; cursor: pointer; }
.day-modes button[aria-pressed='true'] { background: var(--erp-color-selected); border-color: var(--erp-color-brand); color: var(--erp-color-brand); }
.specific-periods { display: flex; flex-direction: column; gap: 10px; }
.specific-times { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px; }
.specific-times input { width: 100%; }
.schedule-feedback { margin-top: 10px; color: var(--erp-color-brand); font-size: 11px; line-height: 1.8; overflow-wrap: anywhere; }
.text-button { padding: 0; border: 0; background: transparent; color: var(--erp-color-brand); cursor: pointer; font: inherit; }
.text-button:hover { text-decoration: underline; }
.local-note { padding: 10px 12px; margin-top: 16px; font-size: 11px; line-height: 1.8; color: var(--erp-color-text-secondary); background: var(--erp-color-info-soft); border-radius: 6px; }
@media (max-width: 760px) {
  .schedule-fields { grid-template-columns: 1fr 1fr; }
  .schedule-fields > .field:last-child { grid-column: 1 / -1; }
  .schedule-grid-layout { grid-template-columns: minmax(0, 1fr); gap: 16px; }
  .day-adjustment { padding-left: 0; padding-top: 15px; border-left: 0; border-top: 1px solid var(--erp-color-border); }
  .weekdays, .calendar-grid { gap: 2px; }
  .calendar-day { height: 60px; padding: 5px 0; }
  .rule-actions select { min-width: 180px; }
  .calendar-caption { flex-wrap: wrap; }
  .calendar-caption strong { font-size: 14px; }
}
</style>
