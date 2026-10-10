import { apiClient } from './request'
import type { AssemblyPayload,AssemblyPreview,AssemblyCandidate,FinishedRecord,FinishedLocation } from '@/types/finishedReceipts'
import type { FinishedGoodsInventoryRow } from '@/types/inventory'
const root='/api/v1/'
export async function fetchAssemblyPreview(id:string) { return (await apiClient.get<{data:AssemblyPreview}>(root+'assembly-finished-receipts/preview/',{params:{schedule_product_id:id},timeout:15000})).data.data }
export async function submitAssemblyReceipt(payload:AssemblyPayload,etag:string) { return (await apiClient.post<{data:{id:string;receipt_number:string;replayed:boolean}}>(root+'assembly-finished-receipts/',payload,{headers:{'If-Match':etag},timeout:30000})).data.data }
export async function fetchAssemblyCandidates(params:Record<string,unknown>) { return (await apiClient.get<{data:{items:AssemblyCandidate[];total:number}}>(root+'assembly-finished-receipts/candidates/',{params,timeout:15000})).data.data }
export async function fetchFinishedRecords(params:Record<string,unknown>) { return (await apiClient.get<{data:{items:FinishedRecord[];total:number}}>(root+'finished-goods-records/',{params,timeout:15000})).data.data }
export async function fetchFinishedRecord(id:string) { return (await apiClient.get<{data:FinishedRecord}>(root+`finished-goods-records/${id}/`,{timeout:15000})).data.data }
export async function fetchFinishedLocations(row:FinishedGoodsInventoryRow) {
 const params={product_id:row.product_id||undefined,unit_id:row.unit_id,zone_id:row.zone_id,product_number:row.product_number,product_code:row.product_code,product_name:row.product_name,item_number:row.item_number,category:row.category,specification:row.specification,actual_color:row.actual_color}
 return (await apiClient.get<{data:{items:FinishedLocation[]}}>(root+'finished-goods-records/locations/',{params,timeout:15000})).data.data.items
}
