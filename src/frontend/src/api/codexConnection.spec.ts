import { AxiosError } from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import { getCodexConnection, runCodexConnectionAction, saveCodexModel, getCodexLoginChallenge, codexConnectionError } from './codexConnection'

const operationId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
const response = () => ({ data: { data: { status: 'DISCONNECTED', config_generation: 1 } }, headers: { etag: '"v2"' } })
afterEach(() => vi.restoreAllMocks())

describe('Codex连接请求契约', () => {
  it('读取快照保留ETag，缺少版本时拒绝继续写入', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValueOnce(response()).mockResolvedValueOnce({ ...response(), headers: {} })
    expect((await getCodexConnection()).etag).toBe('"v2"')
    await expect(getCodexConnection()).rejects.toThrow('CODEX_VERSION_MISSING')
  })
  it('读取快照保留官方用量限制错误码和暂停状态', async () => {
    const value = { status: 'ERROR', config_generation: 1, error_code: 'USAGE_LIMIT_EXCEEDED', paused: true }
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { data: value }, headers: { etag: '"v2"' } })
    expect(await getCodexConnection()).toEqual({ data: value, etag: '"v2"' })
  })
  it.each(['login', 'login-cancel', 'disconnect', 'switch', 'refresh', 'test'] as const)('%s带当前版本且不自动重复写入', async action => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue(response())
    await runCodexConnectionAction(action, '"v1"', action === 'login-cancel' ? operationId : undefined)
    expect(post).toHaveBeenCalledExactlyOnceWith(`/api/v1/codex-connection/${action}/`,
      action === 'login-cancel' ? { operation_id: operationId } : {}, expect.objectContaining({ headers: { 'If-Match': '"v1"' } }))
  })
  it('模型保存带版本，空版本或缺取消标识在发请求前拒绝', async () => {
    const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue(response())
    const post = vi.spyOn(apiClient, 'post')
    await saveCodexModel('test-model', '"v1"')
    expect(patch).toHaveBeenCalledWith('/api/v1/codex-connection/model/', { model: 'test-model' }, expect.objectContaining({ headers: { 'If-Match': '"v1"' } }))
    await expect(runCodexConnectionAction('test', '')).rejects.toThrow('CODEX_VERSION_MISSING')
    await expect(runCodexConnectionAction('login-cancel', '"v1"')).rejects.toThrow('CODEX_OPERATION_REQUIRED')
    expect(post).not.toHaveBeenCalled()
  })
  it.each(['http://auth.openai.com/device', 'https://auth.openai.com.evil.test/device', 'https://user@auth.openai.com/device', 'https://auth.openai.com:444/device'])('拒绝不合约的授权链接 %s', async verification_url => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { data: { operation_id: operationId, verification_url, user_code: 'TEST-CODE', expires_at: '2030-01-01T00:00:00Z' } } })
    await expect(getCodexLoginChallenge(operationId)).rejects.toThrow('CODEX_CHALLENGE_INVALID')
  })
  it('官方链接和操作标识校验通过才交给页面，错误信息不展示服务器原文', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { data: { operation_id: operationId, verification_url: 'https://auth.openai.com/device', user_code: 'TEST-CODE', expires_at: '2030-01-01T00:00:00Z' } } })
    expect((await getCodexLoginChallenge(operationId)).verification_url).toBe('https://auth.openai.com/device')
    const error = new AxiosError('private detail', undefined, undefined, undefined, { status: 500, data: { error: { message: 'private detail' } } } as never)
    expect(codexConnectionError(error)).not.toContain('private detail')
  })
})
