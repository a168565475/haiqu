import type { AxiosResponse } from 'axios'

import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type {
  PaginatedProducts,
  ProductInformation,
  ProductInformationInput,
  ProductInformationQuery,
  ProductOptions,
  VersionedProduct,
} from '@/types/product'

const basePath = '/api/v1/products/'

function versioned(response: AxiosResponse<DataResponse<ProductInformation>>): VersionedProduct {
  return {
    data: response.data.data,
    etag: typeof response.headers.etag === 'string' ? response.headers.etag : '',
  }
}

export async function fetchProducts(query: ProductInformationQuery): Promise<PaginatedProducts> {
  const { data } = await apiClient.get<PaginatedProducts>(basePath, { params: query })
  return data
}

export async function fetchProduct(id: string): Promise<VersionedProduct> {
  const response = await apiClient.get<DataResponse<ProductInformation>>(`${basePath}${encodeURIComponent(id)}/`)
  return versioned(response)
}

export async function fetchProductOptions(): Promise<ProductOptions> {
  const { data } = await apiClient.get<DataResponse<ProductOptions>>(`${basePath}options/`)
  return data.data
}

export async function createProduct(payload: ProductInformationInput): Promise<VersionedProduct> {
  const response = await apiClient.post<DataResponse<ProductInformation>>(basePath, payload)
  return versioned(response)
}

export async function updateProduct(
  id: string,
  payload: ProductInformationInput,
  etag: string,
): Promise<VersionedProduct> {
  const response = await apiClient.patch<DataResponse<ProductInformation>>(
    `${basePath}${encodeURIComponent(id)}/`,
    payload,
    { headers: { 'If-Match': etag } },
  )
  return versioned(response)
}

