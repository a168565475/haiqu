import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from './request'
import { recoverSavedProductionTaskImport } from './productionTaskImports'

beforeEach(() => vi.restoreAllMocks())
describe('导入保存响应丢失后的恢复查询', () => {
  it('已有结果时读取原草稿，不创建新的任务或预留合同号', async () => {
    const get = vi.spyOn(apiClient, 'get')
      .mockResolvedValueOnce({ data: { data: { state: 'SAVED', saved_task_id: 'task-1' } }, headers: { etag: 'import-v2' } })
      .mockResolvedValueOnce({ data: { data: { id: 'task-1', status: 'DRAFT' } }, headers: { etag: 'task-v1' } })
    const post = vi.spyOn(apiClient, 'post')
    expect(await recoverSavedProductionTaskImport('import-1')).toEqual({ data: { id: 'task-1', status: 'DRAFT' }, etag: 'task-v1' })
    expect(get.mock.calls.map(call => call[0])).toEqual(['/api/v1/production-task-imports/import-1/', '/api/v1/production-tasks/task-1/'])
    expect(post).not.toHaveBeenCalled()
  })
  it('未保存才允许继续原核对流程，墓碑或查询失败均不会假装未保存', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValueOnce({ data: { data: { state: 'REVIEW' } }, headers: {} })
      .mockResolvedValueOnce({ data: { data: { state: 'SAVED', saved_task_id: null, saved_task_number: 'HT123' } }, headers: {} })
      .mockRejectedValueOnce(new Error('网络中断'))
    expect(await recoverSavedProductionTaskImport('import-1')).toBeNull()
    await expect(recoverSavedProductionTaskImport('import-1')).rejects.toThrow('不能重复建单')
    await expect(recoverSavedProductionTaskImport('import-1')).rejects.toThrow('网络中断')
  })
})
