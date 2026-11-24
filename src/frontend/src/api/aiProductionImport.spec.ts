import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'
import { apiClient } from './request'
import { aiImportErrorMessage, createAiProductionBoms, createAiProductionTaskDraft, fetchAiOpenAiConfig, fetchAiProductionImport, matchAiProductionMaterials, restoreAiImportReview, saveAiImportReview, saveAiOpenAiConfig, selectAiImportTask, uploadAiProductionImport } from './aiProductionImport'

vi.mock('./request', () => ({ apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }))

beforeEach(() => vi.resetAllMocks())

describe('AI 生产任务导入 OpenAI 配置 API', () => {
  it('读取后端 data 数组响应中的第一条配置', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        data: [{
          id: 'config-1', label: '生产任务导入', provider: 'openai', model: 'gpt-6-astra',
          key_configured: true, key_last4: 'test', key_fingerprint: 'fingerprint', updated_at: null,
        }],
        meta: { page: 1, page_size: 20, total: 1, total_pages: 1 },
      },
      headers: { etag: 'config-v1' },
    })

    const result = await fetchAiOpenAiConfig()

    expect(result.data.id).toBe('config-1')
    expect(result.data.key_configured).toBe(true)
    expect(result.etag).toBe('config-v1')
    expect(apiClient.get).toHaveBeenCalledTimes(1)
  })

  it('列表没有 ETag 时读取配置详情，使用详情数据与版本号', async () => {
    vi.mocked(apiClient.get)
      .mockResolvedValueOnce({ data: { data: [{ id: 'config-1', model: 'old-model' }] }, headers: {} })
      .mockResolvedValueOnce({ data: { data: { id: 'config-1', model: 'current-model', key_configured: true, document_reasoning_effort: 'max', material_reasoning_effort: 'low' } }, headers: { etag: 'config-v2' } })
    const result = await fetchAiOpenAiConfig()
    expect(apiClient.get).toHaveBeenNthCalledWith(2, '/api/v1/ai-openai-configs/config-1/')
    expect(result.data.model).toBe('current-model')
    expect(result.data).toMatchObject({ document_reasoning_effort: 'max', material_reasoning_effort: 'low' })
    expect(result.etag).toBe('config-v2')
  })

  it('只修改已有配置的模型时省略空白 Key，并带上并发版本', async () => {
    const payload = { label: '生产任务导入', provider: 'openai', model: 'updated-model', api_key: '  ' }
    vi.mocked(apiClient.patch).mockResolvedValue({ data: { data: { id: 'config-1', model: 'updated-model' } }, headers: { etag: 'config-v3' } })
    await saveAiOpenAiConfig(payload, 'config-v2', 'config-1')
    expect(apiClient.patch).toHaveBeenCalledWith('/api/v1/ai-openai-configs/config-1/', {
      label: '生产任务导入', provider: 'openai', model: 'updated-model',
    }, { headers: { 'If-Match': 'config-v2' } })
    expect(payload.api_key).toBe('  ')
  })

  it('新增配置仍提交首次输入的 Key', async () => {
    const payload = { label: '生产任务导入', provider: 'openai', model: 'selected-model', api_key: 'test-key' }
    vi.mocked(apiClient.post).mockResolvedValue({ data: { data: { id: 'config-1' } }, headers: { etag: 'config-v1' } })
    await saveAiOpenAiConfig(payload)
    expect(apiClient.post).toHaveBeenCalledWith('/api/v1/ai-openai-configs/', payload, { headers: undefined })
    expect(apiClient.patch).not.toHaveBeenCalled()
  })
})

