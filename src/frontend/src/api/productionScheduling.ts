import { isAxiosError, type AxiosResponse } from 'axios'

import { apiClient } from './request'
import type {
  BatchCreatedSchedules, CompleteScheduleInput, CompleteScheduleResult, Paginated, PlanCategory, ProductionSchedule, ScheduleBatchCreateInput, ScheduleCompletionPreview, ScheduleCreateInput, ScheduleItem, ScheduleOptions,
  ScheduleTaskCandidate, ScheduleUpdateInput, ScheduleWriteItem, VersionedSchedule,
} from '@/types/productionScheduling'
import type { DataResponse } from '@/types/referenceData'

const basePath = '/api/v1/production-schedules/'
const saveTimeout = 60_000

function versioned(response: AxiosResponse<DataResponse<ProductionSchedule>>): VersionedSchedule {
  return { data: response.data.data, etag: typeof response.headers.etag === 'string' ? response.headers.etag : '' }
}

export async function fetchSchedules(params: Record<string, unknown>): Promise<Paginated<ProductionSchedule>> {
  const { data } = await apiClient.get<Paginated<ProductionSchedule>>(basePath, { params })
  return data
}

export async function fetchSchedule(id: string): Promise<VersionedSchedule> {
  return versioned(await apiClient.get<DataResponse<ProductionSchedule>>(`${basePath}${encodeURIComponent(id)}/`))
}

async function checkUnacknowledgedSave<T>(error: unknown, readBack: () => Promise<T | null>): Promise<T> {
  if (!isAxiosError(error)) throw error
  const response = error.response
  const disconnected = !response && ['ECONNABORTED', 'ETIMEDOUT', 'ERR_NETWORK'].includes(error.code ?? '')
  const gatewayError = response && ([408, 502, 503, 504].includes(response.status) ||
    (response.status === 500 && (response.data == null || String(response.data).trim() === ''))) &&
    !response.data?.error?.message && !response.data?.detail
  if (!disconnected && !gatewayError) throw error

  const message = '尚未核实本次排产结果。填写已保留，请先在排产列表按生产任务单号核对。'
  let confirmed: T | null
  try { confirmed = await readBack() }
  catch (readError) { throw new Error(message, { cause: readError }) }
  if (!confirmed) throw new Error(message, { cause: error })
  return confirmed
}

async function readMatchingSchedule(id: string, items: ScheduleWriteItem[], taskId?: string) {
  const result = await fetchSchedule(id)
  const saved = result.data
  if (saved.id !== id || saved.record_status !== 'ACTIVE' || (taskId && saved.production_task_id !== taskId)
      || saved.products.length !== items.length) return null
  const matches = items.every(item => {
    const row = saved.products.find(product => product.product_line_id === item.product_line_id)
    return row && row.planned_quantity === item.planned_quantity
      && row.material_inbound_date === item.material_inbound_date && row.metal_return_date === item.metal_return_date
      && row.sewing_return_date === item.sewing_return_date && row.finished_inbound_date === item.finished_inbound_date
      && row.crafts.length === item.craft_ids.length && row.crafts.every(craft => item.craft_ids.includes(craft.id))
  })
  return matches ? result : null
}

async function readCreatedSchedule(input: ScheduleCreateInput) {
  const task = await fetchTaskCandidate(input.production_task_id)
  if (task.id !== input.production_task_id || !task.existing_schedule_id) return null
  return readMatchingSchedule(task.existing_schedule_id, input.items, task.id)
}

export async function createSchedule(payload: ScheduleCreateInput): Promise<VersionedSchedule> {
  try {
    return versioned(await apiClient.post<DataResponse<ProductionSchedule>>(basePath, payload, { timeout: saveTimeout }))
  } catch (error) { return checkUnacknowledgedSave(error, () => readCreatedSchedule(payload)) }
}

export async function createSchedulesBatch(payload: ScheduleBatchCreateInput): Promise<BatchCreatedSchedules> {
  try {
    const { data } = await apiClient.post<BatchCreatedSchedules>(`${basePath}batch/`, payload, { timeout: saveTimeout })
    return data
  } catch (error) {
    return checkUnacknowledgedSave(error, async () => {
      const data: ProductionSchedule[] = []
      for (const input of payload.schedules) {
        const confirmed = await readCreatedSchedule(input)
        if (!confirmed) return null
        data.push(confirmed.data)
      }
      return { data }
    })
  }
}

export async function updateSchedule(id: string, payload: ScheduleUpdateInput, etag: string): Promise<VersionedSchedule> {
  try {
    return versioned(await apiClient.patch<DataResponse<ProductionSchedule>>(
      `${basePath}${encodeURIComponent(id)}/`, payload, { headers: { 'If-Match': etag }, timeout: saveTimeout },
    ))
  } catch (error) { return checkUnacknowledgedSave(error, () => readMatchingSchedule(id, payload.items)) }
}

export async function voidSchedule(id: string, reason: string, etag: string): Promise<VersionedSchedule> {
  return versioned(await apiClient.post<DataResponse<ProductionSchedule>>(
    `${basePath}${encodeURIComponent(id)}/void/`, { reason }, { headers: { 'If-Match': etag } },
  ))
}

export async function completeSchedule(
  id: string,
  payload: CompleteScheduleInput,
  etag: string,
): Promise<CompleteScheduleResult> {
  const { data } = await apiClient.post<DataResponse<CompleteScheduleResult>>(
    `${basePath}${encodeURIComponent(id)}/complete/`, payload, { headers: { 'If-Match': etag } },
  )
  return data.data
}

export async function fetchScheduleCompletionPreview(id: string): Promise<ScheduleCompletionPreview> {
  const { data } = await apiClient.get<DataResponse<ScheduleCompletionPreview>>(
    `${basePath}${encodeURIComponent(id)}/completion-preview/`,
  )
  return data.data
}

export async function fetchScheduleOptions(): Promise<ScheduleOptions> {
  const { data } = await apiClient.get<DataResponse<ScheduleOptions>>(`${basePath}options/`)
  return data.data
}

export async function fetchTaskCandidates(params: Record<string, unknown>): Promise<Paginated<ScheduleTaskCandidate>> {
  const { data } = await apiClient.get<Paginated<ScheduleTaskCandidate>>(`${basePath}task-candidates/`, { params })
  return data
}

export async function fetchTaskCandidate(id: string): Promise<ScheduleTaskCandidate> {
  const { data } = await apiClient.get<DataResponse<ScheduleTaskCandidate>>(
    `${basePath}task-candidates/${encodeURIComponent(id)}/`,
  )
  return data.data
}

export async function fetchScheduleItems(params: Record<string, unknown>): Promise<Paginated<ScheduleItem>> {
  const { data } = await apiClient.get<Paginated<ScheduleItem>>('/api/v1/production-schedule-items/', { params })
  return data
}

export async function fetchSchedulePlanCategories(): Promise<PlanCategory[]> {
  const { data } = await apiClient.get<DataResponse<PlanCategory[]>>('/api/v1/production-schedule-items/categories/')
  return data.data
}

export function scheduleProductImageUrl(taskId: string, fileId: string): string {
  const path = `${basePath}task-files/${encodeURIComponent(taskId)}/${encodeURIComponent(fileId)}/`
  return new URL(path, `${apiClient.defaults.baseURL || window.location.origin}/`).toString()
}
