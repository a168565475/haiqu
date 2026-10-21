import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import type { AbsenceItem, AttendanceCalendar, AttendanceVacation, CalendarDay } from '@/types/attendance'
import AttendanceCalendarDialog from './AttendanceCalendarDialog.vue'

const api = vi.hoisted(() => ({ getAttendanceCalendar: vi.fn(), getAttendanceVacation: vi.fn() }))
vi.mock('@/api/attendance', async original => ({ ...await original<object>(), ...api }))
const absence = (overrides: Partial<AbsenceItem> = {}): AbsenceItem => ({ type: 1, vacation_id: 2, name: '年假', count: 1, duration: 43200, time_type: 0, ...overrides })
const day = (overrides: Partial<CalendarDay> = {}): CalendarDay => ({ date: '2026-09-15', report_returned: true, checkin_count: 2, states: ['late', 'early'], exceptions: [{ type: 1, count: 1 }, { type: 2, count: 1 }], raw: [], schedule: null, source_summaries: [{ record_id: 'source-1', sp_items: [absence(), absence({ type: 2, vacation_id: null, name: '补卡', duration: null })], ot_info: null }], ...overrides })
const calendar = (days = [day()], user = 'Member.Unbound'): AttendanceCalendar => ({ month: '2026-09', user_id: user, name: user === 'Member.Unbound' ? '未绑定成员甲' : '成员乙', days })
const balance = (user = 'Member.Unbound'): AttendanceVacation => ({ user_id: user, fetched_at: '2026-10-20T02:30:00Z', is_current: true, items: [{ id: 2, name: '年假', time_attr: 0, duration_type: 1, quota_type: 1, perday_duration: 28800, assignduration: 259200, real_assignduration: 259200, usedduration: 43200, leftduration: 216000 }, { id: 3, name: '不限额假', time_attr: 0, duration_type: 1, quota_type: 0, perday_duration: 28800, assignduration: 0, real_assignduration: 0, usedduration: 0, leftduration: 0 }] })
const wrappers: ReturnType<typeof mount>[] = []
function authorize(permissions = ['attendance.view_attendance']) {
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true, employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions, data_scope: 'ALL' } })
}
function render() {
  const wrapper = mount(AttendanceCalendarDialog, { props: { modelValue: true, month: '2026-09', userId: 'Member.Unbound', name: '未绑定成员甲', people: [{ user_id: 'Other.User', name: '成员乙' }] as never }, global: { stubs: { AppWindowDialog: { props: ['modelValue'], template: '<section v-if="modelValue" role="dialog"><slot /><slot name="footer" /></section>' } } } })
  wrappers.push(wrapper); return wrapper
}
beforeEach(() => { vi.clearAllMocks(); setActivePinia(createPinia()); authorize(); api.getAttendanceCalendar.mockResolvedValue(calendar()); api.getAttendanceVacation.mockResolvedValue(balance()) })
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('个人月历假勤与当前余额', () => {
  it('月格新增假勤标识且保留多异常，默认假勤详情且提示折叠', async () => {
    const wrapper = render(); await flushPromises()
    const cell = wrapper.get('[data-date="2026-09-15"]')
    expect(cell.text()).toContain('迟到'); expect(cell.text()).toContain('早退'); expect(cell.text()).toContain('请假'); expect(cell.text()).toContain('补卡')
    await cell.trigger('click')
    expect(wrapper.get('[data-testid="absence-detail"]').text()).toContain('0.5 天')
    expect(wrapper.get('[data-testid="absence-detail"]').text()).not.toContain('审批单号')
    expect(wrapper.get('.operation-note').attributes('open')).toBeUndefined()
    expect(api.getAttendanceVacation).not.toHaveBeenCalled()
  })
  it('多日报逐条展示，重复来源项不相加并提示核对，零项不点亮月格', async () => {
    api.getAttendanceCalendar.mockResolvedValueOnce(calendar([day({ source_summaries: [{ record_id: 'one', sp_items: [absence(), absence({ duration: 86400 })], ot_info: { ot_status: 1, ot_duration: 3600 } }, { record_id: 'two', sp_items: [absence({ duration: 7200, time_type: 1 })], ot_info: null }] }), day({ date: '2026-09-16', states: ['unknown'], source_summaries: [{ record_id: 'zero', sp_items: [absence({ count: 0, duration: 0 })], ot_info: { ot_status: 0, ot_duration: 0 } }] })]))
    const wrapper = render(); await flushPromises(); await wrapper.get('[data-date="2026-09-15"]').trigger('click')
    expect(wrapper.findAll('[data-testid="absence-source"]')).toHaveLength(2)
    expect(wrapper.findAll('[data-testid="absence-item"]')).toHaveLength(3)
    expect(wrapper.get('[data-testid="absence-detail"]').text()).toContain('重复统计项，待核对')
    expect(wrapper.get('[data-testid="absence-detail"]').text()).toContain('0.5 天'); expect(wrapper.get('[data-testid="absence-detail"]').text()).toContain('2 小时')
    expect(wrapper.get('[data-testid="absence-detail"]').text()).toContain('来源单位待核实')
    expect(wrapper.get('[data-date="2026-09-16"]').find('.day-events').text()).toBe('')
    await wrapper.get('[data-date="2026-09-16"]').trigger('click')
    expect(wrapper.get('[data-testid="absence-detail"]').text()).toContain('0 天')
  })
  it('旧快照缺字段与明确空统计分别提示，原打卡详情继续可用', async () => {
    api.getAttendanceCalendar.mockResolvedValueOnce(calendar([day({ source_summaries: undefined }), day({ date: '2026-09-16', source_summaries: [{ record_id: 'empty', sp_items: [], ot_info: null }] })]))
    const wrapper = render(); await flushPromises(); await wrapper.get('[data-date="2026-09-15"]').trigger('click')
    expect(wrapper.get('[data-testid="absence-detail"]').text()).toContain('该快照未采集或未返回假勤来源')
    await wrapper.get('[data-testid="calendar-tab-punches"]').trigger('click')
    expect(wrapper.get('[data-testid="punch-detail"]').text()).toContain('迟到：1 次')
    await wrapper.get('[data-date="2026-09-16"]').trigger('click'); await wrapper.get('[data-testid="calendar-tab-absence"]').trigger('click')
    expect(wrapper.get('[data-testid="absence-detail"]').text()).toContain('来源返回空统计项')
  })
  it('来源明确加班缺时长仍标加班，不把未知原值换算成小时', async () => {
    api.getAttendanceCalendar.mockResolvedValueOnce(calendar([day({ source_summaries: [{ record_id: 'short', sp_items: [], ot_info: { ot_status: 2, ot_duration: 0, exception_duration: [120, 240] } }] })]))
    const wrapper = render(); await flushPromises(); await wrapper.get('[data-date="2026-09-15"]').trigger('click')
    expect(wrapper.get('[data-date="2026-09-15"] .day-events').text()).toBe('加班')
    const detail = wrapper.get('[data-testid="absence-detail"]').text()
    expect(detail).toContain('加班缺时长'); expect(detail).toContain('120、240（来源单位待核实）'); expect(detail).not.toContain('小时')
  })
  it('余额按需读取，只标当前读取时间，未绑定成员也可查看且收起后保留摘要', async () => {
    const wrapper = render(); await flushPromises(); await wrapper.get('[data-testid="toggle-vacation"]').trigger('click'); await flushPromises()
    expect(api.getAttendanceVacation).toHaveBeenCalledWith('2026-09', 'Member.Unbound', expect.any(AbortSignal))
    expect(wrapper.get('[data-testid="vacation-detail"]').text()).toContain('2026-10-20 10:30:00')
    expect(wrapper.get('[data-testid="vacation-detail"]').text()).toContain('不是所选历史月份')
    expect(wrapper.get('[data-testid="vacation-detail"]').text()).toContain('2.5 天')
    expect(wrapper.get('[data-testid="vacation-detail"]').text()).toContain('不限额')
    await wrapper.get('[data-testid="toggle-vacation"]').trigger('click')
    expect(wrapper.find('[data-testid="vacation-detail"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="vacation-summary"]').text()).toContain('2.5 天')
    expect(api.getAttendanceVacation).toHaveBeenCalledTimes(1)
  })
  it('余额读取失败不清空月历，重读失败保留同成员上次结果', async () => {
    api.getAttendanceVacation.mockRejectedValueOnce({ response: { status: 502 } })
    const wrapper = render(); await flushPromises(); await wrapper.get('[data-testid="toggle-vacation"]').trigger('click'); await flushPromises()
    expect(wrapper.get('[data-testid="vacation-error"]').text()).toContain('审批接口')
    expect(wrapper.find('[data-date="2026-09-15"]').exists()).toBe(true)
    await wrapper.get('[data-testid="refresh-vacation"]').trigger('click'); await flushPromises()
    api.getAttendanceVacation.mockRejectedValueOnce(new Error('offline'))
    await wrapper.get('[data-testid="refresh-vacation"]').trigger('click'); await flushPromises()
    expect(wrapper.get('[data-testid="vacation-detail"]').text()).toContain('2.5 天')
    expect(wrapper.get('[data-testid="vacation-error"]').text()).toContain('保留上次读取')
  })
  it.each([
    ['企业微信应用未启用或配置不完整，请联系管理员。', '企业微信应用未启用或配置不完整，请联系管理员。'],
    ['读取期间企业微信配置已变化，请重新查询。', '读取期间企业微信配置已变化，请重新查询。'],
    ['读取期间考勤快照已更新，请重新查询。', '读取期间考勤快照已更新，请重新查询。'],
    ['未知上游错误，可能包含敏感内容', '当前假期余额暂无法读取，请重新查询；若持续失败，请联系管理员核对配置。'],
  ])('余额409仅展示已知安全冲突：%s', async (message, expected) => {
    api.getAttendanceVacation.mockRejectedValueOnce({ isAxiosError: true, response: { status: 409, data: { error: { code: 'CONFLICT', message } } } })
    const wrapper = render(); await flushPromises(); await wrapper.get('[data-testid="toggle-vacation"]').trigger('click'); await flushPromises()
    const feedback = wrapper.get('[data-testid="vacation-error"]').text()
    expect(feedback).toBe(expected)
    expect(feedback).not.toContain('同步进度'); expect(feedback).not.toContain('未知上游错误')
    expect(wrapper.find('[data-date="2026-09-15"]').exists()).toBe(true)
  })
  it('切人/换月清余额并阻止迟到响应，不能把他人的余额恢复回来', async () => {
    let finish!: (value: AttendanceVacation) => void
    api.getAttendanceVacation.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = render(); await flushPromises(); await wrapper.get('[data-testid="toggle-vacation"]').trigger('click'); await flushPromises()
    const signal = api.getAttendanceVacation.mock.calls[0]?.[2] as AbortSignal
    api.getAttendanceCalendar.mockResolvedValueOnce(calendar([day()], 'Other.User'))
    await wrapper.get('[aria-label="月历人员"]').setValue('Other.User'); await flushPromises(); finish(balance()); await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(wrapper.get('[data-testid="vacation-summary"]').text()).not.toContain('2.5 天')
    expect(wrapper.find('[data-testid="vacation-detail"]').exists()).toBe(false)
    api.getAttendanceVacation.mockResolvedValueOnce(balance('Other.User'))
    await wrapper.get('[data-testid="toggle-vacation"]').trigger('click'); await flushPromises()
    expect(api.getAttendanceVacation.mock.calls.at(-1)?.slice(0, 2)).toEqual(['2026-09', 'Other.User'])
    await wrapper.get('[aria-label="月历月份"]').setValue('2026-08'); await flushPromises()
    expect(wrapper.find('[data-testid="vacation-detail"]').exists()).toBe(false)
  })
  it('权限撤销或关闭中断余额，迟到响应不能恢复敏感状态', async () => {
    let finish!: (value: AttendanceVacation) => void
    api.getAttendanceVacation.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = render(); await flushPromises(); await wrapper.get('[data-testid="toggle-vacation"]').trigger('click'); await flushPromises()
    const signal = api.getAttendanceVacation.mock.calls[0]?.[2] as AbortSignal
    authorize([]); await flushPromises(); finish(balance()); await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(wrapper.text()).not.toContain('2.5 天'); expect(wrapper.text()).not.toContain('未绑定成员甲')
    authorize(); await flushPromises(); api.getAttendanceVacation.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await wrapper.get('[data-testid="toggle-vacation"]').trigger('click'); await flushPromises()
    await wrapper.setProps({ modelValue: false }); finish(balance()); await flushPromises()
    expect(wrapper.text()).not.toContain('2.5 天')
  })
  it('服务端拒绝余额权限时清空月历和余额并通知父页', async () => {
    api.getAttendanceVacation.mockRejectedValueOnce({ response: { status: 403 } })
    const wrapper = render(); await flushPromises(); await wrapper.get('[data-testid="toggle-vacation"]').trigger('click'); await flushPromises()
    expect(wrapper.emitted('forbidden')).toHaveLength(1)
    expect(wrapper.find('[data-date="2026-09-15"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="vacation-detail"]').exists()).toBe(false)
  })
  it('余额明确空列表不冒充请求失败，卸载会取消正在进行的刷新', async () => {
    api.getAttendanceVacation.mockResolvedValueOnce({ ...balance(), items: [] })
    const wrapper = render(); await flushPromises(); await wrapper.get('[data-testid="toggle-vacation"]').trigger('click'); await flushPromises()
    expect(wrapper.get('[data-testid="vacation-detail"]').text()).toContain('来源返回空列表')
    expect(wrapper.find('[data-testid="vacation-error"]').exists()).toBe(false)
    let finish!: (value: AttendanceVacation) => void
    api.getAttendanceVacation.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await wrapper.get('[data-testid="refresh-vacation"]').trigger('click'); await flushPromises()
    const signal = api.getAttendanceVacation.mock.calls.at(-1)?.[2] as AbortSignal
    wrapper.unmount(); expect(signal.aborted).toBe(true); finish(balance()); await flushPromises()
  })
})
