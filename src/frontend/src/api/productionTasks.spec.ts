import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createProductionOrderFromSalesOrder, decideProductionTaskByPmc, exportProductionTasks, fetchProductionTaskStats, updateProductionTask } from '@/api/productionTasks'
import { apiClient } from '@/api/request'

vi.mock('@/api/request', () => ({
  apiClient: {
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
  },
}))

const mockedGet = vi.mocked(apiClient.get)
const mockedPatch = vi.mocked(apiClient.patch)
const mockedPost = vi.mocked(apiClient.post)

describe('生产任务单 API', () => {
  beforeEach(() => {
    mockedGet.mockReset()
    mockedPatch.mockReset()
    mockedPost.mockReset()
  })

  it('统计接口接收当前非状态筛选', async () => {
    mockedGet.mockResolvedValueOnce({
      data: { data: { all: 1, draft: 1, pending_validation: 0, ready: 0, in_production: 0, completed: 0, paused: 0, cancelled: 0, split_delivery: 0 } },
    })

    await fetchProductionTaskStats({ search: 'HT-2609', salesperson_id: 'employee-1' })

    expect(mockedGet).toHaveBeenCalledWith('/api/v1/production-tasks/stats/', {
      params: { search: 'HT-2609', salesperson_id: 'employee-1' },
    })
  })

  it('PMC 确认使用专用入口并携带当前 ETag', async () => {
    mockedPost.mockResolvedValueOnce({
      data: { data: { id: 'task-1', status: 'READY' } },
      headers: { etag: '"task-v2"' },
    })

    const result = await decideProductionTaskByPmc('task-1', {
      decision: 'CONFIRM',
      planned_start_date: '2026-09-12',
      planned_end_date: '2026-09-20',
      planner_id: 'employee-1',
    }, '"task-v1"')

    expect(mockedPost).toHaveBeenCalledWith('/api/v1/production-tasks/task-1/pmc-decision/', {
      decision: 'CONFIRM',
      planned_start_date: '2026-09-12',
      planned_end_date: '2026-09-20',
      planner_id: 'employee-1',
    }, {
      headers: { 'If-Match': '"task-v1"' },
    })
    expect(result.etag).toBe('"task-v2"')
  })

  it('销售来源建单按一个交付批次提交多个颜色明细', async () => {
    mockedPost.mockResolvedValueOnce({
      data: { data: { id: 'task-1', task_number: 'MO-001' } },
      headers: { etag: '"task-v1"' },
    })
    const payload = {
      delivery_batch_id: 'batch-1',
      lines: [
        { delivery_batch_line_id: 'line-1', product_color_id: 'color-a', quantity: 6 },
        { delivery_batch_line_id: 'line-1', product_color_id: 'color-b', quantity: 4 },
      ],
      planned_start_date: null,
      planned_end_date: null,
      production_priority: 'NORMAL' as const,
      production_batch_number: 'PB-001',
      planner_id: null,
    }

    await createProductionOrderFromSalesOrder(payload)

    expect(mockedPost).toHaveBeenCalledWith('/api/v1/production-tasks/create-from-sales-order/', payload)
  })

  it('精确 PATCH 只提交实际修改字段并携带当前 ETag', async () => {
    mockedPatch.mockResolvedValueOnce({
      data: { data: { id: 'task-1', delivery_date: '2026-09-30' } },
      headers: { etag: '"task-v2"' },
    })

    await updateProductionTask('task-1', { delivery_date: '2026-09-30' }, {}, {}, '"task-v1"')

    const [, body, config] = mockedPatch.mock.calls[0]
    expect(body).toBeInstanceOf(FormData)
    expect(JSON.parse((body as FormData).get('payload') as string)).toEqual({ delivery_date: '2026-09-30' })
    expect(config).toEqual({ headers: { 'If-Match': '"task-v1"' } })
  })

  it('导出勾选项时移除分页参数并传递筛选条件', async () => {
    mockedPost.mockResolvedValueOnce({ data: new Blob(['csv']), headers: { 'x-export-count': '1' } })

    const result = await exportProductionTasks({ page: 3, page_size: 50, status: 'DRAFT', search: 'HT-' }, ['task-1'])

    expect(mockedPost).toHaveBeenCalledWith('/api/v1/production-tasks/export/', { ids: ['task-1'] }, {
      params: { page: undefined, page_size: undefined, status: 'DRAFT', search: 'HT-' },
      responseType: 'blob',
      timeout: 60_000,
    })
    expect(result.count).toBe(1)
  })

  it('已有交货批次日期按批次 ID 精确 PATCH，不夹带产品或批次数量', async () => {
    mockedPatch.mockResolvedValueOnce({
      data: { data: { id: 'task-1', delivery_date: '2026-09-30' } },
      headers: { etag: '"task-v2"' },
    })
    const payload = {
      delivery_date: '2026-09-30',
      delivery_batch_dates: [{ id: 'daac8411-c4ec-4c80-aee2-4d05d1be7b81', delivery_date: '2026-09-30' }],
    }

    const result = await updateProductionTask('task-1', payload, {}, {}, '"task-v1"')

    const [url, body, config] = mockedPatch.mock.calls[0]
    expect(url).toBe('/api/v1/production-tasks/task-1/')
    expect(body).toBeInstanceOf(FormData)
    expect(JSON.parse((body as FormData).get('payload') as string)).toEqual(payload)
    expect(Array.from((body as FormData).keys())).toEqual(['payload'])
    expect(config).toEqual({ headers: { 'If-Match': '"task-v1"' } })
    expect(result.etag).toBe('"task-v2"')
  })
})
