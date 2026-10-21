import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import WeComAttendanceView from './WeComAttendanceView.vue'
import type { AttendanceOverview, MonthlyRow, SyncRun } from '@/types/attendance'

const api = vi.hoisted(() => ({ getAttendanceOverview: vi.fn(), getAttendanceMonthly: vi.fn(), getAttendanceDaily: vi.fn(), getAttendanceRaw: vi.fn(), getAttendanceCalendar: vi.fn(), startAttendanceSync: vi.fn(), getAttendanceSync: vi.fn(), stepAttendanceSync: vi.fn() }))
const messages = vi.hoisted(() => ({ success: vi.fn() }))
vi.mock('@/api/attendance', async original => ({ ...await original<object>(), ...api }))
vi.mock('element-plus', async original => ({ ...await original<object>(), ElMessage: messages }))
const member: MonthlyRow = { user_id: 'Member.Unbound', name: '未绑定成员甲', department_name: '来源部门', employee_id: null, employee_name: null, record_status: 'NOT_RETURNED', work_days: null, standard_work_sec: null, regular_work_sec: null, late_count: null, early_count: null, missing_count: null }
function overview(): AttendanceOverview { return { month: '2026-10', corp_id: 'corp', has_data: true, last_synced_at: '2026-10-19T00:00:00Z', scanned_members: 256, attendance_members: 78, raw_count: 4403, daily_count: 2209, monthly_count: 78, source_start: '2026-10-01', source_end: '2026-10-19', departments: ['来源部门'], current_run: null, history_notice: '当前成员名单不能证明历史离职人员完整覆盖。' } }
function run(overrides: Partial<SyncRun> = {}): SyncRun { return { id: 'run-1', month: '2026-10', status: 'PENDING', phase: 'ROSTER', completed_steps: 0, total_steps: 3, scanned_members: 256, error_code: '', error_message: '', can_retry: true, etag: 'v1', created_at: '', updated_at: '', ...overrides } }
const page = (data: unknown[] = []) => ({ data, count: data.length, page: 1, page_size: 20 })
const wrappers: ReturnType<typeof mount>[] = []
function render() {
  const wrapper = mount(WeComAttendanceView, { global: { stubs: {
    AppWindowDialog: { props: ['modelValue', 'title'], emits: ['update:modelValue'], template: '<section v-if="modelValue" role="dialog"><h2>{{ title }}</h2><slot /><slot name="footer" /></section>' },
    ElDatePicker: { props: ['modelValue', 'type'], emits: ['update:modelValue', 'change'], template: '<input aria-label="考勤月份" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" @change="$emit(\'change\', $event.target.value)">' },
    ElSelect: { props: ['modelValue', 'disabled', 'filterable'], emits: ['update:modelValue'], template: '<select :value="modelValue" :disabled="disabled" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>' },
    ElOption: { props: ['value', 'label'], template: '<option :value="value"><slot>{{ label }}</slot></option>' },
  } } })
  wrappers.push(wrapper); return wrapper
}
function authorize(permissions = ['attendance.view_attendance', 'attendance.sync_attendance']) {
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true, employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions, data_scope: 'ALL' } })
}
beforeEach(() => {
  vi.resetAllMocks(); vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-19T04:00:00Z')); setActivePinia(createPinia()); authorize()
  api.getAttendanceOverview.mockResolvedValue(overview()); api.getAttendanceMonthly.mockResolvedValue(page([member])); api.getAttendanceDaily.mockResolvedValue(page()); api.getAttendanceRaw.mockResolvedValue(page())
  api.getAttendanceCalendar.mockResolvedValue({ month: '2026-09', user_id: member.user_id, name: member.name, days: [{ date: '2026-09-15', report_returned: true, checkin_count: 2, states: ['late', 'early'], exceptions: [{ type: 1, count: 1 }, { type: 2, count: 1 }], raw: [{ id: 'raw-1', date: '2026-09-15', user_id: member.user_id, name: member.name, department_name: '', checkin_time: '2026-09-15T01:12:00Z', checkin_type: '上班打卡', group_name: '规则甲', exceptions: ['迟到'] }] }] })
  api.startAttendanceSync.mockResolvedValue(run()); api.getAttendanceSync.mockResolvedValue(run()); api.stepAttendanceSync.mockResolvedValue(run({ status: 'SUCCESS', completed_steps: 3, etag: 'v4' }))
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks(); vi.useRealTimers() })

