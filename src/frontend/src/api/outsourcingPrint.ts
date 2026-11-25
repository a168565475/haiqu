import { apiClient } from './request'
import type { OutsourcingPrintKind } from '@/types/outsourcingPrint'
import type { UnifiedOutsourcingOrder } from '@/types/unifiedOutsourcing'

export async function fetchOutsourcingPrintPdf(
  record: Pick<UnifiedOutsourcingOrder, 'id' | 'record_type'>,
  kind: OutsourcingPrintKind,
  warehouse = false,
): Promise<Blob> {
  const resource = record.record_type === 'TUBE' ? 'tube-outsourcing-orders' : 'outsourcing-orders'
  const response = await apiClient.get<Blob>(`/api/v1/${resource}/${encodeURIComponent(record.id)}/print-pdf/`, {
    params: { kind, ...(warehouse ? { warehouse_stage: 'all' } : {}) },
    responseType: 'blob',
    timeout: 30000,
  })
  return response.data
}
