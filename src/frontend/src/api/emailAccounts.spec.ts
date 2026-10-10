import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchEmailAccounts, sendEmailAccountTest, updateEmailAccount } from '@/api/emailAccounts'
import { apiClient } from '@/api/request'

vi.mock('@/api/request', () => ({
  apiClient: {
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
  },
}))

const mockedGet = vi.mocked(apiClient.get)
const mockedPatch = vi.mocked(apiClient.patch)
const mockedPost = vi.mocked(apiClient.post)

describe('email accounts api', () => {
  beforeEach(() => {
    mockedGet.mockReset()
    mockedPatch.mockReset()
    mockedPost.mockReset()
  })

  it('读取当前账户自己的邮件账户列表', async () => {
    mockedGet.mockResolvedValueOnce({ data: { data: [{ id: 'mail-1', display_name: '工作邮箱' }] } })

    await expect(fetchEmailAccounts()).resolves.toEqual([{ id: 'mail-1', display_name: '工作邮箱' }])
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/email-accounts/', { params: { page_size: 100 } })
  })

  it('更新与测试发送均携带 ETag', async () => {
    mockedPatch.mockResolvedValueOnce({ data: { data: { id: 'mail-1' } }, headers: { etag: '"v1"' } })
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'mail-1' } }, headers: { etag: '"v2"' } })

    await updateEmailAccount('mail-1', { is_enabled: false }, '"v0"')
    await sendEmailAccountTest('mail-1', 'test@example.test', '"v1"')

    expect(mockedPatch).toHaveBeenCalledWith(
      '/api/v1/email-accounts/mail-1/',
      { is_enabled: false },
      { headers: { 'If-Match': '"v0"' } },
    )
    expect(mockedPost).toHaveBeenCalledWith(
      '/api/v1/email-accounts/mail-1/test-send/',
      { recipient: 'test@example.test' },
      { headers: { 'If-Match': '"v1"' } },
    )
  })
})
