import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'
import { errorMessage } from './errors'

function failure(data: unknown, status = 400) {
  return new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, {
    data, status, statusText: 'Bad Request', headers: {}, config: { headers: new AxiosHeaders() },
  })
}
describe('ERP 错误契约', () => {
  it('显示业务错误的具体原因而不是通用失败', () => {
    expect(errorMessage(failure({ error: { code: 'SOURCE_CHANGED', message: 'BOM 来源已经变化，请刷新领料明细后重新提交。' } }, 409)))
      .toBe('BOM 来源已经变化，请刷新领料明细后重新提交。')
  })
  it('支持独立登录接口的 detail', () => {
    expect(errorMessage(failure({ detail: '用户名或密码错误' }))).toBe('用户名或密码错误')
  })
  it('网络断开不会显示提交成功', () => {
    expect(errorMessage(new AxiosError('Network Error'))).toContain('核对提交结果')
  })
})
