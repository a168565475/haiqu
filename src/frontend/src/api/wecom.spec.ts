import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import { AxiosError } from 'axios'
import { bindWeComEmployee, getWeComConfig, saveWeComConfig, checkWeComConnection, wecomError } from './wecom'

afterEach(() => vi.restoreAllMocks())

describe('企业微信管理请求契约', () => {
  it('读取并保留服务端返回的三项凭据，不用配置状态替代真实值', async () => {
    const saved = { has_secret: true, has_callback_token: true, has_callback_aes_key: true, secret: 'fixture-secret', callback_token: 'fixturetoken', callback_aes_key: 'a'.repeat(43), credential_read_errors: [] }
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { data: saved }, headers: { etag: 'v1' } })
    const result = await getWeComConfig()
    expect(get).toHaveBeenCalledWith('/api/v1/wecom/config/', expect.any(Object))
    expect(result.data).toEqual(saved)
    expect(result.etag).toBe('v1')
  })
  it('省略空密钥、携带版本并接收新版本', async () => {
    const saved = { has_secret: true, secret: 'fixture-secret', callback_token: '', callback_aes_key: '', credential_read_errors: [] }
    const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: { data: saved }, headers: { etag: 'v2' } })
    const result = await saveWeComConfig({ corp_id: 'corp', agent_id: '1', erp_origin: 'https://erp.test', enabled: false, secret: '', callback_token: ' ', callback_aes_key: '' }, 'v1')
    expect(patch).toHaveBeenCalledWith('/api/v1/wecom/config/', { corp_id: 'corp', agent_id: '1', erp_origin: 'https://erp.test', enabled: false }, expect.objectContaining({ headers: { 'If-Match': 'v1' } }))
    expect(result.etag).toBe('v2')
    expect(result.data).toEqual(saved)
  })
  it('绑定必须使用所选员工版本和显式身份确认', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { data: { id: 'binding' } } })
    await bindWeComEmployee('Member.A', { id: 'employee', employee_code: 'E1', display_name: '测试员工', username: 'account', etag: 'employee-v1' })
    expect(post).toHaveBeenCalledWith('/api/v1/wecom/bindings/', { user_id: 'Member.A', employee_id: 'employee', confirmed: true }, expect.objectContaining({ headers: { 'If-Match': 'employee-v1' } }))
  })
  it('连接检查使用当前配置版本', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { data: {} }, headers: { etag: 'v3' } })
    await checkWeComConnection('v2')
    expect(post).toHaveBeenCalledWith('/api/v1/wecom/config/check/', {}, expect.objectContaining({ headers: { 'If-Match': 'v2' } }))
  })
  it('保留明确的未迁移、加密密钥和绑定冲突原因', () => {
    for (const [status, code, message] of [[503, 'WECOM_UNAVAILABLE', '企业微信模块尚未执行已审阅的数据库迁移。'], [409, 'CONFLICT', '企业微信加密密钥未配置。'], [409, 'CONFLICT', '此企业微信账号已绑定其他员工。']] as const) {
      const error = new AxiosError('request', undefined, undefined, undefined, { status, data: { error: { code, message, field_errors: {} } } } as never)
      expect(wecomError(error)).toContain(message)
    }
  })
  it('显示已知字段校验错误，但不展示未知或服务器HTML错误内容', () => {
    const invalid = new AxiosError('request', undefined, undefined, undefined, { status: 400, data: { error: { code: 'VALIDATION_ERROR', message: '输入未通过校验', field_errors: { callback_aes_key: ['请输入43位密钥'], employee_id: ['员工不存在'] } } } } as never)
    expect(wecomError(invalid)).toContain('EncodingAESKey：请输入43位密钥')
    expect(wecomError(invalid)).toContain('ERP 员工：员工不存在')
    for (const data of ['<html>private trace</html>', { error: { code: 'UNKNOWN_ERROR', message: 'private trace' } }]) {
      expect(wecomError(new AxiosError('request', undefined, undefined, undefined, { status: 500, data } as never))).not.toContain('private trace')
    }
  })
})
