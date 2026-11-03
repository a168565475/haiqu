import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'
import ElementPlus, { ElMessage, ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import type { CodexConnectionSnapshot } from '@/types/codexConnection'
import CodexConnectionSettingsView from './CodexConnectionSettingsView.vue'

const api = vi.hoisted(() => ({ get: vi.fn(), action: vi.fn(), save: vi.fn(), challenge: vi.fn() }))
vi.mock('@/api/codexConnection', async importOriginal => ({ ...await importOriginal<typeof import('@/api/codexConnection')>(),
  getCodexConnection: api.get, runCodexConnectionAction: api.action, saveCodexModel: api.save, getCodexLoginChallenge: api.challenge }))
const operationId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const employeeId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
const snapshot = (changes: Partial<CodexConnectionSnapshot> = {}): CodexConnectionSnapshot => ({
  config_generation: 1, status: 'DISCONNECTED', selected_model: 'model-a', cli_version: '0.165.0', account: null,
  models: [{ id: 'model-a', display_name: '模型 A' }, { id: 'model-b', display_name: '模型 B' }],
  rate_limits: null, limits_updated_at: null, last_checked_at: null, last_test_at: null, error_code: '', paused: true, operation: null, ...changes,
})
const pending = () => snapshot({ status: 'LOGIN_PENDING', operation: { id: operationId, action: 'login', state: 'RUNNING', actor_id: employeeId, can_cancel: true } })
const response = (value = snapshot()) => ({ data: value, etag: '"v1"' })
const challenge = () => ({ operation_id: operationId, verification_url: 'https://auth.openai.com/device', user_code: 'TEST-CODE', expires_at: new Date(Date.now() + 60_000).toISOString() })
const wrappers: ReturnType<typeof mount>[] = []
async function render() {
  const wrapper = mount(CodexConnectionSettingsView, { props: { embedded: true }, global: { plugins: [ElementPlus] } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks(); setActivePinia(createPinia())
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true,
    employee: { id: employeeId, employee_code: 'TEST', display_name: '测试管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  api.get.mockResolvedValue(response()); api.action.mockResolvedValue(response()); api.save.mockResolvedValue(response()); api.challenge.mockResolvedValue(challenge())
  vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks() })

describe('Codex连接设置', () => {
  it('无管理权限不请求账号或展示操作', async () => {
    useAuthStore().user!.is_superuser = false
    const wrapper = await render()
    expect(wrapper.text()).toContain('无权管理')
    expect(api.get).not.toHaveBeenCalled(); expect(wrapper.find('[data-action="login"]').exists()).toBe(false)
  })
  it('缺少套餐和额度显示未知，已连接不宣称模型测试通过，静止状态不轮询', async () => {
    api.get.mockResolvedValue(response(snapshot({ status: 'CONNECTED', account: { display_name: 't***@example.test', plan_type: null } })))
    const wrapper = await render()
    expect(wrapper.text()).toContain('模型尚未验证'); expect(wrapper.text()).toContain('使用限额：未知')
    expect(wrapper.text()).not.toContain('已用 0%'); expect(wrapper.text()).not.toContain('最小测试通过')
    await vi.advanceTimersByTimeAsync(6000); expect(api.get).toHaveBeenCalledTimes(1)
  })
  it('官方额度明确为零时显示零，未知窗口值保持未知', async () => {
    api.get.mockResolvedValue(response(snapshot({ rate_limits: { windows: [{ name: '短期', used_percent: 0, window_minutes: null, resets_at: null }], credits: { unlimited: false, has_credits: false, balance: '0' } } })))
    const wrapper = await render()
    expect(wrapper.text()).toContain('已用 0%'); expect(wrapper.text()).toContain('窗口 未知'); expect(wrapper.text()).toContain('额外额度：0')
  })
  it('授权中展示本人的码、禁用重复登录，取消后清除码并停止轮询', async () => {
    api.get.mockResolvedValue(response(pending()))
    const wrapper = await render()
    expect(wrapper.text()).toContain('TEST-CODE'); expect(wrapper.get('[data-action="login"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('a').attributes('rel')).toBe('noopener noreferrer')
    api.action.mockResolvedValue(response()); api.get.mockResolvedValue(response())
    await wrapper.get('[data-action="cancel"]').trigger('click'); await flushPromises()
    expect(api.action).toHaveBeenCalledWith('login-cancel', '"v1"', operationId)
    expect(wrapper.text()).not.toContain('TEST-CODE')
    const count = api.get.mock.calls.length; await vi.advanceTimersByTimeAsync(5000); expect(api.get).toHaveBeenCalledTimes(count)
  })
  it('其他管理员不能读取验证码或取消授权', async () => {
    const value = pending(); value.operation!.actor_id = 'other-employee'; value.operation!.can_cancel = false
    api.get.mockResolvedValue(response(value))
    const wrapper = await render()
    expect(api.challenge).not.toHaveBeenCalled(); expect(wrapper.find('[data-action="cancel"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('其他管理员发起')
  })
  it('授权信息409继续读取；本地展示结束后隐藏码并轮询至真实成功', async () => {
    api.get.mockResolvedValue(response(pending()))
    api.challenge.mockRejectedValueOnce(new AxiosError('pending', undefined, undefined, undefined, { status: 409 } as never))
    const wrapper = await render()
    expect(wrapper.find('[data-testid="authorization"]').exists()).toBe(false)
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(wrapper.text()).toContain('TEST-CODE')
    expect(wrapper.text()).toContain('本地展示截止')
    expect(wrapper.text()).not.toContain('有效期至')
    await vi.advanceTimersByTimeAsync(60_000); await flushPromises()
    expect(wrapper.text()).not.toContain('TEST-CODE'); expect(wrapper.text()).toContain('本地展示已结束')
    expect(wrapper.text()).toContain('仍在等待官方完成状态'); expect(wrapper.text()).not.toContain('已过期')
    expect(wrapper.get('[data-action="cancel"]').attributes('disabled')).toBeUndefined()
    const reads = api.get.mock.calls.length, challenges = api.challenge.mock.calls.length
    await vi.advanceTimersByTimeAsync(6000); await flushPromises()
    expect(api.get.mock.calls.length).toBeGreaterThan(reads); expect(api.challenge).toHaveBeenCalledTimes(challenges)
    expect(api.action).not.toHaveBeenCalled()
    api.get.mockResolvedValue(response(snapshot({ status: 'CONNECTED', account: { display_name: 't***', plan_type: null } })))
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(wrapper.text()).toContain('已连接，模型尚未验证'); expect(wrapper.text()).not.toContain('本地展示已结束')
    const completedReads = api.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(6000); expect(api.get).toHaveBeenCalledTimes(completedReads)
  })
  it('迟到授权响应已过本地截止时不显示码，仅按服务器终态结束等待', async () => {
    api.get.mockResolvedValue(response(pending()))
    api.challenge.mockResolvedValue({ ...challenge(), expires_at: new Date(Date.now() - 1000).toISOString() })
    const wrapper = await render()
    expect(wrapper.text()).not.toContain('TEST-CODE'); expect(wrapper.text()).toContain('本地展示已结束')
    expect(wrapper.text()).not.toContain('已过期'); expect(wrapper.text()).not.toContain('连接异常')
    api.get.mockResolvedValue(response(snapshot({ status: 'ERROR', error_code: 'TIMEOUT' })))
    await vi.advanceTimersByTimeAsync(2000); await flushPromises()
    expect(wrapper.text()).toContain('连接异常'); expect(wrapper.text()).not.toContain('仍在等待官方完成状态')
    expect(api.action).not.toHaveBeenCalled()
    const reads = api.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(6000); expect(api.get).toHaveBeenCalledTimes(reads)
  })
  it('卸载停止轮询并忽略迟到的授权码', async () => {
    let finish!: (value: ReturnType<typeof challenge>) => void
    api.get.mockResolvedValue(response(pending())); api.challenge.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await render()
    wrapper.unmount(); wrappers.splice(wrappers.indexOf(wrapper), 1)
    finish(challenge()); await flushPromises(); await vi.advanceTimersByTimeAsync(6000)
    expect(api.get).toHaveBeenCalledTimes(1); expect(vi.getTimerCount()).toBe(0)
  })
  it('ERP身份变化立即清除授权码，旧挑战响应不能落到新身份', async () => {
    let finish!: (value: ReturnType<typeof challenge>) => void
    api.get.mockResolvedValue(response(pending())); api.challenge.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await render()
    useAuthStore().clearAuthentication(); await flushPromises(); finish(challenge()); await flushPromises()
    expect(wrapper.text()).not.toContain('TEST-CODE'); expect(wrapper.text()).toContain('无权管理')
    await vi.advanceTimersByTimeAsync(6000); expect(api.get).toHaveBeenCalledTimes(1)
  })
  it('关闭清理后若父级取消离开，页面仍可重新读取且不显示旧授权码', async () => {
    api.get.mockResolvedValue(response(pending()))
    const wrapper = await render()
    expect(wrapper.text()).toContain('TEST-CODE')
    let finish!: (value: ReturnType<typeof response>) => void
    api.get.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await vi.advanceTimersByTimeAsync(2000)
    expect(wrapper.vm.canClose()).toBe(true)
    await flushPromises()
    expect(wrapper.text()).not.toContain('TEST-CODE')
    expect(wrapper.get('[data-action="read"]').attributes('disabled')).toBeUndefined()
    finish(response(pending())); await flushPromises()
    expect(wrapper.text()).not.toContain('TEST-CODE')
  })
  it('授权码已显示后撤权会立即清空并停止请求', async () => {
    api.get.mockResolvedValue(response(pending()))
    const wrapper = await render()
    expect(wrapper.text()).toContain('TEST-CODE')
    useAuthStore().user!.is_superuser = false; await flushPromises()
    expect(wrapper.text()).not.toContain('TEST-CODE')
    await vi.advanceTimersByTimeAsync(6000); expect(api.get).toHaveBeenCalledTimes(1)
  })
  it('写入超时只重新GET核对，不重复登录，进行中禁止关闭', async () => {
    let fail!: (error: unknown) => void
    api.action.mockImplementationOnce(() => new Promise((_, reject) => { fail = reject }))
    const wrapper = await render()
    await wrapper.get('[data-action="login"]').trigger('click')
    expect(wrapper.get('[data-action="refresh"]').attributes('disabled')).toBeDefined()
    expect(wrapper.vm.canClose()).toBe(false)
    fail(new AxiosError('timeout', 'ECONNABORTED')); await flushPromises()
    expect(api.action).toHaveBeenCalledTimes(1); expect(api.get).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('不会自动重复操作')
  })
  it('切换需明确确认，取消确认不发送；确认后显示服务器排空状态', async () => {
    api.get.mockResolvedValue(response(snapshot({ status: 'READY', account: { display_name: 't***', plan_type: 'Plus' } })))
    const wrapper = await render()
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    await wrapper.get('[data-action="switch"]').trigger('click'); await flushPromises(); expect(api.action).not.toHaveBeenCalled()
    const draining = response(snapshot({ status: 'DRAINING', account: { display_name: 't***', plan_type: 'Plus' }, operation: { id: operationId, action: 'switch', state: 'QUEUED', actor_id: employeeId, can_cancel: true } }))
    api.action.mockResolvedValue(draining); api.get.mockResolvedValue(draining)
    await wrapper.get('[data-action="switch"]').trigger('click'); await flushPromises()
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(expect.stringContaining('等待当前任务结束'), expect.any(String), expect.any(Object))
    expect(api.action).toHaveBeenCalledWith('switch', '"v1"', undefined)
    expect(wrapper.text()).toContain('正在暂停新任务'); expect(wrapper.get('[data-action="test"]').attributes('disabled')).toBeDefined()
  })
  it('选择模型后必须保存再测试，测试成功仅按服务器READY显示', async () => {
    api.get.mockResolvedValue(response(snapshot({ status: 'CONNECTED', account: { display_name: 't***', plan_type: 'Plus' } })))
    const wrapper = await render()
    await wrapper.get('select').setValue('model-b')
    expect(wrapper.get('[data-action="test"]').attributes('disabled')).toBeDefined()
    const saved = response(snapshot({ status: 'CONNECTED', selected_model: 'model-b', config_generation: 2, account: { display_name: 't***', plan_type: 'Plus' } }))
    api.save.mockResolvedValue(saved); api.get.mockResolvedValue(saved)
    await wrapper.get('[data-action="save-model"]').trigger('click'); await flushPromises()
    expect(api.save).toHaveBeenCalledWith('model-b', '"v1"')
    const tested = response({ ...saved.data, status: 'READY' }); api.action.mockResolvedValue(tested); api.get.mockResolvedValue(tested)
    await wrapper.get('[data-action="test"]').trigger('click'); await flushPromises()
    expect(api.action).toHaveBeenCalledWith('test', '"v1"', undefined); expect(wrapper.text()).toContain('最小测试通过')
  })
  it('读取失败清除版本并禁用写操作，不保留假成功', async () => {
    const wrapper = await render()
    api.get.mockRejectedValueOnce(new AxiosError('private trace', undefined, undefined, undefined, { status: 503 } as never))
    await wrapper.get('[data-action="read"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('暂时无法完成'); expect(wrapper.text()).not.toContain('private trace')
    expect(wrapper.get('[data-action="login"]').attributes('disabled')).toBeDefined()
  })
  it('官方用量限制明确提示暂停，不建议重新授权或自动重试', async () => {
    api.get.mockResolvedValue(response(snapshot({ status: 'ERROR', error_code: 'USAGE_LIMIT_EXCEEDED',
      account: { display_name: 't***', plan_type: 'pro' }, paused: true })))
    const wrapper = await render()
    expect(wrapper.text()).toContain('官方用量已达限制，新任务已暂停。请等待额度恢复或更换可用账号后测试。')
    expect(wrapper.text()).not.toContain('重新授权后测试')
    expect(wrapper.get('[data-action="switch"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.get('[data-action="disconnect"]').attributes('disabled')).toBeUndefined()
    const reads = api.get.mock.calls.length
    await vi.advanceTimersByTimeAsync(6000); await flushPromises()
    expect(api.get).toHaveBeenCalledTimes(reads)
    expect(api.action).not.toHaveBeenCalled(); expect(api.challenge).not.toHaveBeenCalled()
  })
  it.each(['TIMEOUT', 'UPSTREAM_UNAVAILABLE'])('其他错误 %s 保留原提示', async error_code => {
    api.get.mockResolvedValue(response(snapshot({ status: 'ERROR', error_code })))
    const wrapper = await render()
    expect(wrapper.text()).toContain('连接未就绪，请重新读取状态，或重新授权后测试。')
    expect(wrapper.text()).not.toContain('官方用量已达限制')
  })
  it('非ERROR状态不把遗留用量错误码当作当前失败', async () => {
    api.get.mockResolvedValue(response(snapshot({ status: 'READY', error_code: 'USAGE_LIMIT_EXCEEDED',
      account: { display_name: 't***', plan_type: 'pro' }, paused: false })))
    const wrapper = await render()
    expect(wrapper.text()).toContain('最小测试通过')
    expect(wrapper.text()).not.toContain('官方用量已达限制')
  })
})
