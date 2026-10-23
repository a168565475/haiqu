import { isAxiosError } from 'axios'
import { apiClient } from './request'
import { createClientUuid } from '@/utils/clientUuid'
import type {
  DepartmentMapping, DepartmentMappingInput, DepartmentMappingPreview, DepartmentMappingPreviewResponse,
  EmployeeDirectoryMatchInput, EmployeeDirectoryPreview, EmployeeDirectoryPreviewResponse,
  EmployeeDirectoryResult, EmployeeDirectorySyncInput,
  EmployeeDirectoryProgress, EmployeeDirectoryProgressObserver,
} from '@/types/employeeDirectory'

const root = '/api/v1/wecom/'
// GET恢复已保存副本；刷新与保存独立授权，超时不自动重试。
const options = (etag?: string, progressId?: string) => ({ timeout: 120000,
  ...(etag || progressId ? { headers: { ...(etag ? { 'If-Match': etag } : {}), ...(progressId ? { 'X-Directory-Progress': progressId } : {}) } } : {}),
})

async function withProgress<T>(observer: EmployeeDirectoryProgressObserver | undefined, request: (id?: string) => Promise<T>): Promise<T> {
  if (!observer) return request()
  const id = createClientUuid()
  let finished = false, timer: ReturnType<typeof setTimeout> | undefined
  const controller = new AbortController()
  const stop = () => { finished = true; clearTimeout(timer); controller.abort() }
  observer.signal.addEventListener('abort', stop, { once: true })
  if (observer.signal.aborted) stop()
  const poll = async () => {
    if (finished) return
    try {
      const response = await apiClient.get<{ data: EmployeeDirectoryProgress }>(root + `employee-directory/progress/${id}/`, { timeout: 10000, signal: controller.signal })
      const data = response.data.data
      if (!Number.isInteger(data.completed) || !Number.isInteger(data.total) || data.total < 1 || data.completed < 0 || data.completed > data.total
        || !['RUNNING', 'SUCCESS', 'FAILED'].includes(data.status) || typeof data.phase !== 'string') throw new Error('进度数据无效')
      if (!finished) observer.onProgress(data)
    } catch (error) {
      // 主请求刚发出时缓存可能尚未建立；其他读取故障明确标记，不推进百分比。
      if (!finished && !(isAxiosError(error) && error.response?.status === 404)) observer.onProgress(null)
    } finally { if (!finished) timer = setTimeout(poll, 1000) }
  }
  timer = setTimeout(poll, 300)
  try { return await request(id) }
  finally { stop(); observer.signal.removeEventListener('abort', stop) }
}

function previewResult<T>(response: { data: { data: T }; headers: Record<string, unknown> }): { data: T; etag: string } {
  const etag = response.headers.etag
  if (typeof etag !== 'string' || !etag.trim()) throw new Error('预览版本缺失，请重新读取后再操作。')
  return { data: response.data.data, etag }
}

export async function getEmployeeDirectoryPreview(applyDepartments = false, observer?: EmployeeDirectoryProgressObserver): Promise<EmployeeDirectoryPreviewResponse> {
  return withProgress(observer, async id => previewResult(await apiClient.get<{ data: EmployeeDirectoryPreview }>(root + 'employee-directory/', {
    ...options(undefined, id), params: { apply_departments: applyDepartments },
  })))
}

export async function refreshEmployeeDirectory(applyDepartments = false, observer?: EmployeeDirectoryProgressObserver): Promise<EmployeeDirectoryPreviewResponse> {
  return withProgress(observer, async id => previewResult(await apiClient.post<{ data: EmployeeDirectoryPreview }>(root + 'employee-directory/refresh/', {
    apply_departments: applyDepartments,
  }, options(undefined, id))))
}

export async function syncEmployeeDirectory(data: EmployeeDirectorySyncInput, etag: string, observer?: EmployeeDirectoryProgressObserver): Promise<EmployeeDirectoryResult[]> {
  return withProgress(observer, async id => (await apiClient.post<{ data: EmployeeDirectoryResult[] }>(root + 'employee-directory/sync/', data, options(etag, id))).data.data)
}

