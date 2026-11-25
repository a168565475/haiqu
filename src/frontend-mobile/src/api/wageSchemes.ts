import type { AxiosResponse } from 'axios'
import { apiClient } from '@/utils/request'
import type { SavedWageScheme, VersionedWageScheme, WageFormOptions, WageSchemeInput, WageSubmission, WageTarget, WageTargetResponse } from '@/types/wageSchemes'

const path = '/api/v1/workshop-reporting/wage-schemes/'
type ResponseData<T> = { data: T }

function versioned(response: AxiosResponse<ResponseData<SavedWageScheme>>): VersionedWageScheme {
  const etag = response.headers.etag
  if (typeof etag !== 'string' || !etag) throw new Error('未收到工价方案版本，请核对保存结果后重试')
  return { data: response.data.data, etag }
}

export async function fetchWageTargets(taskNumber: string, page: number, signal?: AbortSignal) {
  const { data } = await apiClient.get<WageTargetResponse>(`${path}mobile-targets/`, {
    params: taskNumber ? { task_number: taskNumber } : { page }, signal,
  })
  return data
}

export async function fetchWageSubmissions(taskNumber: string, page: number, signal?: AbortSignal) {
  const { data } = await apiClient.get<{ data: WageSubmission[]; meta: WageTargetResponse['meta'] }>(path, {
    params: { submitted_by_me: true, task_number: taskNumber, page }, signal,
  })
  return data
}

export async function fetchWageForm(target: WageTarget, signal?: AbortSignal) {
  const { data } = await apiClient.get<ResponseData<WageFormOptions>>(`${path}mobile-form/`, {
    params: { schedule_product_id: target.schedule_product_id, craft_id: target.craft_id }, signal,
  })
  return data.data
}

export async function fetchWageScheme(id: string, signal?: AbortSignal) {
  return versioned(await apiClient.get<ResponseData<SavedWageScheme>>(`${path}${encodeURIComponent(id)}/`, { signal }))
}

export async function saveWageScheme(input: WageSchemeInput, saved: VersionedWageScheme | null) {
  if (!saved) return versioned(await apiClient.post<ResponseData<SavedWageScheme>>(path, input))
  return versioned(await apiClient.patch<ResponseData<SavedWageScheme>>(
    `${path}${encodeURIComponent(saved.data.id)}/`, input, { headers: { 'If-Match': saved.etag } },
  ))
}

export async function createWageSchemeChange(source: VersionedWageScheme, input: WageSchemeInput) {
  return versioned(await apiClient.post<ResponseData<SavedWageScheme>>(
    `${path}${encodeURIComponent(source.data.id)}/change/`, input, { headers: { 'If-Match': source.etag } },
  ))
}

export async function submitWageScheme(saved: VersionedWageScheme) {
  const { data } = await apiClient.post<ResponseData<SavedWageScheme>>(
    `${path}${encodeURIComponent(saved.data.id)}/submit/`, {}, { headers: { 'If-Match': saved.etag } },
  )
  return data.data
}
