<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'
import { ElButton } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { attendanceError, getAttendanceCalendar, getAttendanceVacation } from '@/api/attendance'
import { useAuthStore } from '@/stores/auth'
import type { AttendanceCalendar, AttendanceVacation, CalendarDay, MonthlyRow } from '@/types/attendance'
import { attendanceStates, calendarCells, exceptionText, monthLabel, shanghaiDateTime, shanghaiTime, sourceNumber, stateLabels, validMonth } from './attendancePresentation'
import { absenceItemLabel, absenceTypeLabel, dailyOvertimeDetails, formatAbsenceDuration, formatOvertimeOriginal, formatVacationBalance, hasAbsenceActivity, hasDailyOvertimeActivity, overtimeStatusLabel } from './attendanceAbsencePresentation'

const props = defineProps<{ modelValue: boolean; month: string; userId: string; name: string; people: MonthlyRow[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; forbidden: [] }>()
const auth = useAuthStore()
const permitted = computed(() => auth.hasPermission('attendance.view_attendance'))
const selectedMonth = ref(props.month), selectedUser = ref(props.userId), selectedDate = ref('')
const calendar = ref<AttendanceCalendar | null>(null), loading = ref(false), error = ref('')
const detailTab = ref<'absence' | 'punches'>('absence')
const vacation = ref<AttendanceVacation | null>(null), vacationOpen = ref(false), vacationLoading = ref(false), vacationError = ref('')
const cells = computed(() => calendarCells(selectedMonth.value, calendar.value?.days ?? []))
const selected = computed(() => cells.value.find(day => day?.date === selectedDate.value) ?? null)
const sourceGroups = computed(() => selected.value?.source_summaries?.map((source, sourceIndex) => ({
  ...source,
  key: `${source.record_id ?? 'source'}-${sourceIndex}`,
  items: source.sp_items?.map((item, itemIndex) => ({ item, key: `${item.type}-${itemIndex}`, duplicate: source.sp_items!.filter(other => other.type === item.type && other.vacation_id === item.vacation_id && other.time_type === item.time_type).length > 1 })),
  overtime: dailyOvertimeDetails(source.ot_info)?.filter(row => source.ot_info?.[row.key] != null),
})) ?? null)
const people = computed(() => props.people.some(person => person.user_id === props.userId) ? props.people : [{ user_id: props.userId, name: props.name }, ...props.people])
const legend = ['normal', 'zero', 'late', 'early', 'missing', 'absent', 'location', 'device', 'recorded', 'unknown', 'future', 'rest']
let sequence = 0, controller: AbortController | undefined, disposed = false
let vacationSequence = 0, vacationController: AbortController | undefined

function live() { return !disposed && props.modelValue && permitted.value }
function clearVacation() {
  vacationSequence++; vacationController?.abort(); vacation.value = null; vacationOpen.value = false; vacationLoading.value = false; vacationError.value = ''
}

function clear() {
  sequence++; controller?.abort(); calendar.value = null; error.value = ''; loading.value = false
  clearVacation()
}
async function load(clearExisting = false) {
  if (!live() || !selectedUser.value || !validMonth(selectedMonth.value)) return
  controller?.abort(); controller = new AbortController()
  const current = ++sequence, signal = controller.signal
  if (clearExisting) calendar.value = null
  loading.value = true; error.value = ''
  try {
    const result = await getAttendanceCalendar(selectedMonth.value, selectedUser.value, signal)
    if (!live() || current !== sequence || signal.aborted) return
    calendar.value = result
    if (!selectedDate.value.startsWith(selectedMonth.value) || !cells.value.some(day => day?.date === selectedDate.value)) selectedDate.value = `${selectedMonth.value}-01`
  } catch (cause) {
    if (!live() || current !== sequence || signal.aborted) return
    const status = (cause as { response?: { status?: number } })?.response?.status
    if (status === 401 || status === 403) { clear(); emit('forbidden'); return }
    error.value = attendanceError(cause)
  } finally { if (current === sequence) loading.value = false }
}
function changeSelection() {
  clear(); selectedDate.value = `${selectedMonth.value}-01`; detailTab.value = 'absence'
  if (!validMonth(selectedMonth.value)) { error.value = '请选择有效的考勤月份。'; return }
  void load()
}
async function loadVacation() {
  if (!live() || !calendar.value || vacationLoading.value || !validMonth(selectedMonth.value)) return
  vacationController?.abort(); vacationController = new AbortController()
  const current = ++vacationSequence, signal = vacationController.signal, user = selectedUser.value, month = selectedMonth.value
  vacationLoading.value = true; vacationError.value = ''
  try {
    const result = await getAttendanceVacation(month, user, signal)
    if (!live() || signal.aborted || current !== vacationSequence || user !== selectedUser.value || month !== selectedMonth.value) return
    vacation.value = result
  } catch (cause) {
    if (!live() || signal.aborted || current !== vacationSequence) return
    const status = (cause as { response?: { status?: number } })?.response?.status
    if (status === 401 || status === 403) { clear(); emit('forbidden'); return }
    if (status === 409) {
      const message = (cause as { response?: { data?: { error?: { message?: unknown } } } })?.response?.data?.error?.message
      const knownMessages = ['企业微信应用未启用或配置不完整，请联系管理员。', '读取期间企业微信配置已变化，请重新查询。', '读取期间考勤快照已更新，请重新查询。']
      vacationError.value = knownMessages.find(value => value === message) || '当前假期余额暂无法读取，请重新查询；若持续失败，请联系管理员核对配置。'
      return
    }
    vacationError.value = status === 502 ? '当前假期余额读取失败，请核对企业微信审批接口授权或稍后重试。'
      : status === 404 ? '当前月份的成功快照未包含该成员，暂无法读取当前余额。' : attendanceError(cause)
  } finally { if (current === vacationSequence) vacationLoading.value = false }
}
function toggleVacation() {
  vacationOpen.value = !vacationOpen.value
  if (vacationOpen.value && !vacation.value && !vacationLoading.value) void loadVacation()
}
function changeOpen(open: boolean) { if (!open) clear(); emit('update:modelValue', open) }
function dayMarkers(day: CalendarDay) {
  const markers = new Map<string, { label: string; kind: string }>()
  for (const source of day.source_summaries ?? []) {
    for (const item of source.sp_items ?? []) {
      if (!hasAbsenceActivity(item)) continue
      const label = absenceTypeLabel(item), kind = ({ 1: 'leave', 2: 'correction', 3: 'trip' } as Record<number, string>)[item.type] ?? 'other'
      // 月格只去除重复类型标识，右侧原始日报和每条统计项仍逐条保留。
      markers.set(`${item.type}-${label}`, { label, kind })
    }
    if (hasDailyOvertimeActivity(source.ot_info)) markers.set('overtime', { label: '加班', kind: 'overtime' })
  }
  return [...markers.values()]
}
function scheduleTime(seconds: number) { return `${String(Math.floor(seconds / 3600)).padStart(2, '0')}:${String(Math.floor(seconds % 3600 / 60)).padStart(2, '0')}` }
async function moveDate(event: KeyboardEvent, date: string) {
  const movements: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }
  if (!Object.hasOwn(movements, event.key)) return
  event.preventDefault()
  const dates = cells.value.filter(day => day !== null)
  const index = dates.findIndex(day => day.date === date)
  const target = dates[Math.max(0, Math.min(dates.length - 1, index + movements[event.key]!))]
  if (!target) return
  selectedDate.value = target.date
  await nextTick()
  const grid = (event.target as HTMLElement).closest('.calendar-grid')
  grid?.querySelector<HTMLButtonElement>(`[data-date="${target.date}"]`)?.focus()
}
watch(() => [props.modelValue, props.month, props.userId, permitted.value] as const, ([open, month, user, allowed]) => {
  clear()
  if (open && allowed) { selectedMonth.value = month; selectedUser.value = user; selectedDate.value = `${month}-01`; detailTab.value = 'absence'; void load() }
}, { immediate: true, flush: 'sync' })
onDeactivated(clear)
onBeforeUnmount(() => { disposed = true; clear() })
</script>

