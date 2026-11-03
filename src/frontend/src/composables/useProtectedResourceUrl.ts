import { getActivePinia } from 'pinia'
import { computed, onScopeDispose, ref, toValue, watch, type MaybeRefOrGetter } from 'vue'
import { CanceledError, isCancel } from 'axios'
import { useAuthStore } from '@/stores/auth'
import {
  fetchProtectedResource, isSafeResourceImage, locateResource, safeResourceFilename,
  type ResourceReadOptions, type ResourceSource,
} from '@/api/protectedResources'

type ReadOptions = Pick<ResourceReadOptions, 'timeout'>
const canceled = () => new CanceledError('Protected resource owner is no longer usable')

/** One verified identity and one component scope, never rebound to a later identity. */
function useResourceOwner() {
  // Static/local images also work outside the application (e.g. standalone display).
  // A missing authentication context never permits a protected request.
  const auth = getActivePinia() ? useAuthStore() : null
  const context = () => [auth?.user?.id, auth?.identityGeneration, auth?.identityRequestGeneration,
    auth?.identityVersion, auth?.identityReady] as const
  const snapshot = context()
  const verified = snapshot[4] === true && snapshot[0] != null
  const active = ref(auth ? verified : true)
  const controllers = new Set<AbortController>()
  const urls = new Set<string>()
  const invalidators = new Set<() => void>()
  const matches = () => context().every((value, index) => value === snapshot[index])
  function assertCurrent() {
    if (!active.value || !verified || !matches()) throw canceled()
  }
  function releaseUrl(url: string) {
    if (urls.delete(url)) URL.revokeObjectURL(url)
  }
  function cancelResources() {
    for (const controller of controllers) controller.abort()
    controllers.clear()
    for (const url of [...urls]) releaseUrl(url)
  }
  function invalidate() {
    if (!active.value) return
    active.value = false
    cancelResources()
    for (const invalidateResource of invalidators) invalidateResource()
    invalidators.clear()
  }
  watch(context, (current, previous) => {
    // /me 会替换 user 对象；只有身份值变化才失效，不能按数组引用判断。
    if (current.some((value, index) => value !== previous[index])) invalidate()
  }, { flush: 'sync' })
  onScopeDispose(invalidate)
  return {
    active, assertCurrent, releaseUrl, cancelResources,
    createController() {
      assertCurrent()
      const controller = new AbortController()
      controllers.add(controller)
      return controller
    },
    finishController(controller: AbortController) { controllers.delete(controller) },
    ownUrl(blob: Blob) {
      assertCurrent()
      const url = URL.createObjectURL(blob)
      // Also defend against a synchronous owner change during an injected URL factory.
      urls.add(url)
      try { assertCurrent() } catch (error) { releaseUrl(url); throw error }
      return url
    },
    onInvalidate(callback: () => void) {
      if (active.value) invalidators.add(callback)
      else callback()
    },
  }
}

/** A parent-owned, incrementally deduplicated image collection, including preview-only entries. */
export function useProtectedResourceUrls(
  sources: MaybeRefOrGetter<readonly ResourceSource[]>, options: ReadOptions = {},
) {
  const owner = useResourceOwner()
  interface Entry { url: string; error: boolean; controller?: AbortController }
  const entries = new Map<string, Entry>()
  const revision = ref(0)
  function remove(key: string, entry: Entry) {
    entry.controller?.abort()
    if (entry.controller) owner.finishController(entry.controller)
    if (entry.url) owner.releaseUrl(entry.url)
    entries.delete(key)
  }
  function clear() {
    for (const [key, entry] of entries) remove(key, entry)
    revision.value++
  }
  owner.onInvalidate(clear)
  async function load(key: string, url: string, entry: Entry) {
    const assertEntry = () => {
      owner.assertCurrent()
      if (entries.get(key) !== entry) throw canceled()
    }
    try {
      assertEntry()
      const controller = owner.createController()
      entry.controller = controller
      const result = await fetchProtectedResource(url, { ...options, signal: controller.signal })
      assertEntry()
      if (!isSafeResourceImage(result.blob)) throw new Error('该文件不是支持安全展示的图片。')
      entry.url = owner.ownUrl(result.blob)
      revision.value++
    } catch (error) {
      // Failure handlers must not turn a stale rejection into a current UI error.
      if (!owner.active.value || entries.get(key) !== entry || isCancel(error)) return
      try { assertEntry() } catch { return }
      entry.error = true
      revision.value++
    } finally {
      if (entry.controller) owner.finishController(entry.controller)
    }
  }
  watch(() => JSON.stringify(toValue(sources).map(source => locateResource(source).key)), () => {
    if (!owner.active.value) return
    const locations = toValue(sources).map(source => locateResource(source))
    const keys = new Set(locations.map(location => location.key))
    for (const [key, entry] of entries) if (!keys.has(key)) remove(key, entry)
    for (const location of locations) {
      if (entries.has(location.key)) continue
      const entry: Entry = { url: location.kind === 'public' ? location.url : '', error: location.kind === 'invalid' && location.key !== 'invalid:' }
      entries.set(location.key, entry)
      if (location.kind === 'protected') void load(location.key, location.url, entry)
    }
    revision.value++
  }, { immediate: true, flush: 'sync' })
  function urlFor(source: ResourceSource): string {
    void revision.value
    if (!owner.active.value) return ''
    return entries.get(locateResource(source).key)?.url ?? ''
  }
  function errorFor(source: ResourceSource): boolean {
    void revision.value
    return owner.active.value && (entries.get(locateResource(source).key)?.error ?? false)
  }
  const urlsFor = (list: readonly ResourceSource[]) => list.map(urlFor)
  return { urlFor, urlsFor, errorFor, urls: computed(() => urlsFor(toValue(sources))), active: owner.active, revision, clear }
}

