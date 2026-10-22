import { apiClient } from './request'
import type { SampleWarehouseDraft, SampleWarehouseLoadResult, SampleWarehouseInventory } from '@/types/sampleWarehouse'

export async function fetchSampleInventoryCandidates(sampleId: string): Promise<SampleWarehouseInventory> {
  if (!sampleId) throw new Error('缺少申请编号。')
  return (await apiClient.get<{ data: SampleWarehouseInventory }>(`/api/v1/sample-requests/${sampleId}/warehouse-inventory/`)).data.data
}

export async function fetchSampleWarehouseReview(sampleId: string): Promise<SampleWarehouseLoadResult> {
  if (!sampleId) throw new Error('缺少申请编号。')
  return (await apiClient.get<{ data: SampleWarehouseLoadResult }>(`/api/v1/sample-requests/${sampleId}/warehouse-review/`)).data.data
}

export async function saveSampleWarehouseReview(input: { sampleId: string; etag: string; draft: SampleWarehouseDraft; submit: boolean }): Promise<SampleWarehouseLoadResult> {
  if (!input.sampleId) throw new Error('缺少申请编号，请重新加载。')
  if (!input.etag) throw new Error('缺少材料版本，请重新加载。')
  const draft = { notes: input.draft.notes, lines: input.draft.lines.map(({ key, supplyQuantity, inventoryAllocations }) => ({ key, supplyQuantity,
    inventoryAllocations: (inventoryAllocations || []).map(({ balanceId, stockMode, quantity }) => ({ balanceId, stockMode, quantity })),
  })) }
  return (await apiClient.put<{ data: SampleWarehouseLoadResult }>(`/api/v1/sample-requests/${input.sampleId}/warehouse-review/`, { draft, submit: input.submit }, { headers: { 'If-Match': input.etag } })).data.data
}
