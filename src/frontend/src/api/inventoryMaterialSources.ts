import { apiClient } from './request'
import type { DataResponse } from '@/types/referenceData'
import type { MaterialCatalog, MaterialCatalogList, MaterialCatalogOptions, MaterialCatalogQuery, PublicMaterialOptions, PublicMaterialOptionsQuery } from '@/types/materialCatalog'

const basePath = '/api/v1/material-inbound-sources/'

export async function fetchInboundMaterialOptions(): Promise<MaterialCatalogOptions> {
  return (await apiClient.get<DataResponse<MaterialCatalogOptions>>(`${basePath}options/`)).data.data
}
export async function fetchInboundMaterials(query: MaterialCatalogQuery): Promise<MaterialCatalogList> {
  return (await apiClient.get<MaterialCatalogList>(basePath, { params: query })).data
}
export async function fetchInboundMaterial(id: string): Promise<DataResponse<MaterialCatalog>> {
  return (await apiClient.get<DataResponse<MaterialCatalog>>(`${basePath}${encodeURIComponent(id)}/`)).data
}
export async function fetchInboundPublicOptions(query: PublicMaterialOptionsQuery): Promise<PublicMaterialOptions> {
  return (await apiClient.get<DataResponse<PublicMaterialOptions>>(`${basePath}public-options/`, { params: query })).data.data
}
