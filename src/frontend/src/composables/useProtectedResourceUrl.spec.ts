import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, getActivePinia, setActivePinia } from 'pinia'
import { defineComponent, effectScope, ref, type EffectScope } from 'vue'
import { AxiosError, isCancel, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { ElImage } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/api/request'
import { installIdentityRequestGuard } from '@/api/identityGuard'
import { useAuthStore } from '@/stores/auth'
import type { AuthResponse } from '@/types/auth'
import type { BomLineInput } from '@/types/bom'
import ProtectedImage from '@/components/common/ProtectedImage.vue'
import ProtectedAttachmentLink from '@/components/common/ProtectedAttachmentLink.vue'
import ProductImage from '@/components/products/ProductImage.vue'
import BomLineImageSummary from '@/components/BomLineImageSummary.vue'
import BomLineImageManager from '@/views/boms/BomLineImageManager.vue'
import SampleParameterImages from '@/components/samples/SampleParameterImages.vue'
import type { SampleDetail } from '@/types/sample'
import { useProtectedResourceActions, useProtectedResourceUrl, useProtectedResourceUrls } from './useProtectedResourceUrl'

// 网络、对象 URL 和下载消费为测试替身；生命周期、Axios 保护、Vue 组件为实际实现。
const defaults = { adapter: apiClient.defaults.adapter, baseURL: apiClient.defaults.baseURL }
const scopes: EffectScope[] = [], wrappers: VueWrapper[] = []
const created = vi.fn(), revoked = vi.fn(), clicked = vi.fn()
let dispose: () => void
let serial = 0
const dialog = defineComponent({
  props: ['modelValue'], emits: ['update:modelValue'],
  template: '<section v-if="modelValue" data-dialog><button data-close @click="$emit(\'update:modelValue\', false)">关闭</button><slot/><slot name="footer"/></section>',
})
function identity(id = 1, version?: string): AuthResponse {
  return { authenticated: true, user: { id, username: `user${id}`, display_name: '单测', is_superuser: id === 1,
    employee: null, permissions: [], data_scope: 'ALL' },
  ...(version ? { account_switch: { active: id !== 1, can_return: id !== 1, identity_version: version } } : {}) }
}
function response(config: InternalAxiosRequestConfig, blob = new Blob(['png'], { type: 'image/png' })): AxiosResponse {
  return { config, data: blob, status: 200, statusText: 'OK', headers: {} }
}
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
function scoped<T>(factory: () => T): T {
  const scope = effectScope(); scopes.push(scope); return scope.run(factory)!
}
function render(component: Parameters<typeof mount>[0], props: Record<string, unknown> = {}): VueWrapper {
  const wrapper = mount(component, {
    props, global: {
      plugins: [getActivePinia()!],
      stubs: { AppWindowDialog: dialog, ElButton: { template: '<button><slot/></button>' }, ElIcon: { template: '<span><slot/></span>' } },
    },
  })
  wrappers.push(wrapper); return wrapper
}
beforeEach(() => {
  setActivePinia(createPinia())
  const auth = useAuthStore(); auth.applyAuthResponse(identity())
  apiClient.defaults.baseURL = 'https://api.test'
  apiClient.defaults.adapter = async config => response(config)
  dispose = installIdentityRequestGuard(apiClient, () => ({ generation: auth.identityRequestGeneration,
    version: auth.identityVersion, blocked: !auth.identityReady }), () => auth.requireIdentityRevalidation())
  serial = 0; created.mockReset().mockImplementation(() => `blob:owned-${++serial}`); revoked.mockReset(); clicked.mockReset()
  vi.stubGlobal('URL', class extends URL { static createObjectURL = created; static revokeObjectURL = revoked })
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { clicked({ href: this.href, filename: this.download }) })
})
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount()); scopes.splice(0).forEach(scope => scope.stop())
  dispose(); Object.assign(apiClient.defaults, defaults); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers()
})

