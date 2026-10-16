import type { AxiosResponse } from 'axios'
import { apiClient } from './request'
import type {
  ProductCatalog, ProductCatalogFields, ProductCatalogInput, ProductCatalogList, ProductCatalogName,
  ProductCatalogNameInput, ProductCatalogOptions, ProductCatalogQuery, VersionedProductCatalog, VersionedProductCatalogName,
} from '@/types/productCatalog'

const base = '/api/v1/product-catalog/'
type Data<T> = { data: T }
const path = (id: string) => `${base}${encodeURIComponent(id)}/`
const namePath = (id: string) => `${base}names/${encodeURIComponent(id)}/`
const headers = (etag: string) => ({ headers: { 'If-Match': etag } })
function versioned<T>(response: AxiosResponse<Data<T>>): { data: T; etag: string } {
  return { data: response.data.data, etag: typeof response.headers.etag === 'string' ? response.headers.etag : '' }
}
export async function fetchProductCatalogOptions(): Promise<ProductCatalogOptions> {
  return (await apiClient.get<Data<ProductCatalogOptions>>(`${base}options/`)).data.data
}
export async function fetchProductCatalogNames(query: { category_id?: string; q?: string }): Promise<ProductCatalogName[]> {
  return (await apiClient.get<Data<ProductCatalogName[]>>(`${base}names/`, { params: query })).data.data
}
export async function fetchProductCatalogName(id: string): Promise<VersionedProductCatalogName> {
  return versioned(await apiClient.get<Data<ProductCatalogName>>(namePath(id)))
}
export async function createProductCatalogName(input: ProductCatalogNameInput): Promise<VersionedProductCatalogName> {
  return versioned(await apiClient.post<Data<ProductCatalogName>>(`${base}names/`, input))
}
export async function updateProductCatalogName(id: string, input: { name: string }, etag: string): Promise<VersionedProductCatalogName> {
  return versioned(await apiClient.patch<Data<ProductCatalogName>>(namePath(id), input, headers(etag)))
}
export async function fetchProductCatalogs(query: ProductCatalogQuery): Promise<ProductCatalogList> {
  return (await apiClient.get<ProductCatalogList>(base, { params: query })).data
}
export async function fetchProductCatalog(id: string): Promise<VersionedProductCatalog> {
  return versioned(await apiClient.get<Data<ProductCatalog>>(path(id)))
}
export async function createProductCatalog(input: ProductCatalogInput): Promise<VersionedProductCatalog> {
  return versioned(await apiClient.post<Data<ProductCatalog>>(base, input))
}
export async function updateProductCatalog(id: string, input: Partial<ProductCatalogFields>, etag: string): Promise<VersionedProductCatalog> {
  return versioned(await apiClient.patch<Data<ProductCatalog>>(path(id), input, headers(etag)))
}
export async function addProductCatalogColor(id: string, input: { value: string }, etag: string): Promise<VersionedProductCatalog> {
  return versioned(await apiClient.post<Data<ProductCatalog>>(`${path(id)}colors/`, input, headers(etag)))
}
export async function deleteProductCatalogColor(id: string, colorId: string, etag: string): Promise<VersionedProductCatalog> {
  return versioned(await apiClient.delete<Data<ProductCatalog>>(`${path(id)}colors/${encodeURIComponent(colorId)}/`, headers(etag)))
}
type ApiError = { response?: { status?: number; data?: { error?: { message?: string; field_errors?: Record<string, unknown> }; detail?: string } }; message?: string }
export function productCatalogErrorStatus(error: unknown): number | undefined { return (error as ApiError | null)?.response?.status }
export function productCatalogError(error: unknown): string {
  const issue = error as ApiError | null
  if ([412, 428].includes(productCatalogErrorStatus(error) ?? 0)) return '档案版本已变化或缺失，请重新读取后再保存。'
  const data = issue?.response?.data
  const fields = Object.values(data?.error?.field_errors ?? {}).flat().filter(value => typeof value === 'string')
  return fields.length ? fields.join('；') : data?.error?.message || data?.detail || issue?.message || '操作失败，请稍后重试。'
}
