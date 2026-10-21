import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import * as api from './wecom'

afterEach(() => vi.restoreAllMocks())
describe('企业微信消息请求契约', () => {
  it('模板缺少ETag拒绝写入流程，有版本时原样保留', async () => {
    const data = { name: '通用通知', body: '{{消息内容}}', is_saved: false, updated_at: null }
    vi.spyOn(apiClient, 'get').mockResolvedValueOnce({ data: { data }, headers: {} }).mockResolvedValueOnce({ data: { data }, headers: { etag: 'template-v0' } })
    await expect(api.getWeComMessageTemplate()).rejects.toThrow('模板版本缺失')
    await expect(api.getWeComMessageTemplate()).resolves.toEqual({ data, etag: 'template-v0' })
  })
  it('保存和发送携带各自版本，测试仅向单一绑定发送且保留幂等键', async () => {
    const template = { name: '通用通知', body: '{{消息内容}}' }
    const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: { data: { ...template, is_saved: true, updated_at: null } }, headers: { etag: 'template-v1' } })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { data: { id: 'attempt', status: 'PROCESSING' } } })
    await api.saveWeComMessageTemplate(template, 'template-v0')
    expect(patch).toHaveBeenCalledWith('/api/v1/wecom/message-template/', template, expect.objectContaining({ headers: { 'If-Match': 'template-v0' } }))
    const payload = { binding_id: 'binding-a', message_content: '测试', idempotency_key: '00000000-0000-4000-8000-000000000001' }
    await api.sendWeComMessageTest(payload, 'template-v1')
    expect(post).toHaveBeenCalledWith('/api/v1/wecom/message-tests/', payload, expect.objectContaining({ headers: { 'If-Match': 'template-v1' } }))
  })
  it('未知结果查询通过原幂等键过滤，分页参数不丢失', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { data: [], count: 0, page: 2, page_size: 20 } })
    await api.getWeComMessageAttempts({ page: 2, page_size: 20, idempotency_key: 'same-key' })
    expect(get).toHaveBeenCalledWith('/api/v1/wecom/message-attempts/', expect.objectContaining({ params: { page: 2, page_size: 20, idempotency_key: 'same-key' } }))
  })
})
