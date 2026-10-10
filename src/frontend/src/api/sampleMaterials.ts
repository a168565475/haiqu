import { apiClient } from './request'
import type { SampleMaterialDraft, SampleMaterialLoadResult, SampleMaterialUnit } from '@/types/sampleMaterial'
import type { SampleMaterialReferences, SampleMaterialCandidate, SampleMaterialCategory } from '@/types/sampleMaterial'

export async function fetchSampleMaterialReferences(): Promise<SampleMaterialReferences> {
  return (await apiClient.get<{ data: SampleMaterialReferences }>('/api/v1/sample-requests/material-reference-options/')).data.data
}

export async function fetchSampleMaterialCandidates(category: SampleMaterialCategory, q: string, page: number, name = '') {
  return (await apiClient.get<{ data: SampleMaterialCandidate[]; meta: { total: number } }>('/api/v1/sample-requests/material-candidates/', { params: { category, q, page, name, page_size: 50 } })).data
}

export async function fetchSampleMaterialUnits(): Promise<SampleMaterialUnit[]> {
  return (await apiClient.get<{ data: SampleMaterialUnit[] }>('/api/v1/sample-requests/material-units/')).data.data
}

export async function fetchSampleMaterials(sampleId: string): Promise<SampleMaterialLoadResult> {
  if (!sampleId) throw new Error('缺少申请编号。')
  return (await apiClient.get<{ data: SampleMaterialLoadResult }>(`/api/v1/sample-requests/${sampleId}/materials/`)).data.data
}

export async function saveSampleMaterials(input: { sampleId: string; etag: string; draft: SampleMaterialDraft; submit: boolean }): Promise<SampleMaterialLoadResult> {
  if (!input.sampleId) throw new Error('缺少申请编号，请重新进入。')
  if (!input.etag) throw new Error('缺少材料版本，请重新加载。')
  return (await apiClient.put<{ data: SampleMaterialLoadResult }>(`/api/v1/sample-requests/${input.sampleId}/materials/`, { draft: input.draft, submit: input.submit }, { headers: { 'If-Match': input.etag } })).data.data
}

export async function confirmSampleNoMaterials(sampleId: string, etag: string): Promise<SampleMaterialLoadResult> {
  if (!sampleId || !etag) throw new Error('缺少申请或材料版本，请重新加载。')
  return (await apiClient.post<{ data: SampleMaterialLoadResult }>(`/api/v1/sample-requests/${sampleId}/no-materials/`, {}, { headers: { 'If-Match': etag } })).data.data
}