export async function matchEmployeeDirectory(data: EmployeeDirectoryMatchInput, etag: string, observer?: EmployeeDirectoryProgressObserver): Promise<EmployeeDirectoryResult> {
  return withProgress(observer, async id => (await apiClient.post<{ data: EmployeeDirectoryResult }>(root + 'employee-directory/match/', data, options(etag, id))).data.data)
}

export async function getDepartmentMappings(): Promise<DepartmentMappingPreviewResponse> {
  return previewResult(await apiClient.get<{ data: DepartmentMappingPreview }>(root + 'department-mappings/', options()))
}

export async function refreshDepartmentMappings(): Promise<DepartmentMappingPreviewResponse> {
  return previewResult(await apiClient.post<{ data: DepartmentMappingPreview }>(root + 'department-mappings/refresh/', {}, options()))
}

export function directoryAccessDenied(error: unknown): boolean {
  return isAxiosError(error) && [401, 403].includes(error.response?.status || 0)
}

export async function saveDepartmentMapping(departmentId: number, data: DepartmentMappingInput, etag: string): Promise<DepartmentMapping> {
  return (await apiClient.put<{ data: DepartmentMapping }>(root + `department-mappings/${departmentId}/`, data, options(etag))).data.data
}

const uncertainMessage = '请求未确认完成，请重新读取并核实结果后再操作，勿直接重复提交。'
const knownErrorCodes = new Set([
  'VALIDATION_ERROR', 'AUTHENTICATION_REQUIRED', 'PERMISSION_DENIED', 'NOT_FOUND', 'TOO_MANY_REQUESTS',
  'CONFLICT', 'PRECONDITION_FAILED', 'PRECONDITION_REQUIRED', 'REQUEST_FAILED',
  'WECOM_UNAVAILABLE', 'WECOM_UPSTREAM_ERROR', 'WECOM_ROLE_REQUIRED',
])
const fieldLabels: Record<string, string> = {
  preview_token: '预览', apply_departments: '补充部门归属', user_ids: '所选成员',
  confirmed_new_user_ids: '确认新建的成员', user_id: '企业微信账号', employee_id: 'ERP 员工',
  employee_etag: '员工版本', confirmed: '人工确认', department_id: '来源部门',
  organization_unit_id: 'ERP 部门', organization_etag: '部门版本', non_field_errors: '提交内容',
}

export function employeeDirectoryError(error: unknown): string {
  if (!isAxiosError(error) || !error.response) return uncertainMessage
  const { status, data } = error.response
  const detail = data?.error
  // 只显示项目约定的结构化错误，不将未知报文、HTML 或服务器堆栈交给页面。
  if (status !== 500 && detail && typeof detail === 'object' && knownErrorCodes.has(detail.code) && typeof detail.message === 'string') {
    const messages = [detail.message]
    if (detail.field_errors && typeof detail.field_errors === 'object') {
      for (const [field, value] of Object.entries(detail.field_errors)) {
        if (!Object.hasOwn(fieldLabels, field)) continue
        const errors = (Array.isArray(value) ? value : [value]).filter((item): item is string => typeof item === 'string')
        if (errors.length) messages.push(`${fieldLabels[field]}：${errors.join('；')}`)
      }
    }
    if (messages.some(Boolean)) return messages.filter(Boolean).join('；')
  }
  if (status === 412) return '来源或 ERP 资料已变化，请重新读取并核对后再提交。'
  if (status === 428) return '缺少预览版本，请重新读取后再操作。'
  if (status === 409) return '当前配置、身份或部门存在冲突，请核对后重新读取。'
  if (status === 403) return '当前账号无权执行此操作，或会话校验失败，请刷新核实权限。'
  if (status === 401) return '登录状态已失效，请重新登录。'
  if (status === 404) return '所选员工或部门已不存在，请重新读取并核对。'
  if (status === 400) return '提交内容未通过校验，请核对所选成员、人工确认及预览版本。'
  if (status === 503) return '服务尚未就绪，请联系管理员核实配置及数据库迁移。'
  return uncertainMessage
}
