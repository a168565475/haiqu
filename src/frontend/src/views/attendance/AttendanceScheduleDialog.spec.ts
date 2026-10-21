import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import AttendanceScheduleDialog from './AttendanceScheduleDialog.vue'

const api = vi.hoisted(() => ({ getAttendanceSchedule: vi.fn(), saveAttendanceSchedule: vi.fn(), getAttendanceRules: vi.fn() }))
vi.mock('@/api/attendance', async original => ({ ...await original<object>(), ...api }))
const days = Array.from({ length: 30 }, (_, i) => ({ date: `2026-09-${String(i + 1).padStart(2, '0')}`, kind: 'UNSET', periods: [] as { start_sec: number; end_sec: number }[] }))
function schedule() { return { month: '2026-09', configured: false, days: structuredClone(days), source: null, import_token: null, etag: 'schedule-v0' } }
const ruleDays = days.map(day => ({ ...day, kind: day.date === '2026-09-06' ? 'REST' : 'WORK', periods: day.date === '2026-09-06' ? [] : [{ start_sec: 28800, end_sec: 61200 }] }))
const rule = { id: 7, name: '接口返回的固定规则', type: 1, can_import: true, reason: '', days: ruleDays, warnings: ['当前规则不能证明历史月份排班。'], import_token: 'signed-source-token' }
const wrappers: ReturnType<typeof mount>[] = []
function authorize(permissions = ['attendance.view_attendance', 'attendance.manage_schedule']) {
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'editor', display_name: '管理员', is_superuser: false, employee: { id: 'editor', employee_code: 'EDITOR', display_name: '管理员', status: 'ACTIVE' }, permissions, data_scope: 'ALL' } })
}
function render() {
  const wrapper = mount(AttendanceScheduleDialog, { props: { modelValue: true, month: '2026-09' }, global: { stubs: { AppWindowDialog: { props: ['modelValue'], template: '<section v-if="modelValue"><slot /><slot name="footer" /></section>' } } } })
  wrappers.push(wrapper); return wrapper
}
function pending<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
beforeEach(() => {
  vi.resetAllMocks(); setActivePinia(createPinia()); authorize()
  api.getAttendanceSchedule.mockResolvedValue(schedule()); api.getAttendanceRules.mockResolvedValue({ rules: [rule], fetched_at: '2026-10-19T00:00:00Z' })
  api.saveAttendanceSchedule.mockResolvedValue({ ...schedule(), configured: true, etag: 'schedule-v1' })
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })

