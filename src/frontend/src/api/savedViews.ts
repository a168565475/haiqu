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
