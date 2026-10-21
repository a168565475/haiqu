import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SampleDetail } from '@/types/sample'
import SampleParameterImages from './SampleParameterImages.vue'

enableAutoUnmount(afterEach)
const mocks = vi.hoisted(() => ({
  upload: vi.fn(), remove: vi.fn(), fetchFile: vi.fn(),
  success: vi.fn(), warning: vi.fn(), error: vi.fn(),
}))
vi.mock('@/api/samples', () => ({
  uploadSampleParameterImage: mocks.upload,
  deleteSampleParameterImage: mocks.remove,
  fetchSampleBusinessFile: mocks.fetchFile,
}))
vi.mock('element-plus', async importOriginal => ({
  ...await importOriginal<typeof import('element-plus')>(),
  ElMessage: { success: mocks.success, warning: mocks.warning, error: mocks.error },
}))

const sample = {
  id: 'sample-1', parameter_images: [],
  workflow_actions: { can_upload_metalwork: true, can_upload_cutting: true },
} as unknown as SampleDetail

function render() {
  return mount(SampleParameterImages, {
    props: { sample, etag: 'v1' },
    global: { stubs: { AppWindowDialog: true } },
  })
}

async function selectFiles(wrapper: ReturnType<typeof render>, files: File[]) {
  const input = wrapper.find('input[type="file"]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: files })
  await input.trigger('change')
  await flushPromises()
}

beforeEach(() => {
  vi.resetAllMocks()
  mocks.upload.mockResolvedValue({ data: sample, etag: 'v2' })
})

describe('参数图片上传反馈', () => {
  it('全部无效时只提示原因，不请求接口也不提示成功', async () => {
    const wrapper = render()
    const oversized = new File([new Uint8Array(5 * 1024 * 1024 + 1)], '过大.png', { type: 'image/png' })
    await selectFiles(wrapper, [oversized, new File([], '空图.png', { type: 'image/png' }), new File(['文字'], '说明.txt', { type: 'text/plain' })])
    expect(mocks.upload).not.toHaveBeenCalled()
    expect(mocks.success).not.toHaveBeenCalled()
    expect(mocks.warning).not.toHaveBeenCalled()
    expect(mocks.error).toHaveBeenCalledOnce()
    expect(mocks.error.mock.calls[0]![0]).toContain('过大.png')
    expect(mocks.error.mock.calls[0]![0]).toContain('空图.png')
    expect(mocks.error.mock.calls[0]![0]).toContain('说明.txt')
    expect(wrapper.emitted('saved')).toBeUndefined()
    expect(wrapper.find('input').attributes('disabled')).toBeUndefined()
  })

  it('成功数量按真实接口成功次数统计，并串行使用新版本', async () => {
    const wrapper = render()
    mocks.upload.mockResolvedValueOnce({ data: sample, etag: 'v2' }).mockResolvedValueOnce({ data: sample, etag: 'v3' })
    const first = new File(['图片1'], '1.png', { type: 'image/png' })
    const second = new File(['图片2'], '2.jpg', { type: 'image/jpeg' })
    await selectFiles(wrapper, [first, second])
    expect(mocks.upload).toHaveBeenNthCalledWith(1, 'sample-1', 'metalwork', first, 'v1')
    expect(mocks.upload).toHaveBeenNthCalledWith(2, 'sample-1', 'metalwork', second, 'v2')
    expect(mocks.success).toHaveBeenCalledWith('金工参数图片已上传 2 张。')
    expect(mocks.error).not.toHaveBeenCalled()
    expect(wrapper.emitted('saved')).toHaveLength(2)
  })

  it('部分有效时说明已上传数量及未上传原因', async () => {
    const wrapper = render()
    await selectFiles(wrapper, [new File(['图片'], '有效.png', { type: 'image/png' }), new File(['文字'], '无效.txt', { type: 'text/plain' })])
    expect(mocks.upload).toHaveBeenCalledOnce()
    expect(mocks.success).not.toHaveBeenCalled()
    expect(mocks.warning).toHaveBeenCalledWith(expect.stringContaining('已上传 1 张。其余图片未上传'))
    expect(mocks.warning.mock.calls[0]![0]).toContain('无效.txt')
  })

  it('部分成功后接口冲突会停止后续上传并保留准确成功数', async () => {
    const wrapper = render()
    mocks.upload.mockResolvedValueOnce({ data: sample, etag: 'v2' }).mockRejectedValueOnce({ response: { data: { error: { message: '数据版本已过期，请刷新。' } } } })
    await selectFiles(wrapper, ['1', '2', '3'].map(name => new File(['图片'], `${name}.png`, { type: 'image/png' })))
    expect(mocks.upload).toHaveBeenCalledTimes(2)
    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(mocks.success).not.toHaveBeenCalled()
    expect(mocks.warning).toHaveBeenCalledWith(expect.stringContaining('已上传 1 张。其余图片未上传：数据版本已过期'))
    expect(wrapper.find('input').attributes('disabled')).toBeUndefined()
  })

  it('首个接口失败时不提示上传成功', async () => {
    const wrapper = render()
    mocks.upload.mockRejectedValueOnce({ response: { data: { error: { field_errors: { file: ['图片扫描失败。'] } } } } })
    await selectFiles(wrapper, [new File(['图片'], '1.png', { type: 'image/png' })])
    expect(mocks.error).toHaveBeenCalledWith('图片扫描失败。')
    expect(mocks.success).not.toHaveBeenCalled()
    expect(mocks.warning).not.toHaveBeenCalled()
    expect(wrapper.emitted('saved')).toBeUndefined()
  })
})
