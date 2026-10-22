<script setup lang="ts">
import { computed, onBeforeUnmount, onDeactivated, reactive, ref, watch } from 'vue'
import { ElButton, ElDatePicker, ElMessage, ElOption, ElSelect, ElTooltip } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import * as api from '@/api/attendance'
import type { AttendanceOverview, AttendanceQuery, AttendanceTab, DailyRow, MonthlyRow, RawRow, SyncRun } from '@/types/attendance'
import AttendanceCalendarDialog from './AttendanceCalendarDialog.vue'
import AttendanceScheduleDialog from './AttendanceScheduleDialog.vue'
import { currentMonth, departmentOptions, exceptionText, formatDuration, monthLabel, shanghaiDateTime, shanghaiTime, sourceNumber, validMonth } from './attendancePresentation'

const auth = useAuthStore()
const permitted = computed(() => auth.hasPermission('attendance.view_attendance'))
const canSync = computed(() => permitted.value && auth.hasPermission('attendance.sync_attendance'))
const canSchedule = computed(() => permitted.value && auth.hasPermission('attendance.manage_schedule'))
const forbidden = ref(false), tab = ref<AttendanceTab>('monthly'), activeMonth = ref(currentMonth())
const form = reactive({ month: activeMonth.value, department: '', search: '', status: '', date: '' })
const applied = ref<AttendanceQuery>({ month: activeMonth.value }), page = ref(1), pageSize = ref(20), count = ref(0)
const overview = ref<AttendanceOverview | null>(null), monthly = ref<MonthlyRow[]>([]), daily = ref<DailyRow[]>([]), raw = ref<RawRow[]>([])
const departmentSearch = ref('')
const departments = computed(() => {
  const search = departmentSearch.value.trim().toLocaleLowerCase()
  return departmentOptions(overview.value?.departments ?? []).filter(option => option.value.toLocaleLowerCase().includes(search) || option.label.toLocaleLowerCase().includes(search))
})
const overviewLoading = ref(false), tableLoading = ref(false), overviewError = ref(''), tableError = ref(''), validationError = ref('')
const hasTableSnapshot = ref(false), scopeDialog = ref(false), scheduleDialog = ref(false), calendarDialog = ref(false)
const calendarMember = ref({ user_id: '', name: '' })
const syncRun = ref<SyncRun | null>(null), syncBusy = ref(false), syncActive = ref(false), syncError = ref(''), syncNotice = ref('')
const syncProgressVisible = ref(false)
const syncPercentage = computed(() => {
  const run = syncRun.value
  if (run?.status === 'SUCCESS') return 100
  return run && run.total_steps > 0 ? Math.min(99, Math.max(0, Math.floor(run.completed_steps / run.total_steps * 100))) : 0
})
const pageCount = computed(() => Math.max(1, Math.ceil(count.value / pageSize.value)))
const rowsCount = computed(() => tab.value === 'monthly' ? monthly.value.length : tab.value === 'daily' ? daily.value.length : raw.value.length)
const tabLabels: Record<AttendanceTab, string> = { monthly: '成员月报', daily: '成员日报', raw: '原始打卡明细' }
const syncStatus = computed(() => syncRun.value ? ({ PENDING: '待推进', RUNNING: syncActive.value ? '同步进行中' : '已暂停后续批次', FAILED: '同步未完成', SUCCESS: '同步成功', INVALIDATED: '配置变化，需重新开始' }[syncRun.value.status]) : '')
const resumeAvailable = computed(() => syncRun.value && (syncRun.value.status === 'PENDING' || syncRun.value.status === 'RUNNING' || syncRun.value.status === 'FAILED' && syncRun.value.can_retry))
const canStart = computed(() => canSync.value && !syncBusy.value)
const phaseLabel = computed(() => ({ SCOPE: '读取可见范围', DEPARTMENTS: '读取部门', ROSTER: '读取成员', MEMBERS: '读取成员', RECORDS: '读取打卡明细、日报及月报', RAW: '读取打卡明细', DAILY: '读取日报', MONTHLY: '读取月报', PUBLISH: '更新月度快照', COMPLETE: '全部完成', COMPLETED: '全部完成', DONE: '全部完成' }[syncRun.value?.phase.toUpperCase() ?? ''] || '按批读取来源数据'))
let disposed = false, overviewSequence = 0, tableSequence = 0, syncSequence = 0
let overviewController: AbortController | undefined, tableController: AbortController | undefined, syncController: AbortController | undefined
let startKey = '', startKeyMonth = ''