describe('全员月度安排', () => {
  it('首次不预填上下班或星期，不读取外部规则，不自动保存', async () => {
    const wrapper = render(); await flushPromises()
    expect(api.getAttendanceSchedule).toHaveBeenCalledWith('2026-09')
    expect((wrapper.get('[aria-label="统一上班时间"]').element as HTMLInputElement).value).toBe('')
    expect(wrapper.findAll('input[type="checkbox"]:checked')).toHaveLength(0)
    expect(api.getAttendanceRules).not.toHaveBeenCalled(); expect(api.saveAttendanceSchedule).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('全员统一'); expect(wrapper.text()).toContain('不重算')
  })
  it('当前规则由用户读取选择，应用只改草稿，取消后重开丢弃草稿', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.get('[data-testid="read-rules"]').trigger('click'); await flushPromises()
    expect((wrapper.get('[aria-label="企业微信当前规则"]').element as HTMLSelectElement).value).toBe('')
    await wrapper.get('[aria-label="企业微信当前规则"]').setValue('7')
    await wrapper.get('[data-testid="apply-rule"]').trigger('click')
    expect(wrapper.get('[data-schedule-date="2026-09-06"]').text()).toContain('休息')
    expect(api.saveAttendanceSchedule).not.toHaveBeenCalled()
    await wrapper.get('[data-testid="cancel-schedule"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([false])
    await wrapper.setProps({ modelValue: false }); await wrapper.setProps({ modelValue: true }); await flushPromises()
    expect(wrapper.get('[data-schedule-date="2026-09-06"]').text()).toContain('未设置')
  })
  it('全月明确休息且来源token与ETag提交，成功由真实响应决定', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.get('[data-testid="read-rules"]').trigger('click'); await flushPromises()
    await wrapper.get('[aria-label="企业微信当前规则"]').setValue('7'); await wrapper.get('[data-testid="apply-rule"]').trigger('click')
    await wrapper.get('[data-testid="save-schedule"]').trigger('click'); await flushPromises()
    expect(api.saveAttendanceSchedule.mock.calls[0]?.slice(0, 3)).toEqual(['2026-09', { days: ruleDays, import_token: 'signed-source-token' }, 'schedule-v0'])
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })
  it('上下班颠倒或跨日不能生成工作日，明确星期后才改整月', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.get('[aria-label="周一工作"]').setValue(true)
    await wrapper.get('[aria-label="统一上班时间"]').setValue('18:00'); await wrapper.get('[aria-label="统一下班时间"]').setValue('08:00')
    await wrapper.get('[data-testid="apply-month"]').trigger('click')
    expect(wrapper.text()).toContain('下班时间必须晚于上班时间')
    await wrapper.get('[aria-label="统一上班时间"]').setValue('08:00'); await wrapper.get('[aria-label="统一下班时间"]').setValue('17:00')
    await wrapper.get('[data-testid="apply-month"]').trigger('click')
    expect(wrapper.get('[data-schedule-date="2026-09-07"]').text()).toContain('工作')
    expect(wrapper.get('[data-schedule-date="2026-09-08"]').text()).toContain('休息')
  })
  it('月历按周一开头，选择与方向键只切换右侧单日调整', async () => {
    const wrapper = render(); await flushPromises()
    expect(wrapper.attributes('width')).toBe('1040')
    expect(wrapper.findAll('.weekdays span')).toHaveLength(7)
    expect(wrapper.get('.calendar-grid').element.children).toHaveLength(31)
    await wrapper.get('[data-schedule-date="2026-09-06"]').trigger('click')
    expect(wrapper.get('[data-testid="day-adjustment"]').text()).toContain('2026-09-06')
    await wrapper.get('[data-schedule-date="2026-09-06"]').trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.get('[data-testid="day-adjustment"]').text()).toContain('2026-09-13')
    await wrapper.get('[data-testid="day-rest"]').trigger('click')
    expect(wrapper.get('[data-schedule-date="2026-09-13"]').text()).toContain('休息')
    expect(wrapper.get('[data-schedule-date="2026-09-06"]').text()).toContain('未设置')
  })
  it('导入规则后的逐日调整保留来源，整月手动生成清空来源', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.get('[data-testid="read-rules"]').trigger('click'); await flushPromises()
    await wrapper.get('[aria-label="企业微信当前规则"]').setValue('7'); await wrapper.get('[data-testid="apply-rule"]').trigger('click')
    await wrapper.get('[data-testid="day-rest"]').trigger('click')
    await wrapper.get('[data-testid="save-schedule"]').trigger('click'); await flushPromises()
    expect(api.saveAttendanceSchedule.mock.calls[0]?.[1].import_token).toBe('signed-source-token')
    await wrapper.setProps({ modelValue: false }); await wrapper.setProps({ modelValue: true }); await flushPromises()
    await wrapper.get('[aria-label="统一上班时间"]').setValue('08:00'); await wrapper.get('[aria-label="统一下班时间"]').setValue('17:00')
    await wrapper.get('[aria-label="周一工作"]').setValue(true); await wrapper.get('[data-testid="apply-month"]').trigger('click')
    await wrapper.get('[data-testid="save-schedule"]').trigger('click'); await flushPromises()
    expect(api.saveAttendanceSchedule.mock.calls[1]?.[1].import_token).toBeNull()
  })
  it('单日允许多段且保留来源工作时段，重叠时不发送保存', async () => {
    const data = schedule(); data.days[0] = { date: '2026-09-01', kind: 'WORK', periods: [{ start_sec: 28800, end_sec: 43200 }, { start_sec: 46800, end_sec: 61200 }] }
    api.getAttendanceSchedule.mockResolvedValueOnce(data)
    const wrapper = render(); await flushPromises()
    expect(wrapper.findAll('[data-testid="period-row"]')).toHaveLength(2)
    await wrapper.get('[aria-label="第2段上班时间"]').setValue('11:00')
    await wrapper.get('[data-testid="save-schedule"]').trigger('click'); await flushPromises()
    expect(api.saveAttendanceSchedule).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('重叠')
  })
  it('编辑后的不重叠时段按开始时间提交，日期顺序保持不变', async () => {
    const data = schedule(); data.days[0] = { date: '2026-09-01', kind: 'WORK', periods: [{ start_sec: 28800, end_sec: 43200 }, { start_sec: 46800, end_sec: 61200 }] }
    api.getAttendanceSchedule.mockResolvedValueOnce(data)
    const wrapper = render(); await flushPromises()
    await wrapper.get('[aria-label="第1段上班时间"]').setValue('18:00')
    await wrapper.get('[aria-label="第1段下班时间"]').setValue('20:00')
    await wrapper.get('[data-testid="save-schedule"]').trigger('click'); await flushPromises()
    const submitted = api.saveAttendanceSchedule.mock.calls[0]?.[1].days
    expect(submitted[0].periods).toEqual([{ start_sec: 46800, end_sec: 61200 }, { start_sec: 64800, end_sec: 72000 }])
    expect(submitted.map((day: { date: string }) => day.date)).toEqual(days.map(day => day.date))
    expect(wrapper.emitted('saved')).toHaveLength(1)
  })
  it('清空单日时间后不能用原值保存，补全后才允许提交', async () => {
    const data = schedule(); data.days[0] = { date: '2026-09-01', kind: 'WORK', periods: [{ start_sec: 28800, end_sec: 61200 }] }
    api.getAttendanceSchedule.mockResolvedValueOnce(data)
    const wrapper = render(); await flushPromises()
    await wrapper.get('[aria-label="第1段上班时间"]').setValue('')
    await wrapper.get('[data-testid="save-schedule"]').trigger('click'); await flushPromises()
    expect(api.saveAttendanceSchedule).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('补全')
    await wrapper.get('[aria-label="第1段上班时间"]').setValue('08:30')
    await wrapper.get('[data-testid="save-schedule"]').trigger('click'); await flushPromises()
    expect(api.saveAttendanceSchedule.mock.calls[0]?.[1].days[0].periods[0].start_sec).toBe(30600)
  })
  it('版本冲突保留编辑且禁止继续覆盖；撤权后清理并拒绝迟到加载', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.get('[data-testid="day-rest"]').trigger('click')
    api.saveAttendanceSchedule.mockRejectedValueOnce({ response: { status: 412 } })
    await wrapper.get('[data-testid="save-schedule"]').trigger('click'); await flushPromises()
    expect(wrapper.get('[data-schedule-date="2026-09-01"]').text()).toContain('休息')
    expect(wrapper.get('[data-testid="save-schedule"]').attributes('disabled')).toBeDefined()
    authorize(['attendance.view_attendance']); await flushPromises()
    expect(wrapper.find('[data-schedule-date="2026-09-01"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('无权')
  })
  it('撤权后迟到的月度加载不能恢复数据，重新授权重新读取', async () => {
    const oldLoad = pending<ReturnType<typeof schedule>>()
    api.getAttendanceSchedule.mockReturnValueOnce(oldLoad.promise)
    const wrapper = render(); await flushPromises()
    authorize(['attendance.view_attendance']); await flushPromises()
    const old = schedule(); old.days[0]!.kind = 'REST'; oldLoad.resolve(old); await flushPromises()
    expect(wrapper.find('[data-schedule-date]').exists()).toBe(false)
    authorize(); await flushPromises()
    expect(api.getAttendanceSchedule).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-schedule-date="2026-09-01"]').text()).toContain('未设置')
  })
  it('关闭后迟到的规则读取不能进入重新打开的草稿', async () => {
    const oldRules = pending<{ rules: typeof rule[]; fetched_at: string }>()
    api.getAttendanceRules.mockReturnValueOnce(oldRules.promise)
    const wrapper = render(); await flushPromises()
    await wrapper.get('[data-testid="read-rules"]').trigger('click')
    await wrapper.setProps({ modelValue: false }); await wrapper.setProps({ modelValue: true }); await flushPromises()
    oldRules.resolve({ rules: [rule], fetched_at: '2026-10-19T00:00:00Z' }); await flushPromises()
    expect(wrapper.findAll('[aria-label="企业微信当前规则"] option')).toHaveLength(1)
  })
  it('切换月份后旧保存响应不能关闭新草稿或发出成功事件', async () => {
    const oldSave = pending<ReturnType<typeof schedule>>()
    api.saveAttendanceSchedule.mockReturnValueOnce(oldSave.promise)
    const wrapper = render(); await flushPromises()
    await wrapper.get('[data-testid="save-schedule"]').trigger('click')
    api.getAttendanceSchedule.mockResolvedValueOnce({ ...schedule(), month: '2026-10', days: [] })
    await wrapper.setProps({ month: '2026-10' }); await flushPromises()
    oldSave.resolve(schedule()); await flushPromises()
    expect(wrapper.emitted('saved')).toBeUndefined()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(wrapper.text()).toContain('2026-10 · 全员统一')
    expect(wrapper.find('[data-schedule-date]').exists()).toBe(false)
  })
  it('关闭后重新打开清空未保存的统一时间和星期', async () => {
    const wrapper = render(); await flushPromises()
    await wrapper.get('[aria-label="统一上班时间"]').setValue('08:00')
    await wrapper.get('[aria-label="周一工作"]').setValue(true)
    await wrapper.setProps({ modelValue: false }); await wrapper.setProps({ modelValue: true }); await flushPromises()
    expect((wrapper.get('[aria-label="统一上班时间"]').element as HTMLInputElement).value).toBe('')
    expect(wrapper.findAll('input[type="checkbox"]:checked')).toHaveLength(0)
  })
})