describe('企业微信考勤页面', () => {
  it('紧凑部门选项保留完整路径用于查询，同名末级部门不合并', async () => {
    const departments = ['企业来源 / 总部 / 行政', '企业来源 / 工厂 / 行政']
    api.getAttendanceOverview.mockResolvedValueOnce({ ...overview(), departments })
    const wrapper = render(); await flushPromises()
    expect(wrapper.findAll('.filters .field > span')).toHaveLength(0)
    const options = wrapper.get('[aria-label="部门"]').findAll('option')
    expect(options.map(option => option.text())).toEqual(['全部部门', '总部 / 行政', '工厂 / 行政'])
    expect(options[2]?.attributes('title')).toBe(departments[1])
    await wrapper.get('[aria-label="部门"]').setValue(departments[1]); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(api.getAttendanceMonthly.mock.calls.at(-1)?.[0]).toMatchObject({ department: departments[1], page_size: 20 })
    expect(api.startAttendanceSync).not.toHaveBeenCalled()
  })
  it('点击同名成员按账号精确筛选并回填，清除其他条件，未提交月份不改变记录来源月', async () => {
    const second = { ...member, user_id: 'Other.Identity' }
    api.getAttendanceMonthly.mockResolvedValue(page([member, second]))
    const wrapper = render(); await flushPromises()
    await wrapper.get('[aria-label="部门"]').setValue('来源部门'); await wrapper.get('form').trigger('submit'); await flushPromises()
    await wrapper.get('[aria-label="考勤月份"]').setValue('2026-13'); await wrapper.get('form').trigger('submit')
    expect(wrapper.text()).toContain('请选择有效的考勤月份')
    await wrapper.get('[aria-label="考勤月份"]').setValue('2026-09')
    await wrapper.findAll('[data-testid="select-member"]')[1]!.trigger('click'); await flushPromises()
    expect((wrapper.get('[aria-label="人员"]').element as HTMLInputElement).value).toBe(second.name)
    expect((wrapper.get('[aria-label="考勤月份"]').element as HTMLInputElement).value).toBe('2026-10')
    expect(wrapper.text()).not.toContain('请选择有效的考勤月份')
    expect(api.getAttendanceMonthly.mock.calls.at(-1)?.[0]).toMatchObject({ month: '2026-10', user_id: second.user_id })
    expect(api.getAttendanceMonthly.mock.calls.at(-1)?.[0]).not.toHaveProperty('department')
    expect((wrapper.get('[aria-label="部门"]').element as HTMLSelectElement).value).toBe('')
    expect(api.getAttendanceMonthly.mock.calls.at(-1)?.[0]).not.toHaveProperty('search')
    await wrapper.get('[data-testid="tab-daily"]').trigger('click'); await flushPromises()
    await wrapper.get('[data-testid="tab-raw"]').trigger('click'); await flushPromises()
    expect(api.getAttendanceRaw.mock.calls.at(-1)?.[0]).toMatchObject({ user_id: second.user_id })
    expect(api.getAttendanceRaw.mock.calls.at(-1)?.[0]).not.toHaveProperty('department')
    expect(api.startAttendanceSync).not.toHaveBeenCalled()
  })
  it('查看日报回填人员并清除部门，查看全部同时清除账号和输入框', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.get('[aria-label="部门"]').setValue('来源部门'); await wrapper.get('form').trigger('submit'); await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '查看日报')!.trigger('click'); await flushPromises()
    expect((wrapper.get('[aria-label="人员"]').element as HTMLInputElement).value).toBe(member.name)
    expect(api.getAttendanceDaily.mock.calls.at(-1)?.[0]).toMatchObject({ user_id: member.user_id })
    expect(api.getAttendanceDaily.mock.calls.at(-1)?.[0]).not.toHaveProperty('department')
    expect((wrapper.get('[aria-label="部门"]').element as HTMLSelectElement).value).toBe('')
    await wrapper.findAll('button').find(button => button.text() === '查看全部人员')!.trigger('click'); await flushPromises()
    expect((wrapper.get('[aria-label="人员"]').element as HTMLInputElement).value).toBe('')
    expect(api.getAttendanceDaily.mock.calls.at(-1)?.[0]).not.toHaveProperty('department')
    expect(api.getAttendanceDaily.mock.calls.at(-1)?.[0]).not.toHaveProperty('user_id')
    expect(api.getAttendanceDaily.mock.calls.at(-1)?.[0]).not.toHaveProperty('search')
  })
  it('手动改写或清空人员框解除旧账号约束，查询才提交新文字', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.get('[data-testid="select-member"]').trigger('click'); await flushPromises()
    const calls = api.getAttendanceMonthly.mock.calls.length
    await wrapper.get('[aria-label="人员"]').setValue('另一个人员')
    expect(api.getAttendanceMonthly).toHaveBeenCalledTimes(calls)
    await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(api.getAttendanceMonthly.mock.calls.at(-1)?.[0]).toMatchObject({ search: '另一个人员' })
    expect(api.getAttendanceMonthly.mock.calls.at(-1)?.[0]).not.toHaveProperty('user_id')
    await wrapper.get('[data-testid="select-member"]').trigger('click'); await flushPromises()
    await wrapper.get('[aria-label="人员"]').setValue('')
    await wrapper.get('[data-testid="tab-raw"]').trigger('click'); await flushPromises()
    expect(api.getAttendanceRaw.mock.calls.at(-1)?.[0]).not.toHaveProperty('user_id')
    expect(api.getAttendanceRaw.mock.calls.at(-1)?.[0]).not.toHaveProperty('search')
  })
  it('换月清除选中身份与回填姓名，手动输入的普通搜索仍可跨月使用', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.get('[data-testid="select-member"]').trigger('click'); await flushPromises()
    await wrapper.get('[aria-label="考勤月份"]').setValue('2026-09'); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(api.getAttendanceMonthly.mock.calls.at(-1)?.[0]).not.toHaveProperty('user_id')
    expect(api.getAttendanceMonthly.mock.calls.at(-1)?.[0]).not.toHaveProperty('search')
    expect((wrapper.get('[aria-label="人员"]').element as HTMLInputElement).value).toBe('')
    await wrapper.get('[aria-label="人员"]').setValue('手动搜索')
    await wrapper.get('[aria-label="考勤月份"]').setValue('2026-08'); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(api.getAttendanceMonthly.mock.calls.at(-1)?.[0]).toMatchObject({ month: '2026-08', search: '手动搜索' })
    expect((wrapper.get('[aria-label="人员"]').element as HTMLInputElement).value).toBe('手动搜索')
  })
  it('个人日报按日筛选保留成员，重置才恢复全员', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '查看日报')!.trigger('click'); await flushPromises()
    await wrapper.get('[aria-label="考勤日期"]').setValue('2026-10-15'); await flushPromises()
    expect(api.getAttendanceDaily.mock.calls.at(-1)?.[0]).toMatchObject({ user_id: member.user_id, date: '2026-10-15' })
    await wrapper.findAll('button').find(button => button.text() === '重置')!.trigger('click'); await flushPromises()
    expect(api.getAttendanceDaily.mock.calls.at(-1)?.[0]).not.toHaveProperty('user_id')
    expect((wrapper.get('[aria-label="人员"]').element as HTMLInputElement).value).toBe('')
  })
  it('失效任务再次开始生成新幂等键，未知网络结果则保留同一键', async () => {
    const wrapper = render(); await flushPromises()
    api.stepAttendanceSync.mockResolvedValueOnce(run({ status: 'INVALIDATED', can_retry: false, error_message: '配置已变化', etag: 'v2' }))
    await wrapper.get('[data-testid="start-sync"]').trigger('click'); await flushPromises()
    const first = api.startAttendanceSync.mock.calls[0]?.[1]
    api.startAttendanceSync.mockRejectedValueOnce(new Error('network outcome unknown'))
    await wrapper.get('[data-testid="start-sync"]').trigger('click'); await flushPromises()
    const second = api.startAttendanceSync.mock.calls[1]?.[1]
    expect(first).not.toBe(second)
    await wrapper.get('[data-testid="start-sync"]').trigger('click'); await flushPromises()
    expect(api.startAttendanceSync.mock.calls[2]?.[1]).toBe(second)
  })
  it('默认北京时间当月，显示全员未绑定及来源未返回，指标区分人数和行数', async () => {
    const wrapper = render(); await flushPromises()
    expect(api.getAttendanceOverview).toHaveBeenCalledWith('2026-10', expect.any(AbortSignal))
    expect((wrapper.get('[aria-label="考勤月份"]').element as HTMLInputElement).value).toBe('2026-10')
    expect(wrapper.get('[data-testid="attendance-records"]').text()).toContain('未绑定成员甲')
    expect(wrapper.get('[data-testid="attendance-records"]').text()).toContain('未返回')
    expect(wrapper.get('[data-testid="attendance-records"]').text()).not.toContain('0 次')
    expect(wrapper.text()).toContain('256'); expect(wrapper.text()).toContain('2,209')
    expect(wrapper.find('[aria-label="ERP绑定"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('缺失记录不等于 0')
    await wrapper.get('[aria-label="人员"]').setValue('成员甲'); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(api.getAttendanceMonthly.mock.calls.at(-1)?.[0]).not.toHaveProperty('binding')
  })
  it('切换历史月份后，重置读取执行时的北京时间当月并清空历史日期', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.get('[aria-label="考勤月份"]').setValue('2026-09'); await wrapper.get('form').trigger('submit'); await flushPromises()
    expect(api.getAttendanceOverview).toHaveBeenLastCalledWith('2026-09', expect.any(AbortSignal))
    vi.setSystemTime(new Date('2026-10-31T16:10:00Z'))
    await wrapper.findAll('button').find(button => button.text() === '重置')!.trigger('click'); await flushPromises()
    expect(api.getAttendanceOverview).toHaveBeenLastCalledWith('2026-11', expect.any(AbortSignal))
    expect(api.getAttendanceMonthly.mock.calls.at(-1)?.[0]).toMatchObject({ month: '2026-11', page: 1 })
    expect(api.getAttendanceMonthly.mock.calls.at(-1)?.[0]).not.toHaveProperty('date')
  })
  it('统计加载和无成功快照时显示未知，真正返回零值时才显示零', async () => {
    let finish!: (value: AttendanceOverview) => void
    api.getAttendanceOverview.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    api.getAttendanceMonthly.mockResolvedValueOnce(page())
    const wrapper = render(); await flushPromises()
    expect(wrapper.findAll('[data-testid="attendance-stat-value"]').map(item => item.text())).toEqual(['—', '—', '—', '—'])
    const empty = { ...overview(), has_data: false, attendance_members: 0, scanned_members: 0, raw_count: 0, daily_count: 0 }
    finish(empty); await flushPromises()
    expect(wrapper.findAll('[data-testid="attendance-stat-value"]').map(item => item.text())).toEqual(['—', '—', '—', '—'])
    api.getAttendanceOverview.mockResolvedValueOnce({ ...empty, has_data: true, scanned_members: 12 })
    await wrapper.get('[data-testid="refresh"]').trigger('click'); await flushPromises()
    expect(wrapper.findAll('[data-testid="attendance-stat-value"]').map(item => item.text())).toEqual(['0', '0', '0', '12'])
  })
  it('真正请求服务端分页和筛选，日报不发送仅月报适用的记录状态', async () => {
    api.getAttendanceMonthly.mockResolvedValue({ ...page([member]), count: 45 })
    const wrapper = render(); await flushPromises()
    await wrapper.get('[data-testid="next-page"]').trigger('click'); await flushPromises()
    expect(api.getAttendanceMonthly).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }), expect.any(AbortSignal))
    await wrapper.get('[aria-label="记录状态"]').setValue('NOT_RETURNED'); await wrapper.get('form').trigger('submit'); await flushPromises()
    await wrapper.get('[data-testid="tab-daily"]').trigger('click'); await flushPromises()
    expect(api.getAttendanceDaily.mock.calls.at(-1)?.[0]).not.toHaveProperty('status')
    expect(wrapper.get('[aria-label="记录状态"]').attributes('disabled')).toBeDefined()
  })
  it('刷新失败保留同查询旧数据，403清理人员、月历和同步状态', async () => {
    const wrapper = render(); await flushPromises()
    api.getAttendanceMonthly.mockRejectedValueOnce(new Error('offline'))
    await wrapper.get('[data-testid="refresh"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('未绑定成员甲'); expect(wrapper.text()).toContain('上次成功')
    api.getAttendanceMonthly.mockRejectedValueOnce({ response: { status: 403 } })
    await wrapper.get('[data-testid="refresh"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).not.toContain('未绑定成员甲'); expect(wrapper.text()).toContain('无权')
  })
  it('无查看权限不请求数据，授权后加载，撤权后迟到响应不能恢复敏感数据', async () => {
    authorize([])
    const wrapper = render(); await flushPromises()
    expect(api.getAttendanceOverview).not.toHaveBeenCalled()
    let resolve!: (value: ReturnType<typeof page>) => void
    api.getAttendanceMonthly.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    authorize(); await flushPromises(); authorize([]); await flushPromises()
    resolve(page([member])); await flushPromises()
    expect(wrapper.text()).not.toContain('未绑定成员甲'); expect(wrapper.text()).toContain('无权')
  })
  it('月历精确使用UserID，选日同时展示迟到早退和北京时间来源流水', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.get('[aria-label="考勤月份"]').setValue('2026-09'); await wrapper.get('form').trigger('submit'); await flushPromises()
    await wrapper.get('[data-testid="open-calendar"]').trigger('click'); await flushPromises()
    expect(api.getAttendanceCalendar).toHaveBeenCalledWith('2026-09', 'Member.Unbound', expect.any(AbortSignal))
    await wrapper.get('[data-date="2026-09-15"]').trigger('click')
    await wrapper.get('[data-testid="calendar-tab-punches"]').trigger('click')
    const detail = wrapper.get('[data-testid="day-detail"]').text()
    expect(detail).toContain('迟到'); expect(detail).toContain('早退'); expect(detail).toContain('09:12:00'); expect(detail).not.toContain('正常打卡')
    await wrapper.get('[data-date="2026-09-16"]').trigger('click')
    expect(wrapper.get('[data-testid="day-detail"] .detail-pair strong').text()).toBe('未返回')
  })
  it('同步步骤串行且使用每步新版本，暂停后不发下一步，继续先重取版本', async () => {
    let finish!: (value: SyncRun) => void
    api.stepAttendanceSync.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = render(); await flushPromises()
    await wrapper.get('[data-testid="start-sync"]').trigger('click'); await flushPromises()
    expect(api.stepAttendanceSync).toHaveBeenCalledTimes(1)
    expect(api.stepAttendanceSync.mock.calls[0]?.slice(0, 2)).toEqual(['run-1', 'v1'])
    await wrapper.get('[data-testid="pause-sync"]').trigger('click')
    finish(run({ status: 'RUNNING', completed_steps: 1, etag: 'v2' })); await flushPromises()
    expect(api.stepAttendanceSync).toHaveBeenCalledTimes(1)
    api.getAttendanceSync.mockResolvedValueOnce(run({ status: 'RUNNING', completed_steps: 1, etag: 'v2' }))
    await wrapper.get('[data-testid="resume-sync"]').trigger('click'); await flushPromises()
    expect(api.stepAttendanceSync.mock.calls[1]?.slice(0, 2)).toEqual(['run-1', 'v2'])
    expect(wrapper.find('[data-testid="sync-progress"]').exists()).toBe(false)
    expect(messages.success).toHaveBeenCalledWith(expect.stringContaining('同步成功'))
  })
  it('撤销同步权限阻止后续步骤，卸载后当前步骤返回不能继续', async () => {
    let finish!: (value: SyncRun) => void
    api.stepAttendanceSync.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = render(); await flushPromises()
    await wrapper.get('[data-testid="start-sync"]').trigger('click'); await flushPromises()
    authorize(['attendance.view_attendance']); await flushPromises()
    finish(run({ status: 'RUNNING', completed_steps: 1, etag: 'v2' })); await flushPromises()
    expect(api.stepAttendanceSync).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-testid="resume-sync"]').exists()).toBe(false)
    authorize(); await flushPromises()
    api.stepAttendanceSync.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await wrapper.get('[data-testid="start-sync"]').trigger('click'); await flushPromises()
    wrapper.unmount(); wrappers.splice(wrappers.indexOf(wrapper), 1)
    finish(run({ status: 'RUNNING', completed_steps: 2, etag: 'v3' })); await flushPromises()
    expect(api.stepAttendanceSync).toHaveBeenCalledTimes(2)
  })
  it('首次无成功快照不把0当缺勤，同步失败不覆盖已有月报', async () => {
    const wrapper = render(); await flushPromises()
    api.stepAttendanceSync.mockResolvedValueOnce(run({ status: 'FAILED', can_retry: true, error_message: '企微暂不可用', etag: 'v2' }))
    await wrapper.get('[data-testid="start-sync"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('未绑定成员甲'); expect(wrapper.text()).toContain('企微暂不可用')
    expect(wrapper.find('[data-testid="resume-sync"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="sync-progress"]').exists()).toBe(true)
  })
  it('页面初始隐藏历史同步状态，未完成任务仍可从同步入口继续且先读取新版本', async () => {
    api.getAttendanceOverview.mockResolvedValueOnce({ ...overview(), current_run: run({ status: 'RUNNING', completed_steps: 1 }) })
    let finish!: (value: SyncRun) => void
    api.stepAttendanceSync.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    api.getAttendanceSync.mockResolvedValueOnce(run({ status: 'RUNNING', completed_steps: 1, etag: 'fresh-v2' }))
    const wrapper = render(); await flushPromises()
    expect(wrapper.find('[data-testid="sync-progress"]').exists()).toBe(false)
    expect(api.stepAttendanceSync).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="start-sync"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="start-sync"]').trigger('click'); await flushPromises()
    expect(api.startAttendanceSync).not.toHaveBeenCalled()
    expect(api.stepAttendanceSync.mock.calls[0]?.slice(0, 2)).toEqual(['run-1', 'fresh-v2'])
    expect(wrapper.find('[data-testid="sync-progress"]').exists()).toBe(true)
    finish(run({ status: 'SUCCESS', completed_steps: 3, etag: 'fresh-v3' })); await flushPromises()
    expect(wrapper.find('[data-testid="sync-progress"]').exists()).toBe(false)
  })
  it('三类来源表均将成员与账号分列，长部门和异常保留完整内容', async () => {
    const department = '企业 / 生产中心 / 很长的部门路径'
    api.getAttendanceMonthly.mockResolvedValueOnce(page([{ ...member, department_name: department }]))
    api.getAttendanceDaily.mockResolvedValueOnce(page([{ id: 'daily', date: '2026-10-15', user_id: member.user_id, name: member.name, department_name: department, group_name: '规则', schedule_name: '班次', checkin_count: 2, standard_work_sec: 28800, regular_work_sec: 28000, exceptions: [{ type: 1, count: 1 }, { type: 2, count: 1 }] }]))
    api.getAttendanceRaw.mockResolvedValueOnce(page([{ id: 'raw', date: '2026-10-15', user_id: member.user_id, name: member.name, department_name: department, checkin_time: '2026-10-15T01:00:00Z', checkin_type: '上班打卡', group_name: '规则', exceptions: ['迟到', '地点异常'] }]))
    const wrapper = render(); await flushPromises()
    for (const kind of ['monthly', 'daily', 'raw']) {
      await wrapper.get(`[data-testid="tab-${kind}"]`).trigger('click'); await flushPromises()
      expect(wrapper.findAll('thead th').slice(0, 3).map(cell => cell.text())).toEqual(['成员', '企业微信账号', '部门'])
      expect(wrapper.findAll('tbody tr')[0]?.findAll('td').slice(0, 2).map(cell => cell.text())).toEqual([member.name, member.user_id])
      expect(wrapper.findAll('tbody tr')[0]?.findAll('td')[2]?.attributes('title')).toBe(department)
    }
  })
})