describe('资源归属和清理', () => {
  it('普通登录→A→B→同B新版本→管理员，旧实例失效，新实例按当前版本读取', async () => {
    const auth = useAuthStore()
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => response(config)); apiClient.defaults.adapter = adapter
    let previous: ReturnType<typeof useProtectedResourceUrl> | undefined
    for (const [id, version] of [[1, undefined], [2, 'A1'], [3, 'B1'], [3, 'B2'], [1, 'ADMIN2']] as const) {
      auth.applyAuthResponse(identity(id, version))
      if (previous) expect(previous.url.value).toBe('')
      const resource = scoped(() => useProtectedResourceUrl('/api/v1/image/'))
      await flushPromises()
      expect(resource.url.value).toBe(`blob:owned-${serial}`)
      expect(adapter.mock.calls.at(-1)![0].headers.get('X-Identity-Version') || undefined).toBe(version)
      previous = resource
    }
    expect(revoked).toHaveBeenCalledTimes(4)
    auth.applyAuthResponse(identity(1, 'ADMIN2'))
    expect(previous!.active.value).toBe(true) // 同身份 /me 不应销毁资源。
  })

  it.each(['identityTransitionPending', 'identityRevalidationRequired'] as const)('%s 立即取消请求，不应用晚到结果或自动以新身份重读', async field => {
    const auth = useAuthStore(), pending = deferred<AxiosResponse>()
    let config!: InternalAxiosRequestConfig
    const adapter = vi.fn((value: InternalAxiosRequestConfig) => { config = value; return pending.promise }); apiClient.defaults.adapter = adapter
    const source = ref('/api/v1/old/'), resource = scoped(() => useProtectedResourceUrl(source))
    await flushPromises(); auth[field] = true
    expect(config.signal?.aborted).toBe(true); expect(resource.active.value).toBe(false)
    auth[field] = false; source.value = '/api/v1/new/'
    pending.resolve(response(config)); await flushPromises()
    expect(resource.url.value).toBe(''); expect(resource.error.value).toBe(false)
    expect(created).not.toHaveBeenCalled(); expect(adapter).toHaveBeenCalledOnce()
  })

  it('URL A→B 乱序：取消 A，只创建 B 的 URL，卸载精确回收', async () => {
    const pending = [deferred<AxiosResponse>(), deferred<AxiosResponse>()], configs: InternalAxiosRequestConfig[] = []
    apiClient.defaults.adapter = config => { configs.push(config); return pending[configs.length - 1]!.promise }
    const source = ref('/api/v1/A/'), resource = scoped(() => useProtectedResourceUrl(source))
    await flushPromises(); source.value = '/api/v1/B/'; await flushPromises()
    expect(configs[0]!.signal?.aborted).toBe(true)
    const blobB = new Blob(['B'], { type: 'image/png' })
    pending[1]!.resolve(response(configs[1]!, blobB)); await flushPromises()
    pending[0]!.resolve(response(configs[0]!)); await flushPromises()
    expect(created).toHaveBeenCalledExactlyOnceWith(blobB); expect(resource.url.value).toBe('blob:owned-1')
    scopes[0]!.stop(); expect(revoked).toHaveBeenCalledExactlyOnceWith('blob:owned-1')
  })

  it('静态、本地 Blob/data 不走 API、不释放调用方 URL；API 列表去重且移除即清理', async () => {
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => response(config)); apiClient.defaults.adapter = adapter
    const sources = ref(['blob:caller', 'data:image/png;base64,eA==', '/assets/1.png', '/api/v1/1/', '/api/v1/1/'])
    const resources = scoped(() => useProtectedResourceUrls(sources)); await flushPromises()
    expect(adapter).toHaveBeenCalledOnce(); expect(resources.urls.value.slice(0, 3)).toEqual(sources.value.slice(0, 3))
    sources.value = ['blob:caller']; await flushPromises()
    expect(revoked).toHaveBeenCalledExactlyOnceWith('blob:owned-1'); scopes[0]!.stop()
    expect(revoked).not.toHaveBeenCalledWith('blob:caller')
  })

  it('无权限保留失败状态，无原 API 回退；卸载后拒绝不生成新错误', async () => {
    apiClient.defaults.adapter = async config => { throw new AxiosError('无权', undefined, config, undefined, { ...response(config), status: 403 }) }
    const resource = scoped(() => useProtectedResourceUrl('/api/v1/image/')); await flushPromises()
    expect(resource.error.value).toBe(true); expect(resource.url.value).toBe(''); expect(created).not.toHaveBeenCalled()
    scopes[0]!.stop(); expect(resource.error.value).toBe(false)
  })

  it('卸载后晚到成功不能创建 Blob URL', async () => {
    const pending = deferred<AxiosResponse>(); let config!: InternalAxiosRequestConfig
    apiClient.defaults.adapter = value => { config = value; return pending.promise }
    scoped(() => useProtectedResourceUrl('/api/v1/late/')); await flushPromises(); scopes[0]!.stop()
    expect(config.signal?.aborted).toBe(true); pending.resolve(response(config)); await flushPromises()
    expect(created).not.toHaveBeenCalled()
  })
})

