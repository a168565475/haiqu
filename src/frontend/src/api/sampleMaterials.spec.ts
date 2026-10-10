import { describe, expect, it, vi } from 'vitest'
import { fetchSampleMaterialUnits, fetchSampleMaterials, saveSampleMaterials } from './sampleMaterials'
import { apiClient } from './request'
vi.mock('./request', () => ({ apiClient: { get: vi.fn(), put: vi.fn() } }))
describe('打样材料单位', () => {
  it('读取生产单位并提供材料接口最多四位小数的约束', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { data: [{ id: 'unit', label: '米', decimalPlaces: 4 }] } })
    expect(await fetchSampleMaterialUnits()).toEqual([{ id: 'unit', label: '米', decimalPlaces: 4 }])
  })
  it('读取真实草稿并携带版本保存到专用接口', async () => {
    const result = { available: true, draft: { lines: [], notes: '' }, etag: 'v2', canEdit: true }
    vi.mocked(apiClient.get).mockResolvedValue({ data: { data: result } })
    vi.mocked(apiClient.put).mockResolvedValue({ data: { data: result } })
    expect(await fetchSampleMaterials('id')).toEqual(result)
    expect(await saveSampleMaterials({ sampleId: 'id', etag: 'v1', draft: result.draft, submit: false })).toEqual(result)
    expect(apiClient.put).toHaveBeenCalledWith('/api/v1/sample-requests/id/materials/', { draft: result.draft, submit: false }, { headers: { 'If-Match': 'v1' } })
  })
  it('版本缺失时阻止写入', async () => {
    await expect(saveSampleMaterials({ sampleId: 'id', etag: '', draft: { lines: [], notes: '' }, submit: true })).rejects.toThrow('版本')
  })
})