function live() { return !disposed && permitted.value && !forbidden.value }
function clearRecords() { monthly.value = []; daily.value = []; raw.value = []; count.value = 0; hasTableSnapshot.value = false; tableError.value = '' }
function stopSync(invalidate = false) {
  syncActive.value = false
  if (invalidate) { syncSequence++; syncController?.abort(); syncBusy.value = false }
}
function clearSensitive() {
  overviewSequence++; tableSequence++; overviewController?.abort(); tableController?.abort(); stopSync(true)
  overview.value = null; clearRecords(); syncRun.value = null; calendarDialog.value = false; scopeDialog.value = false; scheduleDialog.value = false
  calendarMember.value = { user_id: '', name: '' }; overviewLoading.value = false; tableLoading.value = false
  form.search = ''; delete applied.value.user_id; delete applied.value.search; departmentSearch.value = ''
  overviewError.value = ''; validationError.value = ''; syncError.value = ''; syncNotice.value = ''; syncProgressVisible.value = false; startKey = ''; startKeyMonth = ''
}
function denyAccess() { forbidden.value = true; clearSensitive() }
function authorizationFailed(error: unknown) {
  const status = (error as { response?: { status?: number } })?.response?.status
  if (status === 401 || status === 403) { denyAccess(); return true }
  return false
}
async function loadOverview() {
  if (!live()) return
  overviewController?.abort(); overviewController = new AbortController()
  const sequence = ++overviewSequence, signal = overviewController.signal, month = activeMonth.value
  overviewLoading.value = true; overviewError.value = ''
  try {
    const result = await api.getAttendanceOverview(month, signal)
    if (!live() || signal.aborted || sequence !== overviewSequence || month !== activeMonth.value) return
    overview.value = result
    if (!syncBusy.value) syncRun.value = result.current_run
  } catch (error) {
    if (!live() || signal.aborted || sequence !== overviewSequence) return
    if (!authorizationFailed(error)) overviewError.value = api.attendanceError(error)
  } finally { if (sequence === overviewSequence) overviewLoading.value = false }
}
async function loadRecords(clear = false) {
  if (!live()) return
  tableController?.abort(); tableController = new AbortController()
  const sequence = ++tableSequence, signal = tableController.signal, kind = tab.value
  if (clear) clearRecords()
  tableLoading.value = true; tableError.value = ''
  const query: AttendanceQuery = { ...applied.value, page: page.value, page_size: pageSize.value }
  if (kind !== 'monthly') delete query.status
  else delete query.date
  try {
    const result = await ({ monthly: api.getAttendanceMonthly, daily: api.getAttendanceDaily, raw: api.getAttendanceRaw }[kind])(query, signal)
    if (!live() || signal.aborted || sequence !== tableSequence) return
    if (kind === 'monthly') monthly.value = result.data as MonthlyRow[]
    if (kind === 'daily') daily.value = result.data as DailyRow[]
    if (kind === 'raw') raw.value = result.data as RawRow[]
    count.value = result.count; page.value = result.page; pageSize.value = result.page_size; hasTableSnapshot.value = true
  } catch (error) {
    if (!live() || signal.aborted || sequence !== tableSequence) return
    if (!authorizationFailed(error)) tableError.value = api.attendanceError(error)
  } finally { if (sequence === tableSequence) tableLoading.value = false }
}
function refresh() { void loadOverview(); void loadRecords() }
function applyFilters() {
  validationError.value = ''
  if (!validMonth(form.month)) { validationError.value = '请选择有效的考勤月份。'; return }
  if (form.date && (!/^\d{4}-\d{2}-\d{2}$/.test(form.date) || !form.date.startsWith(`${form.month}-`))) { validationError.value = '筛选日期必须属于所选考勤月份。'; return }
  const changedMonth = form.month !== activeMonth.value
  const selectedUser = changedMonth ? undefined : applied.value.user_id
  const search = applied.value.user_id ? '' : form.search.trim()
  if (changedMonth) { clearSensitive(); activeMonth.value = form.month; form.search = search }
  applied.value = { month: form.month, ...(selectedUser ? { user_id: selectedUser } : {}), ...(search ? { search } : {}), ...(form.department ? { department: form.department } : {}), ...(form.status ? { status: form.status as AttendanceQuery['status'] } : {}), ...(form.date ? { date: form.date } : {}) }
  page.value = 1
  void loadRecords(true)
  if (changedMonth) void loadOverview()
}
function resetFilters() { delete applied.value.user_id; Object.assign(form, { month: currentMonth(), department: '', search: '', status: '', date: '' }); applyFilters() }
function switchTab(value: AttendanceTab) { if (tab.value === value) return; tab.value = value; page.value = 1; void loadRecords(true) }
function changePage(value: number) { if (value < 1 || value > pageCount.value || tableLoading.value) return; page.value = value; void loadRecords(true) }
function changePageSize() { page.value = 1; void loadRecords(true) }
function filterDepartments(query: string) { departmentSearch.value = query }
function editPersonSearch() { delete applied.value.user_id }
function selectMember(member: Pick<MonthlyRow, 'user_id' | 'name'>, target = tab.value) {
  // 查看此人整月考勤时清除其他条件，避免原始流水缺少来源部门而被旧条件排除。
  validationError.value = ''
  Object.assign(form, { month: activeMonth.value, department: '', search: member.name || member.user_id, status: '', date: '' })
  tab.value = target; applied.value = { month: activeMonth.value, user_id: member.user_id }; page.value = 1; void loadRecords(true)
}
function viewDaily(member: MonthlyRow) { selectMember(member, 'daily') }
function clearMemberFilter() { form.search = ''; delete applied.value.user_id; delete applied.value.search; page.value = 1; void loadRecords(true) }
function viewCalendar(member: MonthlyRow) { calendarMember.value = { user_id: member.user_id, name: member.name }; calendarDialog.value = true }
function pauseSync() { stopSync(); syncNotice.value = '已暂停后续批次，正在进行的单步仍可完成。' }
function syncLive(sequence: number, month: string) { return live() && canSync.value && sequence === syncSequence && month === activeMonth.value }
async function synchronize(resume = false) {
  if (!live() || !canSync.value || syncBusy.value) return
  const month = activeMonth.value, sequence = ++syncSequence
  syncController = new AbortController()
  const signal = syncController.signal
  syncBusy.value = true; syncActive.value = true; syncError.value = ''; syncNotice.value = ''; syncProgressVisible.value = true
  try {
    let current: SyncRun
    if (resume && syncRun.value) current = await api.getAttendanceSync(syncRun.value.id, signal)
    else {
      if (!startKey || startKeyMonth !== month) {
        if (typeof globalThis.crypto?.randomUUID !== 'function') { syncError.value = '当前浏览器无法生成安全请求编号，请使用 HTTPS 或本机安全地址。'; return }
        startKey = crypto.randomUUID(); startKeyMonth = month
      }
      current = await api.startAttendanceSync(month, startKey, signal)
    }
    if (!syncLive(sequence, month)) return
    syncRun.value = current
    while (syncActive.value && (current.status === 'PENDING' || current.status === 'RUNNING' || current.status === 'FAILED' && current.can_retry)) {
      const previous = current
      current = await api.stepAttendanceSync(current.id, current.etag, signal)
      if (!syncLive(sequence, month)) return
      syncRun.value = current
      if (current.status === 'FAILED' || current.status === 'INVALIDATED') break
      if (current.etag === previous.etag && current.completed_steps === previous.completed_steps && current.phase === previous.phase && current.status === previous.status) {
        syncNotice.value = '本次未取得新进度，请稍后重新读取进度后继续。'; break
      }
    }
    if (current.status === 'SUCCESS') {
      startKey = ''; syncProgressVisible.value = false; syncNotice.value = ''
      ElMessage.success('同步成功，本月可见数据已切换为完整的新结果。')
      // 成功后重新读取完整快照，禁止在旧列表上累加新记录。
      void loadRecords(); void loadOverview()
    } else if (current.status === 'FAILED' || current.status === 'INVALIDATED') {
      if (current.status === 'INVALIDATED') { startKey = ''; startKeyMonth = '' }
      syncError.value = current.error_message || '本轮同步未完成，已有成功数据继续保留。'
    }
  } catch (error) {
    if (!syncLive(sequence, month) || signal.aborted) return
    if (!authorizationFailed(error)) syncError.value = `${api.attendanceError(error)} 已停止后续批次；继续时先读取最新进度。`
  } finally {
    if (sequence === syncSequence) { syncBusy.value = false; syncActive.value = false }
  }
}