<template>
  <AppWindowDialog :model-value="modelValue" title="个人考勤月历" :width="1000" height="auto" :min-width="300" destroy-on-close @update:model-value="changeOpen">
    <div v-if="permitted" class="attendance-calendar">
      <div class="calendar-controls">
        <label class="field"><select v-model="selectedUser" aria-label="月历人员" @change="changeSelection"><option v-for="person in people" :key="person.user_id" :value="person.user_id">{{ person.name }} · {{ person.user_id }}</option></select></label>
        <label class="field"><input v-model="selectedMonth" type="month" aria-label="月历月份" @change="changeSelection"></label>
        <span class="source-caption">北京时间 · 企业微信来源</span>
      </div>
      <p v-if="loading" role="status" class="calendar-feedback">正在读取个人月历…</p>
      <div v-if="error" role="alert" class="calendar-feedback error">{{ error }} {{ calendar ? '保留上次成功读取的月历。' : '' }}<ElButton size="small" @click="load()">重试月历</ElButton></div>
      <section class="vacation-section">
        <div class="vacation-summary" data-testid="vacation-summary">
          <strong>当前假期余额</strong>
          <span v-if="vacation" class="vacation-preview"><span v-for="item in vacation.items.slice(0, 2)" :key="item.id">{{ item.name || `假期 ${item.id}` }} <b>{{ formatVacationBalance(item) }}</b></span><span v-if="!vacation.items.length">来源返回空列表</span></span>
          <span v-else class="muted">{{ vacationLoading ? '正在读取…' : '尚未读取' }}</span>
          <ElButton size="small" data-testid="toggle-vacation" :disabled="!calendar" :aria-expanded="vacationOpen" aria-controls="attendance-vacation-detail" @click="toggleVacation">{{ vacationOpen ? '收起余额' : '查看余额' }}</ElButton>
        </div>
        <div v-if="vacationOpen" id="attendance-vacation-detail" class="vacation-detail" data-testid="vacation-detail">
          <div class="vacation-heading"><span>{{ vacation ? `当前余额 · 读取于 ${shanghaiDateTime(vacation.fetched_at)}` : '读取企业微信当前假期余额' }}</span><ElButton size="small" data-testid="refresh-vacation" :loading="vacationLoading" @click="loadVacation">{{ vacation ? '刷新余额' : '重新读取' }}</ElButton></div>
          <p v-if="vacationLoading" role="status" class="detail-empty">正在读取当前余额…</p>
          <p v-if="vacationError" role="alert" class="error" data-testid="vacation-error">{{ vacationError }} {{ vacation ? '保留上次读取的当前余额。' : '' }}</p>
          <table v-if="vacation?.items.length" class="vacation-table"><thead><tr><th>假期</th><th>当前可用余额</th><th>来源</th></tr></thead><tbody><tr v-for="item in vacation.items" :key="item.id"><td>{{ item.name || `假期 ${item.id}` }}</td><td>{{ formatVacationBalance(item) }}</td><td>企业微信当前值</td></tr></tbody></table>
          <p v-else-if="vacation" class="detail-empty">来源返回空列表，未返回假期余额项。</p>
          <p class="balance-note">余额是读取时的当前值，不是所选历史月份的月末余额。</p>
        </div>
      </section>
      <div v-if="calendar" class="calendar-layout">
        <section class="month-calendar">
          <div class="calendar-caption"><strong>{{ monthLabel(selectedMonth) }}</strong><span>点选日期，查看当天详情</span></div>
          <div class="weekdays" aria-hidden="true"><span v-for="weekday in ['一', '二', '三', '四', '五', '六', '日']" :key="weekday">{{ weekday }}</span></div>
          <div class="calendar-grid" aria-label="个人考勤日期">
            <template v-for="(day, index) in cells" :key="day?.date ?? `blank-${index}`">
              <button v-if="day" type="button" class="calendar-day" :data-date="day.date" :aria-pressed="selectedDate === day.date" :tabindex="selectedDate === day.date ? 0 : -1" :aria-label="`${day.date} ${attendanceStates(day).map(state => stateLabels[state]).join('、')} ${dayMarkers(day).map(marker => marker.label).join('、')}`" @click="selectedDate = day.date" @keydown="moveDate($event, day.date)">
                <span class="day-number">{{ Number(day.date.slice(-2)) }}</span>
                <span class="day-dots" aria-hidden="true"><i v-for="state in attendanceStates(day)" :key="state" class="status-dot" :class="state" /></span>
                <span class="day-label"><span v-for="state in attendanceStates(day)" :key="state">{{ stateLabels[state] }}</span></span>
                <span class="day-events"><span v-for="marker in dayMarkers(day)" :key="`${marker.kind}-${marker.label}`" class="event-badge" :class="marker.kind">{{ marker.label }}</span></span>
              </button>
              <span v-else aria-hidden="true" />
            </template>
          </div>
          <div class="calendar-legend" aria-label="考勤状态图例"><span v-for="state in legend" :key="state"><i class="status-dot" :class="state" aria-hidden="true" />{{ stateLabels[state] }}</span></div>
        </section>
        <aside v-if="selected" class="day-detail" data-testid="day-detail" aria-live="polite">
          <h3>{{ selected.date }}</h3><p class="detail-subtitle">{{ calendar.name }} · {{ calendar.user_id }}</p>
          <p class="source-title">企业微信返回结果</p>
          <div class="detail-tags"><span v-for="state in attendanceStates(selected).filter(state => state !== 'rest')" :key="state" class="detail-status" :class="state">{{ stateLabels[state] }}</span></div>
          <div class="detail-tabs" role="tablist" aria-label="当天来源明细"><button type="button" role="tab" :aria-selected="detailTab === 'absence'" data-testid="calendar-tab-absence" @click="detailTab = 'absence'">假勤明细</button><button type="button" role="tab" :aria-selected="detailTab === 'punches'" data-testid="calendar-tab-punches" @click="detailTab = 'punches'">打卡明细</button></div>
          <section v-if="detailTab === 'absence'" data-testid="absence-detail" role="tabpanel" aria-label="假勤明细">
            <p v-if="sourceGroups === null" class="detail-empty">该快照未采集或未返回假勤来源。</p>
            <p v-else-if="!sourceGroups.length" class="detail-empty">该日期未返回日报假勤来源，不折算为 0。</p>
            <article v-for="(source, index) in sourceGroups" :key="source.key" class="absence-source" data-testid="absence-source">
              <h4 :title="source.record_id || '来源记录编号未返回'">来源日报 {{ index + 1 }}</h4>
              <p v-if="source.items == null" class="detail-empty">该来源未采集或未返回假勤统计。</p>
              <p v-else-if="!source.items.length" class="detail-empty">来源返回空统计项。</p>
              <div v-for="row in source.items" :key="row.key" class="absence-item" data-testid="absence-item">
                <strong>{{ absenceItemLabel(row.item) }}</strong><div class="absence-values"><span>次数 <b>{{ sourceNumber(row.item.count, ' 次') }}</b></span><span>时长 <b>{{ formatAbsenceDuration(row.item.duration, row.item.time_type) }}</b></span></div>
                <p v-if="row.duplicate" class="source-warning">重复统计项，待核对；各项分别保留。</p>
              </div>
              <p class="source-title">加班来源</p>
              <p v-if="source.ot_info == null" class="detail-empty">未返回加班来源。</p>
              <template v-else>
                <div class="detail-pair"><span>来源状态</span><strong>{{ overtimeStatusLabel(source.ot_info.ot_status) }}</strong></div>
                <div v-for="row in source.overtime" :key="row.key" class="detail-pair"><span>{{ row.label }}</span><strong>{{ row.value }}</strong></div>
                <p v-if="!source.overtime?.length" class="detail-empty">未返回分项时长。</p>
                <details class="raw-overtime"><summary>查看来源原值</summary><p>加班时长：{{ formatOvertimeOriginal(source.ot_info.ot_duration) }}</p><p>异常时长：{{ formatOvertimeOriginal(source.ot_info.exception_duration) }}</p></details>
              </template>
            </article>
          </section>
          <section v-else data-testid="punch-detail" role="tabpanel" aria-label="打卡明细">
          <div class="detail-pair"><span>日报打卡次数</span><strong>{{ sourceNumber(selected.checkin_count, ' 次') }}</strong></div>
          <p class="source-title">来源异常统计</p><p class="detail-empty">{{ exceptionText(selected.exceptions) }}</p>
          <p class="source-title">原始打卡明细 · {{ selected.raw.length }} 条</p>
          <ul v-if="selected.raw.length" class="punch-list"><li v-for="(record, index) in selected.raw" :key="`${record.id}-${index}`"><div><strong>{{ shanghaiTime(record.checkin_time) }}</strong><span>{{ record.checkin_type || '类型未返回' }}</span></div><small>{{ record.group_name || '规则未返回' }}</small><small v-if="record.exceptions.length" class="source-exception">{{ record.exceptions.join('、') }}</small></li></ul>
          <p v-else class="detail-empty">{{ selected.checkin_count === 0 ? '日报明确返回 0 次，不据此认定旷工。' : '该日期未返回原始打卡明细，不折算为 0 次。' }}</p>
          <p class="source-title">ERP 全员月度安排</p>
          <p v-if="selected.schedule?.kind === 'REST'" class="detail-empty">休息安排（不改变上方企微结果）</p>
          <p v-else-if="selected.schedule?.kind === 'WORK'" class="detail-empty">工作日 · {{ selected.schedule.periods.map(period => `${scheduleTime(period.start_sec)}—${scheduleTime(period.end_sec)}`).join('、') }}</p>
          <p v-else class="detail-empty">尚未设置</p>
          </section>
        </aside>
      </div>
      <details v-if="calendar" class="operation-note"><summary>来源与显示说明</summary><p>迟到、早退沿用企微结果；假勤标识不覆盖异常。每条来源日报分别展示，同类项不合计。明确 0 与未返回分开显示，不据此推算旷工。</p><p>原始流水条数与日报打卡次数分别展示，二者不要求相等。加班原值单位未明确时不换算小时，余额按来源单位显示。</p></details>
    </div>
    <template #footer><ElButton @click="changeOpen(false)">关闭</ElButton></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.attendance-calendar { color: var(--erp-color-text-primary); font-size: 12px; min-width: 0; container-type: inline-size; container-name: attendance-calendar; }