describe('AI 导入接口契约', () => {
  const payload = {
    id: 'import-1', state: 'REVIEW', phase: 'recognition', original_name: 'task.xlsx', result: {},
    issues: [{ issue_key: 'conflict-1', kind: 'CONFLICT', message: '两个数量不一致，请核对。', source_ids: ['src_a'] }],
    sources: { src_a: { kind: 'cell', sheet: '生产单', ref: 'C8', text: '300' } },
  }

  it('上传等待上限覆盖服务端识别时间，来源字典和问题字段适配为预览数据', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { data: payload }, headers: { etag: 'v1' } })
    const result = await uploadAiProductionImport(new File(['xlsx'], 'task.xlsx'), 'request-1')
    expect(apiClient.post).toHaveBeenCalledWith('/api/v1/ai-production-imports/', expect.any(FormData), { timeout: 1_230_000 })
    expect(result.data.sources).toEqual([{ source_id: 'src_a', kind: 'cell', sheet: '生产单', ref: 'C8', cell_range: 'C8', text: '300' }])
    expect(result.data.issues[0]).toMatchObject({ id: 'conflict-1', code: 'CONFLICT', severity: 'warning', source_refs: ['src_a'] })
  })

  it('重新读取已保存结果保留来源并发版本，不再次上传', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { data: payload }, headers: { etag: 'v2' } })
    const result = await fetchAiProductionImport('import-1')
    expect(result.etag).toBe('v2')
    expect(result.data.sources[0]?.cell_range).toBe('C8')
    expect(apiClient.post).not.toHaveBeenCalled()
  })

  it('材料AI对应使用独立接口、当前版本及630秒等待上限，保留返回草稿', async () => {
    const review = { task_payload: { task_number: '人工确认单号' }, bom_plans: [{ product_key: 'p1', sections: [] }] }
    vi.mocked(apiClient.post).mockResolvedValue({ data: { data: { ...payload, review_draft: review } }, headers: { etag: 'v3' } })
    const result = await matchAiProductionMaterials('import/1', 'v2')
    expect(apiClient.post).toHaveBeenCalledWith('/api/v1/ai-production-imports/import%2F1/match-materials/', {}, { headers: { 'If-Match': 'v2' }, timeout: 630_000 })
    expect(result.etag).toBe('v3')
    expect(result.data.review_draft).toEqual(review)
  })

  it('错误包装的 detail 优先于通用错误码', () => {
    const error = new AxiosError('Request failed', undefined, undefined, undefined, {
      status: 400, data: { error: { message: 'OPENAI_REQUEST_FAILED', field_errors: { code: 'OPENAI_TIMEOUT', detail: ['OpenAI 识别超时，请稍后重试。'] } } },
    } as never)
    expect(aiImportErrorMessage(error, '识别失败')).toBe('OpenAI 识别超时，请稍后重试。')
    error.response!.data = { error: { message: 'OPENAI_REQUEST_FAILED' } }
    expect(aiImportErrorMessage(error, '识别失败')).toBe('识别失败')
  })

  it('切换任务提交任务键和版本，并保留返回的任务及核对稿', async () => {
    const selected = { ...payload, active_task_key: 'second', review_draft: { task_payload: { task_number: 'HT26150' }, bom_plans: [] } }
    vi.mocked(apiClient.post).mockResolvedValue({ data: { data: selected }, headers: { etag: 'v3' } })
    const result = await selectAiImportTask('import/1', 'second', 'v2')
    expect(apiClient.post).toHaveBeenCalledWith('/api/v1/ai-production-imports/import%2F1/select-task/', { task_key: 'second' }, { headers: { 'If-Match': 'v2' } })
    expect(result.etag).toBe('v3'); expect(result.data.active_task_key).toBe('second'); expect(result.data.review_draft).toEqual(selected.review_draft)
  })

  it('保存核对稿按任务键提交，两区块不拆散', async () => {
    const review = { task_key: 'second', task_payload: { task_number: 'HT26150' }, bom_plans: [{ product_key: 'p2' }] }
    vi.mocked(apiClient.patch).mockResolvedValue({ data: { data: { ...payload, review_draft: review } }, headers: { etag: 'v4' } })
    const result = await saveAiImportReview('import-1', review, 'v3')
    expect(apiClient.patch).toHaveBeenCalledWith('/api/v1/ai-production-imports/import-1/', review, { headers: { 'If-Match': 'v3' } })
    expect(result.data.review_draft).toEqual(review); expect(result.etag).toBe('v4')
  })

  it('恢复上一版核对稿携带并发版本，返回原识别内容和核对稿', async () => {
    const restored = { ...payload, active_task_key: 'main', result: { task: { task_number: { value: 'HT26148' } } }, review_draft: { task_payload: { task_number: 'HT26148-核对' }, bom_plans: [] } }
    vi.mocked(apiClient.post).mockResolvedValue({ data: { data: restored }, headers: { etag: 'v5' } })
    const result = await restoreAiImportReview('import/1', 'v4')
    expect(apiClient.post).toHaveBeenCalledWith('/api/v1/ai-production-imports/import%2F1/restore-review/', {}, { headers: { 'If-Match': 'v4' } })
    expect(result.data.result).toEqual(restored.result); expect(result.data.review_draft).toEqual(restored.review_draft); expect(result.etag).toBe('v5')
  })

  it('创建任务和 BOM 都携带选中任务键及版本，旧调用可省略任务键', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { data: payload }, headers: { etag: 'v5' } })
    const task = { task_number: 'HT26150' }, plans = [{ product_key: 'p2' }]
    await createAiProductionTaskDraft('import-1', task, 'v4', 'second')
    expect(apiClient.post).toHaveBeenLastCalledWith('/api/v1/ai-production-imports/import-1/create-task/', { payload: task, task_key: 'second' }, { headers: { 'If-Match': 'v4' } })
    await createAiProductionBoms('import-1', plans, 'v5', 'second')
    expect(apiClient.post).toHaveBeenLastCalledWith('/api/v1/ai-production-imports/import-1/create-boms/', { plans, task_key: 'second' }, { headers: { 'If-Match': 'v5' } })
    await createAiProductionTaskDraft('import-1', task)
    expect(apiClient.post).toHaveBeenLastCalledWith('/api/v1/ai-production-imports/import-1/create-task/', { payload: task }, { headers: undefined })
  })

  it('区分浏览器超时和网络错误，不显示原始请求或重复提交', () => {
    expect(aiImportErrorMessage(new AxiosError('private', 'ECONNABORTED'), '失败')).toContain('等待识别结果超时')
    expect(aiImportErrorMessage(new AxiosError('private', 'ERR_NETWORK'), '失败')).toContain('无法连接识别服务')
  })
})
