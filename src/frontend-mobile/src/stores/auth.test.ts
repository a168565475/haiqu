import { AxiosError } from 'axios'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from './auth'

const request = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), setIdentity: vi.fn() }))
vi.mock('@/utils/request', () => ({ apiClient: { get: request.get, post: request.post }, setRequestIdentity: request.setIdentity }))
const user = { id: 1, username: 'test', display_name: '测试员工', is_superuser: false, employee: { id: 'employee', display_name: '测试员工' }, permissions: [] }
const response = (version = 'one') => ({ data: { authenticated: true, user, account_switch: { identity_version: version, active: false, can_return: false } } })
function rejected(status: number, code: string) {
  return new AxiosError('请求被拒绝', 'ERR_BAD_REQUEST', undefined, undefined, { status, statusText: '', headers: {}, config: {} as never, data: { error: { code } } })
}
beforeEach(() => { vi.resetAllMocks(); setActivePinia(createPinia()); request.get.mockResolvedValue(response()); request.post.mockResolvedValue(response('logged-in')) })

describe('手机登录身份恢复', () => {
  it('匿名会话仍保留返回管理员状态，清理身份时同时清理', async () => {
    request.get.mockResolvedValue({ data: { authenticated: false, user: null, account_switch: { identity_version: 'one', active: true, can_return: true } } })
    const auth = useAuthStore()
    await auth.refresh(true)
    expect(auth.user).toBeNull()
    expect(auth.accountSwitch?.can_return).toBe(true)
    auth.clear()
    expect(auth.accountSwitch).toBeNull()
  })
  it('同一账号身份版本变化也重建业务页面，重复核验相同版本不清表单', async () => {
    const auth = useAuthStore()
    await auth.refresh(true)
    const first = auth.generation
    await auth.refresh(true)
    expect(auth.generation).toBe(first)
    request.get.mockResolvedValue(response('two'))
    await auth.refresh(true)
    expect(auth.generation).toBe(first + 1)
    expect(request.setIdentity).toHaveBeenLastCalledWith('two', true)
  })
  it.each([[403, 'IDENTITY_CONTEXT_INVALID'], [409, 'IDENTITY_VERSION_CONFLICT']])('明确身份失效 %s 可继续用户主动密码登录', async (status, code) => {
    request.get.mockRejectedValue(rejected(status, code))
    const auth = useAuthStore()
    await auth.login('test', 'test-password')
    expect(request.post).toHaveBeenCalledWith('/api/auth/login/', { username: 'test', password: 'test-password' })
    expect(auth.user?.id).toBe(user.id)
  })
  it.each([new Error('网络中断'), rejected(403, 'PERMISSION_DENIED'), rejected(500, 'SERVER_ERROR')])('不吞掉网络、普通权限或服务器错误', async error => {
    request.get.mockRejectedValue(error)
    await expect(useAuthStore().login('test', 'test-password')).rejects.toBe(error)
    expect(request.post).not.toHaveBeenCalled()
  })
  it('恢复登录仍保留后端 CSRF 拒绝，不显示登录成功', async () => {
    request.get.mockRejectedValue(rejected(403, 'IDENTITY_CONTEXT_INVALID'))
    const csrfError = rejected(403, 'CSRF_FAILED')
    request.post.mockRejectedValue(csrfError)
    const auth = useAuthStore()
    await expect(auth.login('test', 'test-password')).rejects.toBe(csrfError)
    expect(auth.user).toBeNull()
  })
  it('清除普通账号会话也废弃无身份版本的在途请求', async () => {
    const auth = useAuthStore()
    auth.clear()
    expect(request.setIdentity).toHaveBeenCalledWith(null, true)
  })
})
