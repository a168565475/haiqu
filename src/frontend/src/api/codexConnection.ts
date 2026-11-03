import { isAxiosError } from 'axios'
import { apiClient } from './request'
import type { CodexConnectionAction, CodexConnectionResponse, CodexConnectionSnapshot, CodexLoginChallenge } from '@/types/codexConnection'

const root = '/api/v1/codex-connection/'
class CodexResponseError extends Error {}
const options = (signal?: AbortSignal) => ({ timeout: 15000, signal })
function writeOptions(etag: string) {
  if (!etag.trim()) throw new CodexResponseError('CODEX_VERSION_MISSING')
  return { timeout: 15000, headers: { 'If-Match': etag } }
}
function snapshot(response: { data: { data: CodexConnectionSnapshot }; headers: Record<string, unknown> }): CodexConnectionResponse {
  const etag = response.headers.etag
  if (typeof etag !== 'string' || !etag.trim()) throw new CodexResponseError('CODEX_VERSION_MISSING')
  if (!response.data?.data || !Number.isInteger(response.data.data.config_generation)
    || !['DISCONNECTED', 'CONNECTED', 'READY', 'LOGIN_PENDING', 'DRAINING', 'ERROR', 'UNKNOWN'].includes(response.data.data.status)) {
    throw new CodexResponseError('CODEX_RESPONSE_INVALID')
  }
  return { data: response.data.data, etag }
}
export async function getCodexConnection(signal?: AbortSignal): Promise<CodexConnectionResponse> {
  return snapshot(await apiClient.get(root, options(signal)))
}
export async function runCodexConnectionAction(action: CodexConnectionAction, etag: string, operationId?: string): Promise<CodexConnectionResponse> {
  if (action === 'login-cancel' && !operationId) throw new CodexResponseError('CODEX_OPERATION_REQUIRED')
  return snapshot(await apiClient.post(`${root}${action}/`, action === 'login-cancel' ? { operation_id: operationId } : {}, writeOptions(etag)))
}
export async function saveCodexModel(model: string, etag: string): Promise<CodexConnectionResponse> {
  return snapshot(await apiClient.patch(root + 'model/', { model }, writeOptions(etag)))
}
export async function getCodexLoginChallenge(operationId: string, signal?: AbortSignal): Promise<CodexLoginChallenge> {
  const { data } = await apiClient.get<{ data: CodexLoginChallenge }>(root + 'challenge/', { ...options(signal), params: { operation_id: operationId } })
  const challenge = data?.data
  let url: URL
  try { url = new URL(challenge?.verification_url) }
  catch { throw new CodexResponseError('CODEX_CHALLENGE_INVALID') }
  if (url.protocol !== 'https:' || url.hostname !== 'auth.openai.com' || url.port || url.username || url.password
    || challenge.operation_id !== operationId || typeof challenge.user_code !== 'string' || !challenge.user_code.trim()
    || challenge.user_code.length > 128 || !Number.isFinite(Date.parse(challenge.expires_at))) {
    throw new CodexResponseError('CODEX_CHALLENGE_INVALID')
  }
  return challenge
}
export function codexConnectionError(error: unknown): string {
  if (error instanceof CodexResponseError) return error.message === 'CODEX_CHALLENGE_INVALID'
    ? '授权信息校验失败，请重新读取连接状态。' : '服务器返回的连接信息不完整，请重新读取。'
  if (!isAxiosError(error)) return '操作未完成，请重新读取连接状态。'
  if (!error.response) return '请求超时或网络中断，正在核对当前状态；不会自动重复操作。'
  if (error.response.status === 401) return 'ERP 登录已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号无权管理 Codex 连接。'
  if ([409, 412, 428].includes(error.response.status)) return '连接状态已变化或有操作正在进行，请读取最新状态后再试。'
  if (error.response.status === 429) return '请求过于频繁或额度不足，请稍后再试。'
  return 'Codex 服务暂时无法完成操作，请稍后重新读取状态。'
}
