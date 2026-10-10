import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type {
  PaginatedSuppliers,
  Supplier,
  SupplierInput,
  SupplierOptions,
  SupplierQuery,
  SupplierStats,
  VersionedSupplier,
} from '@/types/supplier'

const basePath = '/api/v1/suppliers/'

function versioned(response: AxiosResponse<DataResponse<Supplier>>): VersionedSupplier {
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : '',
  }
}

export async function fetchSuppliers(query: SupplierQuery): Promise<PaginatedSuppliers> {
  const { data } = await apiClient.get<PaginatedSuppliers>(basePath, { params: query })
  return data
}

export async function fetchSupplier(id: string): Promise<VersionedSupplier> {
  const response = await apiClient.get<DataResponse<Supplier>>(`${basePath}${encodeURIComponent(id)}/`)
  return versioned(response)
}

export async function fetchSupplierOptions(): Promise<SupplierOptions> {
  const { data } = await apiClient.get<DataResponse<SupplierOptions>>(`${basePath}options/`)
  return data.data
}

export async function fetchSupplierStats(): Promise<SupplierStats> {
  const { data } = await apiClient.get<DataResponse<SupplierStats>>(`${basePath}stats/`)
  return data.data
}

export async function createSupplier(payload: SupplierInput): Promise<VersionedSupplier> {
  const response = await apiClient.post<DataResponse<Supplier>>(basePath, payload)
  return versioned(response)
}

export async function updateSupplier(
  id: string,
  payload: SupplierInput,
  etag: string,
): Promise<VersionedSupplier> {
  const response = await apiClient.patch<DataResponse<Supplier>>(
    `${basePath}${encodeURIComponent(id)}/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}