describe('图片预览和下载动作', () => {
  it('预览关闭、乱序和卸载后晚到均取消，不打开旧图片', async () => {
    const pending = [deferred<AxiosResponse>(), deferred<AxiosResponse>()], configs: InternalAxiosRequestConfig[] = []
    apiClient.defaults.adapter = config => { configs.push(config); return pending[configs.length - 1]!.promise }
    const actions = scoped(useProtectedResourceActions)
    const old = actions.preview('/api/v1/A/').catch(error => error); await flushPromises(); actions.closePreview()
    const current = actions.preview('/api/v1/B/', '原图.png'); await flushPromises()
    pending[1]!.resolve(response(configs[1]!)); await current
    pending[0]!.resolve(response(configs[0]!)); expect(isCancel(await old)).toBe(true)
    expect(actions.previewName.value).toBe('原图.png'); expect(created).toHaveBeenCalledOnce()
    actions.closePreview(); expect(actions.previewUrl.value).toBe(''); expect(revoked).toHaveBeenCalledOnce()
  })

  it.each(['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'image/svg+xml', 'text/html'])('非图片 %s 不建立可执行预览或假装下载完成', async type => {
    apiClient.defaults.adapter = async config => response(config, new Blob(['document'], { type }))
    const actions = scoped(useProtectedResourceActions)
    await expect(actions.preview('/api/v1/file/')).rejects.toThrow()
    expect(created).not.toHaveBeenCalled(); expect(clicked).not.toHaveBeenCalled()
  })

  it('下载保留文件内容、名称和版本；点击后延迟释放，结束不残留计时器', async () => {
    vi.useFakeTimers()
    const blob = new Blob(['xlsx'], { type: 'application/octet-stream' })
    apiClient.defaults.adapter = async config => response(config, blob)
    const actions = scoped(useProtectedResourceActions)
    await actions.download('/api/v1/template/', '联系人模板.xlsx')
    expect(created).toHaveBeenCalledExactlyOnceWith(blob)
    expect(clicked).toHaveBeenCalledExactlyOnceWith({ href: 'blob:owned-1', filename: '联系人模板.xlsx' })
    expect(revoked).not.toHaveBeenCalled(); await vi.advanceTimersByTimeAsync(30_000)
    expect(revoked).toHaveBeenCalledExactlyOnceWith('blob:owned-1'); expect(vi.getTimerCount()).toBe(0)
  })

  it.each(['identity', 'reset', 'unmount'])('下载中 %s 使晚到响应失效，不触发下载', async change => {
    const pending = deferred<AxiosResponse>(); let config!: InternalAxiosRequestConfig
    apiClient.defaults.adapter = value => { config = value; return pending.promise }
    const actions = scoped(useProtectedResourceActions), request = actions.download('/api/v1/file/').catch(error => error)
    await flushPromises()
    if (change === 'identity') useAuthStore().applyAuthResponse(identity(2, 'A1'))
    else if (change === 'reset') actions.reset()
    else scopes[0]!.stop()
    expect(config.signal?.aborted).toBe(true); pending.resolve(response(config))
    expect(isCancel(await request)).toBe(true); expect(clicked).not.toHaveBeenCalled(); expect(created).not.toHaveBeenCalled()
  })
})