.calendar-controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.field { display: flex; width: 154px; min-width: 0; }
.field:first-child { width: 260px; }
.field input, .field select { width: 100%; min-width: 0; height: 32px; font: inherit; }
.source-caption { margin-left: auto; color: var(--erp-color-text-secondary); font-size: 11px; }
.calendar-feedback { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 10px 0; }
.error { color: var(--erp-color-danger); }
.calendar-layout { display: grid; grid-template-columns: minmax(0, 1fr) 310px; gap: 20px; }
.muted, .balance-note { color: var(--erp-color-text-secondary); }
.vacation-section { margin-bottom: 14px; }
.vacation-summary { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 14px; padding: 8px 0; border-block: 1px solid var(--erp-color-border); }
.vacation-summary > strong { font-weight: 600; }
.vacation-summary > .el-button { margin-left: auto; }
.vacation-preview { display: flex; gap: 8px 16px; flex-wrap: wrap; color: var(--erp-color-text-secondary); }
.vacation-preview b { color: var(--erp-color-text-primary); font-weight: 500; font-variant-numeric: tabular-nums; }
.vacation-detail { padding-top: 8px; }
.vacation-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 11px; color: var(--erp-color-text-secondary); margin-bottom: 6px; }
.vacation-table { width: 100%; table-layout: fixed; border-collapse: collapse; }
.vacation-table th, .vacation-table td { padding: 5px 8px; height: 34px; text-align: left; border-bottom: 1px solid var(--erp-color-border); overflow-wrap: anywhere; }
.vacation-table th { height: 32px; font-weight: 500; background: var(--erp-color-info-soft); }
.vacation-table th:nth-child(2), .vacation-table td:nth-child(2) { text-align: right; font-variant-numeric: tabular-nums; }
.balance-note { margin: 6px 0 0; font-size: 11px; line-height: 1.8; }
.month-calendar { min-width: 0; }
.calendar-caption { display: flex; justify-content: space-between; align-items: center; margin: 2px 0 12px; gap: 8px; }
.calendar-caption strong { font-size: 15px; font-weight: 600; }
.calendar-caption span { font-size: 11px; color: var(--erp-color-text-secondary); }
.weekdays, .calendar-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 5px; }
.weekdays { margin-bottom: 6px; }
.weekdays span { height: 24px; line-height: 24px; text-align: center; font-size: 11px; color: var(--erp-color-text-secondary); }
.calendar-day { min-width: 0; min-height: 82px; height: auto; padding: 5px 2px; display: flex; flex-direction: column; align-items: center; justify-content: flex-start; gap: 4px; border: 1px solid transparent; border-radius: 8px; background: transparent; box-shadow: none; color: inherit; cursor: pointer; font: inherit; }
.calendar-day:hover { background: var(--erp-color-hover); }
.calendar-day[aria-pressed='true'] { border-color: var(--erp-color-brand); background: var(--erp-color-selected); }
.calendar-day:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 1px; }
.day-number { display: block; width: 25px; height: 25px; line-height: 25px; text-align: center; border-radius: 50%; font-size: 13px; font-weight: 500; }
.calendar-day[aria-pressed='true'] .day-number { background: var(--erp-color-brand); color: var(--erp-color-text-inverse); }
.day-dots { display: flex; justify-content: center; gap: 4px; min-height: 5px; flex-wrap: wrap; }
.status-dot { width: 5px; height: 5px; display: inline-block; flex: none; border-radius: 50%; background: var(--erp-color-success); }
.status-dot.late, .status-dot.location { background: var(--erp-color-warning); }
.status-dot.early, .status-dot.absent, .status-dot.device { background: var(--erp-color-danger); }
.status-dot.zero, .status-dot.missing { background: var(--erp-color-info); }
.status-dot.unknown { background: transparent; border: 1px solid var(--erp-color-text-muted); }
.status-dot.future { background: transparent; border: 1px dashed var(--erp-color-brand); }
.status-dot.recorded { background: var(--erp-color-brand); }
.status-dot.rest { background: var(--erp-color-text-muted); }
.day-label { display: flex; flex-wrap: wrap; justify-content: center; gap: 0 3px; font-size: 10px; line-height: 12px; color: var(--erp-color-text-secondary); max-width: 100%; }
.calendar-legend { display: flex; flex-wrap: wrap; gap: 7px 14px; padding-top: 14px; margin-top: 10px; border-top: 1px solid var(--erp-color-border); }
.calendar-legend > span { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--erp-color-text-secondary); }
.day-events { display: flex; justify-content: center; align-items: center; flex-wrap: wrap; gap: 3px; max-width: 100%; }
.event-badge { max-width: 100%; padding: 0 3px; border: 1px solid color-mix(in srgb, currentColor 30%, transparent); border-radius: 3px; background: color-mix(in srgb, currentColor 7%, var(--erp-color-surface)); color: var(--erp-color-brand); font-size: 10px; line-height: 15px; overflow-wrap: anywhere; }
.event-badge.leave { color: var(--erp-color-info); }
.event-badge.overtime { color: var(--erp-color-success); }
.detail-tabs { display: flex; gap: 19px; margin: 12px 0; border-bottom: 1px solid var(--erp-color-border); }
.detail-tabs button { position: relative; height: 34px; padding: 0 0 7px; border: 0; border-radius: 0; background: transparent; color: var(--erp-color-text-secondary); font: inherit; cursor: pointer; }
.detail-tabs button[aria-selected='true'] { color: var(--erp-color-brand); font-weight: 600; }
.detail-tabs button[aria-selected='true']::after { content: ''; position: absolute; left: 0; right: 0; bottom: -1px; height: 2px; background: var(--erp-color-brand); }
.detail-tabs button:focus-visible, summary:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
.absence-source + .absence-source { margin-top: 16px; padding-top: 12px; border-top: 1px solid var(--erp-color-border); }
.absence-source h4 { font-size: 11px; font-weight: 400; color: var(--erp-color-text-secondary); margin: 0 0 8px; }
.absence-item { padding: 8px 0; }
.absence-item + .absence-item { border-top: 1px solid var(--erp-color-border); }
.absence-item > strong { font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
.absence-values { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.absence-values > span { display: flex; justify-content: space-between; gap: 12px; color: var(--erp-color-text-secondary); }
.absence-values b { font-weight: 400; color: var(--erp-color-text-primary); text-align: right; font-variant-numeric: tabular-nums; }
.source-warning { color: var(--erp-color-warning); font-size: 11px; line-height: 1.7; }
.raw-overtime, .operation-note { color: var(--erp-color-text-secondary); font-size: 11px; line-height: 1.8; overflow-wrap: anywhere; }
.raw-overtime summary, .operation-note summary { cursor: pointer; line-height: 26px; }
.raw-overtime p, .operation-note p { margin: 6px 0 0; }
.operation-note { margin-top: 12px; }
.day-detail { min-width: 0; border-left: 1px solid var(--erp-color-border); padding-left: 20px; }
.day-detail h3 { margin: 0 0 4px; font-size: 16px; line-height: 24px; font-weight: 600; }
.detail-subtitle { margin: 0 0 15px; font-size: 11px; color: var(--erp-color-text-secondary); overflow-wrap: anywhere; }
.source-title { margin: 16px 0 7px; font-size: 11px; color: var(--erp-color-text-secondary); }
.detail-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.detail-status { padding: 1px 8px; border: 1px solid currentColor; border-radius: 999px; font-size: 11px; line-height: 20px; color: var(--erp-color-success); background: color-mix(in srgb, currentColor 9%, var(--erp-color-surface)); }
.detail-status.late, .detail-status.location { color: var(--erp-color-warning); }
.detail-status.early, .detail-status.absent, .detail-status.device { color: var(--erp-color-danger); }
.detail-status.zero, .detail-status.missing, .detail-status.unknown { color: var(--erp-color-info); }
.detail-status.recorded, .detail-status.future { color: var(--erp-color-brand); }
.detail-pair { display: flex; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--erp-color-border); }
.detail-pair span { color: var(--erp-color-text-secondary); }
.detail-pair strong { font-weight: 500; text-align: right; }
.punch-list { padding: 0; margin: 0; list-style: none; }
.punch-list li { padding: 7px 0; border-bottom: 1px solid var(--erp-color-border); }
.punch-list li > div { display: flex; justify-content: space-between; gap: 8px; }
.punch-list small { display: block; font-size: 11px; color: var(--erp-color-text-secondary); overflow-wrap: anywhere; }
.punch-list .source-exception { color: var(--erp-color-warning); }
.detail-empty { font-size: 12px; line-height: 1.8; color: var(--erp-color-text-secondary); }
@container attendance-calendar (max-width: 700px) {
  .calendar-layout { grid-template-columns: minmax(0, 1fr); gap: 16px; }
  .calendar-controls { gap: 10px; }
  .field { width: 152px; }
  .field:first-child { width: 100%; }
  .source-caption { margin-left: auto; }
  .vacation-summary { gap: 6px 10px; }
  .vacation-summary > strong { width: 100%; }
  .vacation-preview { font-size: 11px; gap: 6px 12px; }
  .vacation-heading { flex-wrap: wrap; }
  .calendar-day { min-height: 78px; padding: 4px 0; gap: 3px; }
  .weekdays, .calendar-grid { gap: 2px; }
  .day-number { width: 23px; height: 23px; line-height: 23px; font-size: 12px; }
  .day-events { gap: 2px; }
  .event-badge { padding: 0 2px; line-height: 14px; }
  .day-detail { border-left: 0; border-top: 1px solid var(--erp-color-border); padding-left: 0; padding-top: 15px; }
  .calendar-caption { flex-wrap: wrap; }
  .calendar-legend { gap: 7px 11px; }
}
</style>
