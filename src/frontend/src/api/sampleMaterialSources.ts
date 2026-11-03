import { apiClient } from './request'
import type { MaterialCatalog, MaterialCatalogList, MaterialCatalogOptions, MaterialCatalogQuery, PublicMaterialOptions, PublicMaterialOptionsQuery } from '@/types/materialCatalog'

const basePath = '/api/v1/sample-material-sources/'
type DataResponse<T> = { data: T }

export async function fetchSampleMaterialOptions(): Promise<MaterialCatalogOptions> {
  return (await apiClient.get<DataResponse<MaterialCatalogOptions>>(`${basePath}options/`)).data.data
}
export async function fetchSampleMaterials(query: MaterialCatalogQuery): Promise<MaterialCatalogList> {
  return (await apiClient.get<MaterialCatalogList>(basePath, { params: query })).data
}
export async function fetchSampleMaterial(id: string): Promise<DataResponse<MaterialCatalog>> {
  return (await apiClient.get<DataResponse<MaterialCatalog>>(`${basePath}${encodeURIComponent(id)}/`)).data
}
export async function fetchSamplePublicOptions(query: PublicMaterialOptionsQuery): Promise<PublicMaterialOptions> {
  return (await apiClient.get<DataResponse<PublicMaterialOptions>>(`${basePath}public-options/`, { params: query })).data.data
}
export async function fetchSampleMaterialCrafts(): Promise<{ crafts: Array<{ id: string; craft_type: string; code: string; name: string }> }> {
  return (await apiClient.get<DataResponse<{ crafts: Array<{ id: string; craft_type: string; code: string; name: string }> }>>(`${basePath}crafts/`)).data.data
}
