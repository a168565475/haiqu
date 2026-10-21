import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  completeSchedule,
  createSchedule,
  createSchedulesBatch,
  fetchScheduleItems,
  fetchScheduleCompletionPreview,
  fetchTaskCandidate,
  scheduleProductImageUrl,
  updateSchedule,
  voidSchedule,
} from '@/api/productionScheduling'
import { apiClient } from '@/api/request'

vi.mock('@/api/request', () => ({
  apiClient: {
    defaults: { baseURL: 'http://localhost:8000' },
    get: vi.fn(), post: vi.fn(), patch: vi.fn(),
  },
}))

const mockedGet = vi.mocked(apiClient.get)
const mockedPost = vi.mocked(apiClient.post)
const mockedPatch = vi.mocked(apiClient.patch)

describe('生产排产 API', () => {
  beforeEach(() => {
    mockedGet.mockReset()
    mockedPost.mockReset()
    mockedPatch.mockReset()
  })

  it('完成预览从只读接口读取数量、状态和提交版本', async () => {
    const preview = { schedule_id: 's1', schedule_etag: '"s-v1"', products: [{ required_quantity: 200, received_quantity: 199 }] }
    mockedGet.mockResolvedValueOnce({ data: { data: preview } })
    expect(await fetchScheduleCompletionPreview('schedule/1')).toEqual(preview)
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/production-schedules/schedule%2F1/completion-preview/')
    expect(mockedPost).not.toHaveBeenCalled()
  })

  it('按真实任务 ID 读取可排产产品详情', async () => {
    mockedGet.mockResolvedValueOnce({ data: { data: { id: 'task/1' } } })
    await fetchTaskCandidate('task/1')
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/production-schedules/task-candidates/task%2F1/')
  })

  it('产品图片走排产权限端点并安全编码标识', () => {
    expect(scheduleProductImageUrl('task/1', 'file 1')).toBe(
      'http://localhost:8000/api/v1/production-schedules/task-files/task%2F1/file%201/',
    )
  })

  it('创建保留幂等标识、来源版本和全部产品字段', async () => {
    const payload = {
      production_task_id: 'task-1', source_revision_hash: 'a'.repeat(64), client_request_id: 'request-1',
      items: [{
        product_line_id: 'line-1', planned_quantity: 10,
        material_inbound_date: '2026-09-16', metal_return_date: '2026-09-20',
        sewing_return_date: '2026-09-23', finished_inbound_date: '2026-09-26', craft_ids: ['craft-1'],
      }],
    }
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'schedule-1' } }, headers: { etag: '"v1"' } })
    const result = await createSchedule(payload)
    expect(result.etag).toBe('"v1"')
    expect(mockedPost).toHaveBeenCalledWith('/api/v1/production-schedules/', payload)
  })

  it('批量生成使用单次事务接口并保留每张任务单的独立请求', async () => {
    const payload = {
      schedules: [
        {
          production_task_id: 'task-1', source_revision_hash: 'a'.repeat(64), client_request_id: 'request-1',
          items: [{
            product_line_id: 'line-1', planned_quantity: 10,
            material_inbound_date: '2026-09-16', metal_return_date: '2026-09-20',
            sewing_return_date: '2026-09-23', finished_inbound_date: '2026-09-26', craft_ids: ['craft-1'],
          }],
        },
        {
          production_task_id: 'task-2', source_revision_hash: 'b'.repeat(64), client_request_id: 'request-2',
          items: [{
            product_line_id: 'line-2', planned_quantity: 20,
            material_inbound_date: '2026-09-17', metal_return_date: '2026-09-21',
            sewing_return_date: '2026-09-24', finished_inbound_date: '2026-09-27', craft_ids: ['craft-2'],
          }],
        },
      ],
    }
    mockedPost.mockResolvedValueOnce({ data: { data: [{ id: 'schedule-1' }, { id: 'schedule-2' }] } })
    const result = await createSchedulesBatch(payload)
    expect(result.data).toHaveLength(2)
    expect(payload.schedules.map(item => item.client_request_id)).toEqual(['request-1', 'request-2'])
    expect(payload.schedules.map(item => item.source_revision_hash)).toEqual(['a'.repeat(64), 'b'.repeat(64)])
    expect(mockedPost).toHaveBeenCalledWith('/api/v1/production-schedules/batch/', payload)
  })

  it('编辑和整单作废都发送 If-Match 防并发覆盖', async () => {
    mockedPatch.mockResolvedValueOnce({ data: { data: { id: 'schedule-1' } }, headers: { etag: '"v2"' } })
    mockedPost.mockResolvedValueOnce({ data: { data: { id: 'schedule-1' } }, headers: { etag: '"v3"' } })
    const update = { source_revision_hash: 'b'.repeat(64), items: [] }
    await updateSchedule('schedule-1', update, '"v1"')
    await voidSchedule('schedule-1', '录入错误', '"v2"')
    expect(mockedPatch).toHaveBeenCalledWith(
      '/api/v1/production-schedules/schedule-1/', update, { headers: { 'If-Match': '"v1"' } },
    )
    expect(mockedPost).toHaveBeenCalledWith(
      '/api/v1/production-schedules/schedule-1/void/', { reason: '录入错误' },
      { headers: { 'If-Match': '"v2"' } },
    )
  })

  it('四类计划查询保留分类和来源上下文筛选', async () => {
    mockedGet.mockResolvedValueOnce({ data: { data: [], meta: {} } })
    const params = { category: 'METAL', schedule_id: 'schedule-1', schedule_product_id: 'product-1' }
    await fetchScheduleItems(params)
    expect(mockedGet).toHaveBeenCalledWith('/api/v1/production-schedule-items/', { params })
  })

  it('完成排产携带排产、任务和销售版本，返回销售同步结果', async () => {
    const payload = { task_etag: '"task-v2"', sales_order_etag: '"sales-v3"', reason: '生产完成' }
    const result = { production_task_status: 'COMPLETED', sales_sync: { status: 'SKIPPED', reason: '余款未结清。' } }
    mockedPost.mockResolvedValueOnce({ data: { data: result } })
    expect(await completeSchedule('schedule/1', payload, '"schedule-v1"')).toEqual(result)
    expect(mockedPost).toHaveBeenCalledWith('/api/v1/production-schedules/schedule%2F1/complete/', payload, { headers: { 'If-Match': '"schedule-v1"' } })
  })
})