describe('实际消费组件', () => {
  it('ProtectedImage 保持 img 布局属性，失败透传真实事件，无原链接回退', async () => {
    apiClient.defaults.adapter = async config => { throw new AxiosError('无权限', undefined, config, undefined, { ...response(config), status: 403 }) }
    const wrapper = render(ProtectedImage, { src: '/api/v1/no-access/', alt: '产品', class: 'existing-thumb' })
    await flushPromises()
    expect(wrapper.get('img').classes()).toContain('existing-thumb'); expect(wrapper.get('img').attributes('src')).toBeUndefined()
    const event = wrapper.emitted('error')![0]![0] as Event
    expect(event.target).toBe(wrapper.get('img').element)
    useAuthStore().requireIdentityRevalidation(); await flushPromises(); expect(wrapper.find('img').exists()).toBe(false)
  })

  it('ProductImage 缩略与弹窗共用一份读取，版本变化关闭并清理', async () => {
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => response(config)); apiClient.defaults.adapter = adapter
    const wrapper = render(ProductImage, { src: '/api/v1/product/', name: '产品原图' }); await flushPromises()
    await wrapper.get('button.product-image').trigger('click'); await flushPromises()
    expect(wrapper.findAll('img')).toHaveLength(2); expect(adapter).toHaveBeenCalledOnce()
    expect(created.mock.calls[0]![0]).toBeInstanceOf(Blob)
    useAuthStore().applyAuthResponse(identity(1, 'ADMIN2')); await flushPromises()
    expect(wrapper.find('[data-dialog]').exists()).toBe(false); expect(wrapper.find('img').exists()).toBe(false)
    expect(revoked).toHaveBeenCalledOnce()
  })

  it('BOM 前三张缩略及第四张预览均受保护，按序去重，身份变化卸载整个预览消费方', async () => {
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => response(config)); apiClient.defaults.adapter = adapter
    const line = { images: [1, 2, 3, 4].map(position => ({ id: `i${position}`, position, content_url: `/api/v1/bom-images/${position}/` })), draft_images: [] } as unknown as BomLineInput
    const wrapper = render(BomLineImageSummary, { line }); await flushPromises()
    expect(adapter).toHaveBeenCalledTimes(4); expect(created).toHaveBeenCalledTimes(4)
    const images = wrapper.findAllComponents(ElImage)
    expect(images).toHaveLength(3)
    expect(images[2]!.props('initialIndex')).toBe(2)
    expect(images[0]!.props('previewSrcList')).toEqual(['blob:owned-1', 'blob:owned-2', 'blob:owned-3', 'blob:owned-4'])
    useAuthStore().applyAuthResponse(identity(2, 'A1')); await flushPromises()
    expect(wrapper.findComponent(ElImage).exists()).toBe(false); expect(revoked).toHaveBeenCalledTimes(4)
  })

  it('附件链接不暴露原 API href；模板下载保留类名和文件名', async () => {
    const wrapper = render(ProtectedAttachmentLink, { src: '/api/v1/contact-imports/template/?scope=global', filename: 'contact_import_template.xlsx', download: true, class: 'template-link' })
    expect(wrapper.get('a').attributes('href')).toBeUndefined(); expect(wrapper.get('a').classes()).toContain('template-link')
    await wrapper.get('a').trigger('click'); await flushPromises()
    expect(clicked).toHaveBeenCalledWith({ href: 'blob:owned-1', filename: 'contact_import_template.xlsx' })
    wrapper.unmount(); expect(revoked).toHaveBeenCalledOnce()
  })

  it('附件弹窗读取中关闭取消请求，晚到不打开弹窗、不写错误', async () => {
    const pending = deferred<AxiosResponse>(); let config!: InternalAxiosRequestConfig
    apiClient.defaults.adapter = value => { config = value; return pending.promise }
    const wrapper = render(ProtectedAttachmentLink, { src: '/api/v1/file/' })
    await wrapper.get('a').trigger('click'); await flushPromises(); await wrapper.get('[data-close]').trigger('click')
    expect(config.signal?.aborted).toBe(true); pending.resolve(response(config)); await flushPromises()
    expect(wrapper.find('[data-dialog]').exists()).toBe(false); expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(created).not.toHaveBeenCalled()
  })

  it('非图片明确提示预览缺口，仍可通过独立按钮受控下载原文件', async () => {
    const pdf = new Blob(['%PDF-unit'], { type: 'application/pdf' })
    apiClient.defaults.adapter = async config => response(config, pdf)
    const wrapper = render(ProtectedAttachmentLink, { src: '/api/v1/evidence/', filename: '凭证.pdf' })
    await wrapper.get('a').trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('安全预览尚未接入')
    expect(created).not.toHaveBeenCalled(); expect(clicked).not.toHaveBeenCalled()
    await wrapper.findAll('button').find(button => button.text() === '下载原文件')!.trigger('click'); await flushPromises()
    expect(created).toHaveBeenCalledExactlyOnceWith(pdf)
    expect(clicked).toHaveBeenCalledExactlyOnceWith({ href: 'blob:owned-1', filename: '凭证.pdf' })
    expect(wrapper.get('[role="alert"]').text()).toContain('安全预览尚未接入')
  })

  it('BOM 管理弹窗关闭后取消整组请求，晚到不保留资源，重开正常读取', async () => {
    const pending = deferred<AxiosResponse>(); let config!: InternalAxiosRequestConfig
    apiClient.defaults.adapter = value => { config = value; return pending.promise }
    const line = { images: [{ id: 'one', position: 1, name: '用料.png', size_bytes: 3, content_url: '/api/v1/bom-image/' }] } as unknown as BomLineInput
    const wrapper = render(BomLineImageManager, { modelValue: true, line }); await flushPromises()
    await wrapper.setProps({ modelValue: false }); expect(config.signal?.aborted).toBe(true)
    pending.resolve(response(config)); await flushPromises(); expect(created).not.toHaveBeenCalled()
    apiClient.defaults.adapter = async config => response(config)
    await wrapper.setProps({ modelValue: true }); await flushPromises(); expect(created).toHaveBeenCalledOnce()
  })

  it('样品参数图预览读取中关闭后不迟到显示，身份变化清理缩略图', async () => {
    const sample = { id: 'sample-1', parameter_images: [{ id: 'image-1', file_id: 'file-1', file_name: '参数.png', parameter_type: 'METALWORK' }], workflow_actions: {} } as unknown as SampleDetail
    const wrapper = render(SampleParameterImages, { sample, etag: 'v1' }); await flushPromises()
    expect(created).toHaveBeenCalledOnce()
    const pending = deferred<AxiosResponse>(); let config!: InternalAxiosRequestConfig
    apiClient.defaults.adapter = value => { config = value; return pending.promise }
    await wrapper.get('.thumbnail-preview').trigger('click'); await flushPromises()
    await wrapper.get('[data-close]').trigger('click'); expect(config.signal?.aborted).toBe(true)
    pending.resolve(response(config)); await flushPromises(); expect(created).toHaveBeenCalledOnce()
    expect(wrapper.find('[data-dialog]').exists()).toBe(false)
    useAuthStore().applyAuthResponse(identity(2, 'A1')); await flushPromises()
    expect(wrapper.find('img').exists()).toBe(false); expect(revoked).toHaveBeenCalledOnce()
  })
})