watch(permitted, value => { if (!value) { clearSensitive(); forbidden.value = true } else { forbidden.value = false; refresh() } }, { immediate: true, flush: 'sync' })
watch(canSync, value => { if (!value) { stopSync(true); syncError.value = ''; syncNotice.value = ''; syncProgressVisible.value = false } }, { flush: 'sync' })
watch(canSchedule, value => { if (!value) scheduleDialog.value = false }, { flush: 'sync' })
onDeactivated(() => { clearSensitive() })
onBeforeUnmount(() => { disposed = true; clearSensitive() })
</script>

<template>
  <div class="attendance-page erp-glass-list" :data-state="!permitted || forbidden ? 'forbidden' : tableLoading ? 'loading' : tableError ? hasTableSnapshot ? 'stale' : 'error' : 'ready'">
    <section class="attendance-heading erp-list-filter">
      <header class="heading-line">
        <div class="heading-info"><h1>考勤管理</h1><span class="attendance-tag">企业微信</span></div>
        <div v-if="permitted && !forbidden" class="attendance-summary" data-testid="attendance-summary" :aria-busy="overviewLoading" aria-label="所选月份考勤来源汇总">
          <div class="summary-item"><span>返回考勤成员</span><div><strong data-testid="attendance-stat-value">{{ !overviewLoading && overview?.has_data ? sourceNumber(overview.attendance_members) : '—' }}</strong><span>人</span></div></div>
          <div class="summary-item"><span>原始打卡</span><div><strong data-testid="attendance-stat-value">{{ !overviewLoading && overview?.has_data ? sourceNumber(overview.raw_count) : '—' }}</strong><span>条</span></div></div>
          <div class="summary-item"><span>日报</span><div><strong data-testid="attendance-stat-value">{{ !overviewLoading && overview?.has_data ? sourceNumber(overview.daily_count) : '—' }}</strong><span>行</span></div></div>
          <div class="summary-item"><span>扫描成员</span><div><strong data-testid="attendance-stat-value">{{ !overviewLoading && overview?.has_data ? sourceNumber(overview.scanned_members) : '—' }}</strong><span>人</span></div></div>
        </div>
      </header>
      <template v-if="permitted && !forbidden">
        <form class="filters" @submit.prevent="applyFilters">
          <div class="field month-field"><ElDatePicker v-model="form.month" type="month" format="YYYY 年 MM 月" value-format="YYYY-MM" :clearable="false" :editable="false" aria-label="考勤月份" /></div>
          <div class="field department-field"><ElSelect v-model="form.department" filterable :filter-method="filterDepartments" :empty-values="[null, undefined]" :fit-input-width="false" :popper-style="{ width: '320px', maxWidth: 'calc(100vw - 32px)' }" popper-class="attendance-department-dropdown" aria-label="部门" placeholder="全部部门" @visible-change="departmentSearch = ''"><ElOption label="全部部门" value="" /><ElOption v-for="department in departments" :key="department.value" :value="department.value" :label="department.label" :title="department.value" /></ElSelect></div>
          <div class="field person"><input v-model="form.search" placeholder="姓名 / 企业微信账号" aria-label="人员" autocomplete="off" @input="editPersonSearch"></div>
          <div class="field status-field"><ElSelect v-model="form.status" :empty-values="[null, undefined]" aria-label="记录状态" placeholder="全部状态" :disabled="tab !== 'monthly'"><ElOption label="全部状态" value="" /><ElOption label="有返回记录" value="RETURNED" /><ElOption label="未返回记录" value="NOT_RETURNED" /></ElSelect></div>
          <div class="filter-actions"><ElButton native-type="submit">查询</ElButton><ElButton @click="resetFilters">重置</ElButton></div>
          <div class="heading-actions"><ElButton v-if="canSchedule" @click="scheduleDialog = true">设置当月上班时间</ElButton><ElButton @click="scopeDialog = true">同步范围说明</ElButton><ElButton v-if="canSync" type="primary" data-testid="start-sync" :disabled="!canStart" @click="synchronize(!!resumeAvailable)">{{ resumeAvailable ? '继续同步所选月份' : '同步所选月份' }}</ElButton></div>
        </form>
        <p v-if="validationError" class="feedback error" role="alert">{{ validationError }}</p>
        <p v-if="overviewError" role="alert" class="feedback error">{{ overviewError }} {{ overview ? '概况保留上次成功结果。' : '' }}</p>
      </template>
    </section>
    <p v-if="!permitted || forbidden" class="feedback error erp-list-surface" role="alert">当前账号无权查看考勤。请联系管理员核对考勤权限与员工状态。</p>
    <template v-else>
      <section class="table-card erp-list-data">
        <div class="table-top">
          <div class="tabs" role="tablist" aria-label="考勤报表"><button v-for="kind in (['monthly', 'daily', 'raw'] as const)" :key="kind" type="button" role="tab" :aria-selected="tab === kind" :data-testid="`tab-${kind}`" @click="switchTab(kind)">{{ { monthly: '月报', daily: '日报', raw: '打卡明细' }[kind] }}</button></div>
          <span class="table-caption">{{ monthLabel(activeMonth) }} · {{ tabLabels[tab] }}</span>
          <label v-if="tab !== 'monthly'" class="date-filter"><span>日期</span><input v-model="form.date" type="date" aria-label="考勤日期" :min="`${activeMonth}-01`" @change="applyFilters"></label>
          <ElButton data-testid="refresh" :disabled="tableLoading || overviewLoading" @click="refresh">刷新数据</ElButton>
        </div>
        <section v-if="syncProgressVisible" class="sync-progress" data-testid="sync-progress" aria-live="polite">
          <div class="sync-progress-detail"><strong>{{ syncRun ? syncStatus : syncBusy ? '正在创建同步批次…' : '同步状态' }}</strong><div class="sync-progress-meter"><progress aria-label="同步进度" :value="syncRun ? syncPercentage : undefined" max="100" /><span v-if="syncRun">{{ syncPercentage }}%</span></div><p v-if="syncRun">{{ phaseLabel }} · 已读取 {{ syncRun.scanned_members }} 人</p><p v-if="syncError" class="error" role="alert">{{ syncError }}</p><p v-if="syncNotice">{{ syncNotice }}</p></div>
          <ElButton v-if="syncActive && canSync" data-testid="pause-sync" @click="pauseSync">暂停后续批次</ElButton><ElButton v-else-if="resumeAvailable && canSync" data-testid="resume-sync" :disabled="syncBusy" @click="synchronize(true)">{{ syncRun?.status === 'FAILED' ? '读取进度并重试' : '继续同步' }}</ElButton>
        </section>
        <p v-if="applied.user_id" class="member-filter">企业微信账号：{{ applied.user_id }}<ElButton link @click="clearMemberFilter">查看全部人员</ElButton></p>
        <p v-if="tableError" class="feedback error" role="alert">{{ tableError }} {{ hasTableSnapshot ? '下表保留上次成功读取的数据。' : '' }}<ElButton size="small" @click="loadRecords()">重新读取</ElButton></p>
        <p v-if="tableLoading" class="loading-note" role="status">正在读取{{ tabLabels[tab] }}…</p>
        <p class="mobile-scroll">可在表格内左右滑动查看全部字段</p>
        <div class="table-frame" tabindex="0" role="region" aria-label="考勤表格，可水平滚动" :aria-busy="tableLoading" data-testid="attendance-records">
          <table v-if="tab === 'monthly'" class="monthly-table">
            <colgroup><col v-for="(width, index) in [90, 130, 193, 90, 86, 100, 100, 70, 70, 70, 100, 125]" :key="index" :style="{ width: `${width}px` }"></colgroup>
            <thead><tr><th>成员</th><th>企业微信账号</th><th>部门</th><th>ERP 绑定</th><th class="numeric">应出勤天数</th><th class="numeric">标准工时</th><th class="numeric">实际工时</th><th class="numeric">迟到次数</th><th class="numeric">早退次数</th><th class="numeric">缺卡次数</th><th>记录状态</th><th>操作</th></tr></thead>
            <tbody><tr v-for="(member, index) in monthly" :key="`${member.user_id}-${index}`">
              <td :title="member.name || '姓名未返回'"><button type="button" class="text-button member-button" data-testid="select-member" @click="selectMember(member)">{{ member.name || '姓名未返回' }}</button></td>
              <td class="account" :title="member.user_id">{{ member.user_id }}</td>
              <td :title="member.department_name || '未返回'"><ElTooltip :content="member.department_name || '未返回'" :trigger="['hover', 'focus']" placement="top"><span class="cell-text" tabindex="0">{{ member.department_name || '未返回' }}</span></ElTooltip></td>
              <td :title="member.employee_name ? `已绑定 ERP 员工：${member.employee_name}` : '未绑定 ERP'"><span class="attendance-tag" :class="{ muted: !member.employee_id }">{{ member.employee_id ? '已绑定' : '未绑定 ERP' }}</span></td>
              <td class="numeric" :title="sourceNumber(member.work_days, ' 天')">{{ sourceNumber(member.work_days, ' 天') }}</td>
              <td class="numeric" :title="formatDuration(member.standard_work_sec)">{{ formatDuration(member.standard_work_sec) }}</td>
              <td class="numeric" :title="formatDuration(member.regular_work_sec)">{{ formatDuration(member.regular_work_sec) }}</td>
              <td class="numeric" :title="sourceNumber(member.late_count, ' 次')">{{ sourceNumber(member.late_count, ' 次') }}</td>
              <td class="numeric" :title="sourceNumber(member.early_count, ' 次')">{{ sourceNumber(member.early_count, ' 次') }}</td>
              <td class="numeric" :title="sourceNumber(member.missing_count, ' 次')">{{ sourceNumber(member.missing_count, ' 次') }}</td>
              <td><span class="attendance-tag" :class="{ muted: member.record_status !== 'RETURNED' }">{{ member.record_status === 'RETURNED' ? '有返回记录' : '未返回记录' }}</span></td>
              <td><div class="row-actions"><button type="button" class="text-button" @click="viewDaily(member)">查看日报</button><button type="button" class="text-button" data-testid="open-calendar" @click="viewCalendar(member)">查看月历</button></div></td>
            </tr></tbody>
          </table>
          <table v-else-if="tab === 'daily'" class="daily-table">
            <colgroup><col v-for="(width, index) in [90, 130, 193, 105, 90, 110, 110, 120, 120, 156]" :key="index" :style="{ width: `${width}px` }"></colgroup>
            <thead><tr><th>成员</th><th>企业微信账号</th><th>部门</th><th>日期</th><th class="numeric">打卡次数</th><th class="numeric">标准工时</th><th class="numeric">实际工时</th><th>打卡规则</th><th>班次</th><th>企微返回异常</th></tr></thead>
            <tbody><tr v-for="(record, index) in daily" :key="`${record.id}-${index}`">
              <td :title="record.name || '姓名未返回'"><button type="button" class="text-button member-button" data-testid="select-member" @click="selectMember(record)">{{ record.name || '姓名未返回' }}</button></td><td class="account" :title="record.user_id">{{ record.user_id }}</td>
              <td :title="record.department_name || '未返回'"><ElTooltip :content="record.department_name || '未返回'" :trigger="['hover', 'focus']" placement="top"><span class="cell-text" tabindex="0">{{ record.department_name || '未返回' }}</span></ElTooltip></td>
              <td>{{ record.date }}</td><td class="numeric" :title="sourceNumber(record.checkin_count, ' 次')">{{ sourceNumber(record.checkin_count, ' 次') }}</td>
              <td class="numeric" :title="formatDuration(record.standard_work_sec)">{{ formatDuration(record.standard_work_sec) }}</td><td class="numeric" :title="formatDuration(record.regular_work_sec)">{{ formatDuration(record.regular_work_sec) }}</td>
              <td :title="record.group_name || '未返回'">{{ record.group_name || '未返回' }}</td><td :title="record.schedule_name || '未返回'">{{ record.schedule_name || '未返回' }}</td>
              <td :title="exceptionText(record.exceptions)"><ElTooltip :content="exceptionText(record.exceptions)" :trigger="['hover', 'focus']" placement="top"><span class="cell-text" tabindex="0">{{ exceptionText(record.exceptions) }}</span></ElTooltip></td>
            </tr></tbody>
          </table>
          <table v-else class="raw-table">
            <colgroup><col v-for="(width, index) in [90, 130, 193, 180, 130, 251, 250]" :key="index" :style="{ width: `${width}px` }"></colgroup>
            <thead><tr><th>成员</th><th>企业微信账号</th><th>部门</th><th>打卡时间（北京时间）</th><th>打卡类型</th><th>打卡规则</th><th>企微返回异常</th></tr></thead>
            <tbody><tr v-for="(record, index) in raw" :key="`${record.id}-${index}`">
              <td :title="record.name || '姓名未返回'"><button type="button" class="text-button member-button" data-testid="select-member" @click="selectMember(record)">{{ record.name || '姓名未返回' }}</button></td><td class="account" :title="record.user_id">{{ record.user_id }}</td>
              <td :title="record.department_name || '未返回'"><ElTooltip :content="record.department_name || '未返回'" :trigger="['hover', 'focus']" placement="top"><span class="cell-text" tabindex="0">{{ record.department_name || '未返回' }}</span></ElTooltip></td>
              <td :title="`${record.date} ${shanghaiTime(record.checkin_time)}`">{{ record.date }} {{ shanghaiTime(record.checkin_time) }}</td><td :title="record.checkin_type || '未返回'">{{ record.checkin_type || '未返回' }}</td>
              <td :title="record.group_name || '未返回'">{{ record.group_name || '未返回' }}</td><td :title="record.exceptions.length ? record.exceptions.join('、') : '来源未列出异常'">{{ record.exceptions.length ? record.exceptions.join('、') : '来源未列出异常' }}</td>
            </tr></tbody>
          </table>
          <div v-if="!rowsCount" class="empty-state" role="status">{{ tableLoading ? '正在加载来源数据…' : tableError ? '读取未完成，请重试。' : overview?.has_data === false ? '该月份尚未同步完成，暂无成功快照。' : '当前筛选下未返回记录，不据此判断缺勤。' }}</div>
        </div>
        <div class="table-footer"><span>共 {{ count.toLocaleString('zh-CN') }} {{ tab === 'monthly' ? '行成员月报' : '条来源记录' }}</span><div class="pagination"><select v-model.number="pageSize" aria-label="每页条数" :disabled="tableLoading" @change="changePageSize"><option :value="20">20 条 / 页</option><option :value="50">50 条 / 页</option><option :value="100">100 条 / 页</option></select><ElButton :disabled="page <= 1 || tableLoading" @click="changePage(page - 1)">上一页</ElButton><span>{{ page }} / {{ pageCount }}</span><ElButton data-testid="next-page" :disabled="page >= pageCount || tableLoading" @click="changePage(page + 1)">下一页</ElButton></div></div>
      </section>
      <AttendanceCalendarDialog v-model="calendarDialog" :month="activeMonth" :user-id="calendarMember.user_id" :name="calendarMember.name" :people="monthly" @forbidden="denyAccess" />
      <AppWindowDialog v-model="scopeDialog" title="同步范围说明" :width="620" height="auto" :min-width="300"><div class="scope-dialog">
        <p>同步包含当前应用可见范围内的企业微信成员，包括未绑定 ERP 员工或账号的成员。部门按来源快照展示，时间统一为北京时间。</p>
        <p>身份按企业与企业微信账号精确对应，不按姓名合并、不创建员工或绑定。</p>
        <p>{{ overview?.history_notice || '当前通讯录不能证明历史离职人员完整覆盖，历史月份需另行核对。' }}</p>
        <p>{{ monthLabel(activeMonth) }}：{{ overview?.has_data ? '已保存成功快照' : '尚未同步完成' }}。最后成功同步：{{ shanghaiDateTime(overview?.last_synced_at) }}。</p>
        <p v-if="overview?.has_data">月报来源 {{ sourceNumber(overview.monthly_count, ' 行') }}；数据日期 {{ overview.source_start || '未返回' }} 至 {{ overview.source_end || '未返回' }}。</p>
        <p>本页只保留考勤所需来源字段，不采集定位、WiFi、照片或备注。</p>
      </div><template #footer><ElButton @click="scopeDialog = false">关闭</ElButton></template></AppWindowDialog>
      <AttendanceScheduleDialog v-model="scheduleDialog" :month="activeMonth" @saved="refresh" @forbidden="denyAccess" />
    </template>
  </div>
