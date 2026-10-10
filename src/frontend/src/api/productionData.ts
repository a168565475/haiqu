import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type {
  AccessoryProductName,
  PaginatedProductionData,
  ProductCategory,
  ProductColor,
  ProductionDataInput,
  ProductionDataQuery,
  ProductionDataRecord,
  ProductionDataResource,
  ProductionDataSummary,
  VersionedProductionData,
} from '@/types/productionData'

const basePath = '/api/v1/reference-data/'

function versioned<T>(response: AxiosResponse<DataResponse<T>>): VersionedProductionData<T> {
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : '',
  }
}

export async function fetchProductionDataSummary(): Promise<ProductionDataSummary> {
  const { data } = await apiClient.get<DataResponse<ProductionDataSummary>>(`${basePath}production-data-summary/`)
  return data.data
}

export async function fetchProductionDataList<T extends ProductionDataRecord>(
  resource: ProductionDataResource,
  query: ProductionDataQuery = {},
): Promise<PaginatedProductionData<T>> {
  const { data } = await apiClient.get<PaginatedProductionData<T>>(`${basePath}${resource}/`, { params: query })
  return data
}

export async function fetchAllProductionDataRecords<T extends ProductionDataRecord>(
  resource: ProductionDataResource,
): Promise<T[]> {
  const firstPage = await fetchProductionDataList<T>(resource, {
    page: 1,
    page_size: 100,
    status: 'ACTIVE',
  })
  if (firstPage.meta.total_pages <= 1) return firstPage.data
  const remainingPages = await Promise.all(
    Array.from({ length: firstPage.meta.total_pages - 1 }, (_, index) => (
      fetchProductionDataList<T>(resource, {
        page: index + 2,
        page_size: 100,
        status: 'ACTIVE',
      })
    )),
  )
  return [firstPage.data, ...remainingPages.map((page) => page.data)].flat()
}

export async function fetchAllProductCategories(): Promise<ProductCategory[]> {
  const firstPage = await fetchProductionDataList<ProductCategory>('product-categories', {
    page: 1,
    page_size: 100,
    status: 'ACTIVE',
  })
  if (firstPage.meta.total_pages <= 1) return firstPage.data
  const pages = await Promise.all(
    Array.from({ length: firstPage.meta.total_pages - 1 }, (_, index) => (
      fetchProductionDataList<ProductCategory>('product-categories', {
        page: index + 2,
        page_size: 100,
        status: 'ACTIVE',
      })
    )),
  )
  return [firstPage.data, ...pages.map((page) => page.data)].flat()
}

export async function fetchAllAccessoryProductNames(): Promise<AccessoryProductName[]> {
  const firstPage = await fetchProductionDataList<AccessoryProductName>('accessory-product-names', {
    page: 1,
    page_size: 100,
    status: 'ACTIVE',
  })
  if (firstPage.meta.total_pages <= 1) return firstPage.data
  const pages = await Promise.all(
    Array.from({ length: firstPage.meta.total_pages - 1 }, (_, index) => (
      fetchProductionDataList<AccessoryProductName>('accessory-product-names', {
        page: index + 2,
        page_size: 100,
        status: 'ACTIVE',
      })
    )),
  )
  return [firstPage.data, ...pages.map((page) => page.data)].flat()
}

export async function fetchProductionDataRecord<T extends ProductionDataRecord>(
  resource: ProductionDataResource,
  id: string,
): Promise<VersionedProductionData<T>> {
  const response = await apiClient.get<DataResponse<T>>(`${basePath}${resource}/${encodeURIComponent(id)}/`)
  return versioned(response)
}

export async function createProductionDataRecord<T extends ProductionDataRecord>(
  resource: ProductionDataResource,
  payload: ProductionDataInput,
): Promise<VersionedProductionData<T>> {
  const response = await apiClient.post<DataResponse<T>>(`${basePath}${resource}/`, payload)
  return versioned(response)
}

export async function updateProductionDataRecord<T extends ProductionDataRecord>(
  resource: ProductionDataResource,
  id: string,
  payload: ProductionDataInput,
  etag: string,
): Promise<VersionedProductionData<T>> {
  const response = await apiClient.patch<DataResponse<T>>(
    `${basePath}${resource}/${encodeURIComponent(id)}/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}

export async function changeProductionDataStatus<T extends ProductionDataRecord>(
  resource: ProductionDataResource,
  id: string,
  action: 'activate' | 'deactivate',
  etag: string,
  reason: string,
): Promise<VersionedProductionData<T>> {
  const response = await apiClient.post<DataResponse<T>>(
    `${basePath}${resource}/${encodeURIComponent(id)}/${action}/`,
    { reason },
    { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}

export async function archiveProductionDataRecord<T extends ProductionDataRecord>(
  resource: ProductionDataResource,
  id: string,
  etag: string,
  reason: string,
): Promise<VersionedProductionData<T>> {
  const response = await apiClient.post<DataResponse<T>>(
    `${basePath}${resource}/${encodeURIComponent(id)}/archive/`,
    { reason },
    { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}

export async function uploadProductColorImage(
  id: string,
  image: File,
  etag: string,
): Promise<VersionedProductionData<ProductColor>> {
  const payload = new FormData()
  payload.append('image', image)
  const response = await apiClient.post<DataResponse<ProductColor>>(
    `${basePath}product-colors/${encodeURIComponent(id)}/image/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}

export async function clearProductColorImage(
  id: string,
  etag: string,
): Promise<VersionedProductionData<ProductColor>> {
  const response = await apiClient.delete<DataResponse<ProductColor>>(
    `${basePath}product-colors/${encodeURIComponent(id)}/image/`,
    { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}
