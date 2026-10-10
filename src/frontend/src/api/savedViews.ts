import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { ApiDataResponse, PaginatedResponse } from '@/types/customer'
import type { SavedView, SavedViewCreateInput } from '@/types/savedView'

function unwrapData<T>(response: AxiosResponse<ApiDataResponse<T>>): T {
  return response.data.data
}

export async function fetchSavedViews(moduleCode: string): Promise<SavedView[]> {
  const { data } = await apiClient.get<PaginatedResponse<SavedView>>('/api/v1/saved-views/', {
    params: { module_code: moduleCode, page_size: 100 },
  })
  return data.data
}

export async function createSavedView(payload: SavedViewCreateInput): Promise<SavedView> {
  const response = await apiClient.post<ApiDataResponse<SavedView>>('/api/v1/saved-views/', payload)
  return unwrapData(response)
}

export async function setDefaultSavedView(id: string): Promise<SavedView> {
  const url = `/api/v1/saved-views/${encodeURIComponent(id)}/`
  const current = await apiClient.get<ApiDataResponse<SavedView>>(url)
  const etag = current.headers.etag
  if (!etag) throw new Error('缺少个人视图版本，请刷新后重试。')
  return unwrapData(await apiClient.post<ApiDataResponse<SavedView>>(`${url}set-default/`, {}, { headers: { 'If-Match': etag } }))
}

export function fetchCustomerSavedViews(): Promise<SavedView[]> {
  return fetchSavedViews('CUSTOMER')
}

export function createCustomerSavedView(payload: SavedViewCreateInput): Promise<SavedView> {
  return createSavedView(payload)
}

export function fetchQuotationSavedViews(): Promise<SavedView[]> {
  return fetchSavedViews('QUOTATION')
}

export function createQuotationSavedView(payload: SavedViewCreateInput): Promise<SavedView> {
  return createSavedView(payload)
}

export function fetchProductionTaskSavedViews(): Promise<SavedView[]> {
  return fetchSavedViews('PRODUCTION_TASK')
}

export function createProductionTaskSavedView(payload: SavedViewCreateInput): Promise<SavedView> {
  return createSavedView(payload)
}