export function useProtectedResourceUrl(source: MaybeRefOrGetter<ResourceSource>, options: ReadOptions = {}) {
  const collection = useProtectedResourceUrls(() => [toValue(source)], options)
  return {
    url: computed(() => collection.urlFor(toValue(source))),
    error: computed(() => collection.errorFor(toValue(source))),
    active: collection.active, revision: collection.revision, clear: collection.clear,
  }
}

/** Explicit preview/download actions; no auto-fetch, auth refresh, navigation or retries. */
export function useProtectedResourceActions() {
  const owner = useResourceOwner()
  const previewUrl = ref(''), previewName = ref(''), previewLoading = ref(false)
  const timers = new Set<ReturnType<typeof setTimeout>>()
  let previewSequence = 0, actionSequence = 0
  let previewController: AbortController | undefined
  function closePreview() {
    previewSequence++
    previewController?.abort()
    if (previewController) owner.finishController(previewController)
    previewController = undefined
    if (previewUrl.value) owner.releaseUrl(previewUrl.value)
    previewUrl.value = ''; previewName.value = ''; previewLoading.value = false
  }
  function reset() {
    actionSequence++
    closePreview()
    for (const timer of timers) clearTimeout(timer)
    timers.clear()
    owner.cancelResources()
  }
  owner.onInvalidate(reset)
  async function preview(source: string, filename?: string, options: ReadOptions = {}) {
    owner.assertCurrent()
    closePreview()
    const sequence = previewSequence
    const controller = owner.createController()
    previewController = controller
    const assertPreview = () => {
      owner.assertCurrent()
      if (sequence !== previewSequence) throw canceled()
    }
    previewLoading.value = true
    try {
      const result = await fetchProtectedResource(source, { ...options, signal: controller.signal })
      assertPreview()
      if (!isSafeResourceImage(result.blob)) throw new Error('该类型附件的安全预览尚未接入，当前未打开文件。')
      previewName.value = filename || result.filename || '图片预览'
      previewUrl.value = owner.ownUrl(result.blob)
    } catch (error) {
      assertPreview()
      throw error
    } finally {
      owner.finishController(controller)
      if (sequence === previewSequence) {
        previewLoading.value = false
        previewController = undefined
      }
    }
  }
  async function download(source: string, filename?: string, options: ReadOptions = {}) {
    owner.assertCurrent()
    const sequence = actionSequence
    const controller = owner.createController()
    const assertDownload = () => {
      owner.assertCurrent()
      if (sequence !== actionSequence) throw canceled()
    }
    try {
      const result = await fetchProtectedResource(source, { ...options, signal: controller.signal })
      assertDownload()
      const url = owner.ownUrl(result.blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = safeResourceFilename(filename || result.filename)
      anchor.rel = 'noopener noreferrer'
      try {
        assertDownload()
        document.body.appendChild(anchor)
        anchor.click()
        assertDownload()
      } catch (error) {
        owner.releaseUrl(url)
        throw error
      } finally { anchor.remove() }
      // Do not revoke synchronously after click: the browser may not have consumed
      // the bytes yet. Invalidation/unmount still revokes immediately and clears timers.
      const timer = setTimeout(() => { timers.delete(timer); owner.releaseUrl(url) }, 30_000)
      timers.add(timer)
    } catch (error) {
      assertDownload()
      throw error
    } finally { owner.finishController(controller) }
  }
  return { previewUrl, previewName, previewLoading, preview, closePreview, download, reset, active: owner.active }
}
