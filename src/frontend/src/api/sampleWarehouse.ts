import { fetchMaterialInventory } from './inventory'
import { apiClient } from './request'
import type { SampleWarehouseDraft, SampleWarehouseLoadResult } from '@/types/sampleWarehouse'

/** @deprecated 仓库核对页不再展示系统库存参考，仅为历史组件保留旧调用契约。 */
export async function fetchSampleInventoryCandidates(keyword: string, page: number) {
  if (!keyword.trim()) throw new Error('请先指定材料名称。')
  if (!Number.isInteger(page) || page < 1) throw new Error('库存页码无效。')
  return fetchMaterialInventory({ q: keyword.trim(), page, page_size: 50 })
}

export async function fetchSampleWarehouseReview(sampleId: string): Promise<SampleWarehouseLoadResult> {
  if (!sampleId) throw new Error('缺少申请编号。')
  return (await apiClient.get<{ data: SampleWarehouseLoadResult }>(`/api/v1/sample-requests/${sampleId}/warehouse-review/`)).data.data
}

export async function saveSampleWarehouseReview(input: { sampleId: string; etag: string; draft: SampleWarehouseDraft; submit: boolean }): Promise<SampleWarehouseLoadResult> {
  if (!input.sampleId) throw new Error('缺少申请编号，请重新加载。')
  if (!input.etag) throw new Error('缺少材料版本，请重新加载。')
  const draft = { notes: input.draft.notes, lines: input.draft.lines.map(({ key, supplyQuantity }) => ({ key, supplyQuantity })) }
  return (await apiClient.put<{ data: SampleWarehouseLoadResult }>(`/api/v1/sample-requests/${input.sampleId}/warehouse-review/`, { draft, submit: input.submit }, { headers: { 'If-Match': input.etag } })).data.data
}
