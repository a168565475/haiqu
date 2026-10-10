import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import { confirmInternalReceipt, fetchMetalReceiptPreview, fetchReceiptPreview, fetchSemiReceiptRecord, fetchSemiReceiptRecords, findInternalReceipt } from './internalReceipts'
import type { ReceiptPayload } from '@/types/internalReceipt'
vi.mock('./request',()=>({apiClient:{get:vi.fn(),post:vi.fn()}}))
describe('厂内半成品入库接口契约',()=>{
  beforeEach(()=>vi.clearAllMocks())
  it('确认携带原请求编号和页面版本，超时不自动重发',async()=>{
    const payload:ReceiptPayload={request_id:'request-1',schedule_product_id:'plan-1',plan_category:'METAL',zone_id:'zone-1',receipt_date:'2026-09-28',remark:'',lines:[{bom_line_id:'part-1',quantity:'20'}]}
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error('timeout'))
    await expect(confirmInternalReceipt(payload,'"v1"')).rejects.toThrow('timeout')
    expect(apiClient.post).toHaveBeenCalledTimes(1)
    expect(apiClient.post).toHaveBeenCalledWith('/api/v1/semi-finished-receipts/',payload,{headers:{'If-Match':'"v1"'},timeout:30000})
  })
  it('列表只请求分页；用户查看后才请求来源详情',async()=>{
    vi.mocked(apiClient.get).mockResolvedValue({data:{data:{items:[],total:0}}})
    await fetchSemiReceiptRecords({page:2,source:'INTERNAL'})
    expect(apiClient.get).toHaveBeenCalledTimes(1)
    await fetchSemiReceiptRecord('movement-1')
    expect(apiClient.get).toHaveBeenLastCalledWith('/api/v1/semi-finished-receipts/movement-1/',{timeout:15000})
  })
  it('预览只带计划和工序，不提交采购批次或自算可入数量',async()=>{
    vi.mocked(apiClient.get).mockResolvedValueOnce({data:{data:{lines:[]}}})
    await fetchReceiptPreview('plan-1','SEWING')
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/semi-finished-receipts/preview/',{params:{schedule_product_id:'plan-1',plan_category:'SEWING'},timeout:15000})
  })
  it('新版金工预览沿同一入口且只传计划和METAL',async()=>{
    vi.mocked(apiClient.get).mockResolvedValueOnce({data:{data:{lines:[],metal_processing:{blockers:[]}}}})
    await fetchMetalReceiptPreview('plan-metal')
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/semi-finished-receipts/preview/',{params:{schedule_product_id:'plan-metal',plan_category:'METAL'},timeout:15000})
  })
  it('按原request_id只读回查，不隐式POST',async()=>{
    vi.mocked(apiClient.get).mockResolvedValueOnce({data:{data:{receipt_number:'RK-real'}}})
    expect(await findInternalReceipt('request-1')).toEqual({receipt_number:'RK-real'})
    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/semi-finished-receipts/by-request/request-1/',{timeout:15000})
    expect(apiClient.post).not.toHaveBeenCalled()
  })
})
