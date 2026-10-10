import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type {
  PaginatedRawMaterials,
  RawMaterialInformation,
  RawMaterialInput,
  RawMaterialOptions,
  RawMaterialQuery,
  VersionedRawMaterial,
} from '@/types/rawMaterial'

const basePath = '/api/v1/raw-materials/'

function versioned(response: AxiosResponse<DataResponse<RawMaterialInformation>>): VersionedRawMaterial {
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : '',
  }
}

export async function fetchRawMaterials(query: RawMaterialQuery): Promise<PaginatedRawMaterials> {
  const { data } = await apiClient.get<PaginatedRawMaterials>(basePath, { params: query })
  return data
}

export async function fetchAllInventoryRawMaterials(): Promise<RawMaterialInformation[]> {
  const firstPage = await fetchRawMaterials({ page: 1, page_size: 100, item_type: 'MATERIAL' })
  if (firstPage.meta.total_pages <= 1) return firstPage.data
  const materials = [...firstPage.data]
  for (let page = 2; page <= firstPage.meta.total_pages; page += 1) {
    const response = await fetchRawMaterials({ page, page_size: 100, item_type: 'MATERIAL' })
    materials.push(...response.data)
  }
  return materials
}

export async function fetchRawMaterial(id: string): Promise<VersionedRawMaterial> {
  const response = await apiClient.get<DataResponse<RawMaterialInformation>>(
    `${basePath}${encodeURIComponent(id)}/`,
  )
  return versioned(response)
}

export async function fetchRawMaterialOptions(): Promise<RawMaterialOptions> {
  const { data } = await apiClient.get<DataResponse<RawMaterialOptions>>(`${basePath}options/`)
  return data.data
}

export async function createRawMaterial(payload: RawMaterialInput): Promise<VersionedRawMaterial> {
  const response = await apiClient.post<DataResponse<RawMaterialInformation>>(basePath, payload)
  return versioned(response)
}

export async function updateRawMaterial(
  id: string,
  payload: RawMaterialInput,
  etag: string,
): Promise<VersionedRawMaterial> {
  const response = await apiClient.patch<DataResponse<RawMaterialInformation>>(
    `${basePath}${encodeURIComponent(id)}/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}