</template>

<style scoped lang="scss">
.attendance-page.erp-glass-list { display: flex; flex: 1; flex-direction: column; gap: 12px; width: 100%; height: 100%; min-width: 0; min-height: 0; margin: 0; overflow: hidden; color: var(--erp-color-text-primary); font-size: 13px; }
.attendance-page * { box-sizing: border-box; }
.attendance-heading.erp-list-filter { flex: none; padding: 8px 16px 12px; }
.heading-line, .heading-info, .heading-actions { display: flex; align-items: center; gap: 12px; }
.heading-line { justify-content: space-between; min-height: 44px; }
.heading-info { flex: none; }
.attendance-page .heading-info h1 { margin: 0; font-size: 34px !important; line-height: 44px !important; font-weight: 700; white-space: nowrap; }
.heading-actions { flex: none; gap: 8px; margin-left: auto; justify-content: flex-end; flex-wrap: wrap; }
.heading-actions :deep(.el-button + .el-button), .filter-actions :deep(.el-button + .el-button), .pagination :deep(.el-button + .el-button) { margin-left: 0; }
.attendance-tag { display: inline-flex; align-items: center; min-height: 22px; padding: 0 7px; border: 1px solid var(--erp-color-brand-light-5); border-radius: 999px; color: var(--erp-color-brand); background: var(--erp-color-info-soft); font-size: 11px; line-height: 20px; white-space: nowrap; }
.attendance-tag.muted { color: var(--erp-color-text-secondary); border-color: var(--erp-color-border); background: var(--erp-color-readonly); }
.attendance-summary { position: relative; isolation: isolate; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); flex: 0 1 420px; width: 420px; max-width: 100%; padding: 12px 0; overflow: hidden; border: 1px solid var(--erp-stat-border); border-radius: 12px; color: var(--erp-stat-text); background: var(--erp-stat-background); box-shadow: var(--erp-stat-shadow); }
.attendance-summary::before { content: ''; position: absolute; z-index: -1; right: -24px; bottom: -72px; width: 240px; height: 110px; border-radius: 50%; background: var(--erp-stat-glow); filter: blur(42px); opacity: var(--erp-stat-glow-opacity); pointer-events: none; }
.summary-item { min-width: 0; padding: 0 12px; border-right: 1px solid var(--erp-stat-divider); }
.summary-item:last-child { border-right: 0; }
.summary-item > span { display: block; font-size: 12px; line-height: 18px; white-space: nowrap; }
.summary-item > div { display: flex; gap: 4px; align-items: baseline; margin-top: 4px; white-space: nowrap; }
.summary-item strong { color: var(--erp-stat-text); font-size: 24px; line-height: 30px; font-weight: 600; font-variant-numeric: tabular-nums; }
.summary-item > div > span { font-size: 12px; }
.filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; margin-top: 10px; }
.field { display: flex; flex: none; min-width: 0; }
.month-field { width: 152px; }
.department-field { width: 180px; }
.person { width: 220px; }
.status-field { width: 128px; }
.field > input, .date-filter input, .pagination select { height: 32px; min-width: 0; width: 100%; padding: 0 12px; border: 1px solid var(--erp-control-border); border-radius: 8px; background: var(--erp-input-surface); box-shadow: var(--erp-input-shadow); color: var(--erp-color-text-primary); font: inherit; }
.field > input::placeholder { color: var(--erp-control-placeholder); }
.field > input:focus-visible, .date-filter input:focus-visible, .pagination select:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
.field :deep(.el-select__wrapper) { height: 32px; min-height: 32px; padding: 0 12px; border-radius: var(--erp-radius-control); background: var(--erp-input-surface); box-shadow: var(--erp-input-shadow), inset 0 0 0 1px var(--erp-input-border); }
.field :deep(.el-select__wrapper:hover) { box-shadow: var(--erp-input-shadow), inset 0 0 0 1px var(--erp-input-hover-border); }
.field :deep(.el-select__wrapper.is-focused) { box-shadow: var(--erp-input-shadow), inset 0 0 0 1px var(--erp-input-focus-border); }
.field :deep(.el-select__input), .field :deep(.el-select__selected-item) { color: var(--erp-input-text); font-size: 12px; line-height: 18px; }
.field :deep(.el-select__wrapper.is-disabled) { background: var(--erp-input-disabled-background); }
.field :deep(.el-select__wrapper.is-disabled .el-select__placeholder) { color: var(--erp-input-disabled-text); }
.month-field :deep(.el-date-editor.el-input) { width: 152px; max-width: 100%; height: 32px; }
.month-field :deep(.el-input__wrapper) { height: 32px; min-height: 32px; padding: 0 12px; border-radius: 8px; background: var(--erp-input-surface); box-shadow: var(--erp-input-shadow), inset 0 0 0 1px var(--erp-input-border); }
.month-field :deep(.el-input__wrapper.is-focus) { box-shadow: var(--erp-input-shadow), inset 0 0 0 1px var(--erp-input-focus-border); }
.month-field :deep(.el-input__inner) { color: var(--erp-input-text); font-size: 12px; }
.filter-actions { display: flex; flex: none; gap: 8px; }
.sync-progress { display: flex; flex: none; align-items: start; justify-content: space-between; gap: 16px; padding: 8px 12px; margin-bottom: 8px; border-radius: 8px; background: var(--erp-color-info-soft); }
.sync-progress strong { font-size: 13px; color: var(--erp-color-brand); }
.sync-progress p { margin: 5px 0; font-size: 12px; }
.sync-progress-detail { flex: 1; min-width: 0; width: 100%; }
.sync-progress-meter { display: flex; align-items: center; gap: 10px; margin-top: 8px; font-size: 12px; }
.sync-progress-meter progress { width: 100%; height: 10px; accent-color: var(--erp-color-brand); }
.table-card.erp-list-data { display: flex; flex: 1; flex-direction: column; min-width: 0; min-height: 0; padding: 0 16px; overflow: hidden; }
.table-top { display: flex; flex: none; align-items: center; justify-content: space-between; gap: 12px; min-height: 44px; flex-wrap: wrap; }
.tabs { display: flex; gap: 26px; align-self: stretch; }
.tabs button { position: relative; height: 44px; padding: 0 2px; border: 0; border-radius: 0; background: transparent; color: var(--erp-color-text-secondary); box-shadow: none; cursor: pointer; font: inherit; white-space: nowrap; }
.tabs button[aria-selected='true'] { font-weight: 600; color: var(--erp-color-brand); }
.tabs button[aria-selected='true']::after { content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 3px; border-radius: 3px 3px 0 0; background: var(--erp-color-brand); }
.tabs button:focus-visible, .text-button:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
.table-caption { margin-right: auto; font-size: 12px; color: var(--erp-color-text-secondary); white-space: nowrap; }
.date-filter { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.date-filter input { width: 150px; }
.member-filter { display: flex; flex: none; align-items: center; gap: 10px; font-size: 12px; margin: 0 0 8px; overflow-wrap: anywhere; }
.table-frame { flex: 1; min-width: 0; min-height: 0; border: 1px solid var(--erp-color-border); border-radius: 8px; overflow: auto; scrollbar-width: thin; background: var(--erp-table-body-fill); }
table { width: 100%; min-width: 1224px; border-collapse: separate; border-spacing: 0; table-layout: fixed; font-size: 12px; line-height: 20px; color: var(--erp-table-text); }
th, td { text-align: left; padding: 0 10px; border: 0; border-right: 1px solid var(--erp-table-grid); border-bottom: 1px solid var(--erp-table-grid); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
th { position: sticky; top: 0; z-index: 2; height: 38px; font-weight: 500; background: var(--erp-table-header-fill); color: var(--erp-table-header-text); }
td { height: 34px; background: var(--erp-table-body-fill); }
th:last-child, td:last-child { border-right: 0; }
tbody tr:last-child td { border-bottom: 0; }
tbody tr:hover td { background: var(--erp-color-hover); }
.numeric { text-align: right; font-variant-numeric: tabular-nums; }
.account { color: var(--erp-color-text-secondary); }
.cell-text { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cell-text:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: -2px; }
.row-actions { display: flex; gap: 10px; align-items: center; }
.text-button { min-height: 24px; padding: 0; border: 0; background: none; color: var(--erp-color-brand); box-shadow: none; font: inherit; white-space: nowrap; cursor: pointer; }
.text-button:hover { text-decoration: underline; }
.member-button { display: block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
.empty-state { padding: 72px 20px; color: var(--erp-color-text-secondary); text-align: center; background: var(--erp-table-body-fill); }
.table-footer { display: flex; flex: none; align-items: center; justify-content: space-between; gap: 12px; min-height: 44px; font-size: 12px; color: var(--erp-color-text-secondary); }
.pagination { display: flex; gap: 9px; align-items: center; }
.pagination select { height: 28px; width: 110px; font-size: 12px; }
.pagination :deep(.el-button) { height: 28px; padding: 0 9px; }
.feedback { display: flex; flex: none; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0; padding: 10px 0; font-size: 12px; }
.error { color: var(--erp-color-danger); }
.loading-note { flex: none; font-size: 12px; color: var(--erp-color-text-secondary); margin: 0 0 8px; }
.scope-dialog { font-size: 13px; line-height: 1.8; color: var(--erp-color-text-primary); }
.mobile-scroll { display: none; }
@media (max-width: 1100px) { .table-caption { display: none; } .heading-line { align-items: start; } }
@media (max-width: 640px) {
  .attendance-page.erp-glass-list { gap: 10px; overflow-x: hidden; overflow-y: auto; }
  .attendance-heading.erp-list-filter { padding: 8px 12px 12px; }
  .attendance-page .heading-info h1 { font-size: 28px !important; line-height: 38px !important; }
  .heading-line { flex-direction: column; gap: 8px; }
  .attendance-summary { width: 100%; flex-basis: auto; padding: 10px 0; grid-template-columns: repeat(2, minmax(0, 1fr)); row-gap: 10px; }
  .summary-item:nth-child(2) { border-right: 0; }
  .summary-item:nth-child(n + 3) { padding-top: 10px; border-top: 1px solid var(--erp-stat-divider); }
  .summary-item strong { font-size: 24px; }
  .filters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .field, .month-field :deep(.el-date-editor.el-input) { width: 100%; }
  .filters .person { grid-column: 1 / -1; }
  .filter-actions { grid-column: 1 / -1; justify-content: flex-end; }
  .heading-actions { grid-column: 1 / -1; margin-left: 0; justify-content: flex-end; gap: 8px; }
  .table-card.erp-list-data { flex: none; min-height: 400px; padding: 0 10px; overflow: visible; }
  .table-top { gap: 8px; padding-bottom: 6px; }
  .tabs { gap: 18px; }
  .table-frame { flex: none; min-height: 260px; max-height: 420px; }
  .date-filter { flex-basis: 100%; order: 1; }
  .date-filter input { flex: 1; }
  .table-footer { flex-wrap: wrap; padding: 8px 0; }
  .pagination { width: 100%; justify-content: space-between; gap: 5px; flex-wrap: wrap; }
  .pagination select { width: 95px; }
  .mobile-scroll { display: block; flex: none; margin: 0 0 6px; font-size: 11px; color: var(--erp-color-text-muted); }
  .sync-progress { flex-direction: column; }
}
</style>
