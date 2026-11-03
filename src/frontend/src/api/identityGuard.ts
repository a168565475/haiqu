import {
  AxiosHeaders,
  CanceledError,
  getAdapter,
  isAxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'

export interface IdentityRequestContext {
  generation: number
  version: string | null
  blocked: boolean
}

interface RequestSnapshot {
  context: IdentityRequestContext
  guarded: boolean
  control: boolean
}

const identityHeader = 'X-Identity-Version'
const installedGuards = new WeakMap<AxiosInstance, () => void>()
const controlRequests = new Set([
  'get /api/auth/me/',
  'get /api/auth/switch-targets/',
  'post /api/auth/login/',
  'post /api/auth/logout/',
  'post /api/auth/switch/',
  'post /api/auth/return-admin/',
])

function resolveUrl(config: AxiosRequestConfig, browserUrl: string | undefined): URL | null {
  // Axios combines baseURL paths even for a leading slash (unlike new URL(url, base)).
  const url = config.url ?? ''
  const absolute = /^([a-z][a-z\d+.-]*:)?\/\//i.test(url)
  const combined = config.baseURL && (!absolute || config.allowAbsoluteUrls === false)
    ? `${config.baseURL.replace(/\/+$/, '')}/${url.replace(/^\/+/, '')}`
    : url
  try {
    const resolved = new URL(combined, browserUrl)
    return /^https?:$/.test(resolved.protocol) && !resolved.username && !resolved.password
      ? resolved : null
  } catch {
    return null
  }
}

function canceled(): CanceledError<unknown> {
  // Deliberately omit config, request, response and cause: stale data must not escape.
  return new CanceledError('Identity request context is no longer usable')
}

/**
 * Install before response-side business guards. Reinstalling replaces the previous guard.
 * runWhen snapshots synchronously, even when a later request interceptor is asynchronous.
 * No active abort, refresh, queuing or replay is performed; caller signals are untouched.
 */
export function installIdentityRequestGuard(
  client: AxiosInstance,
  getContext: () => IdentityRequestContext,
  onIdentityConflict: () => void,
): () => void {
  installedGuards.get(client)?.()
  const browserUrl = typeof window === 'undefined' ? undefined : window.location.href
  const trustedOrigin = resolveUrl({ url: client.defaults.baseURL ?? browserUrl }, browserUrl)?.origin
  const snapshots = new WeakMap<InternalAxiosRequestConfig, RequestSnapshot>()
  const failures = new WeakMap<object, RequestSnapshot>()
  let disposed = false
  let notified: Pick<IdentityRequestContext, 'generation' | 'version'> | undefined

  function assertCurrent(snapshot: RequestSnapshot) {
    if (!snapshot.guarded) return
    const current = getContext()
    if (disposed || snapshot.context.generation !== current.generation
      || snapshot.context.version !== current.version
      || (!snapshot.control && (snapshot.context.blocked || current.blocked))) {
      throw canceled()
    }
  }

  function prepareDispatch(config: InternalAxiosRequestConfig, snapshot: RequestSnapshot) {
    const destination = resolveUrl(config, browserUrl)
    snapshot.guarded = destination !== null && trustedOrigin !== undefined
      && destination.origin === trustedOrigin && destination.pathname.startsWith('/api/')
    snapshot.control = snapshot.guarded && destination !== null && controlRequests.has(
      `${(config.method ?? 'get').toLowerCase()} ${destination.pathname}`,
    )
    // Remove even caller/default false-valued or differently-cased legacy headers.
    config.headers = AxiosHeaders.from(config.headers)
    config.headers.delete(identityHeader)
    assertCurrent(snapshot)
    if (snapshot.guarded && snapshot.context.version !== null) {
      config.headers.set(identityHeader, snapshot.context.version, true)
    }
  }

  const requestInterceptor = client.interceptors.request.use(config => {
    const snapshot = snapshots.get(config)
    // A replacing interceptor must not silently recapture a newer identity.
    if (!snapshot) throw canceled()
    prepareDispatch(config, snapshot)
    const adapter = getAdapter(config.adapter ?? client.defaults.adapter)
    config.adapter = async dispatchConfig => {
      snapshots.set(dispatchConfig, snapshot)
      // Check again after every request interceptor and transformRequest has run.
      prepareDispatch(dispatchConfig, snapshot)
      try {
        const response = await adapter(dispatchConfig)
        assertCurrent(snapshot)
        snapshots.set(response.config, snapshot)
        return response
      } catch (error: unknown) {
        // Includes errors without an Axios config (e.g. a network adapter rejection).
        assertCurrent(snapshot)
        if (error !== null && (typeof error === 'object' || typeof error === 'function')) {
          failures.set(error, snapshot)
        }
        throw error
      }
    }
    return config
  }, (error: unknown) => { throw error }, {
    synchronous: true,
    runWhen(config) {
      // Axios invokes runWhen during synchronous interceptor collection, before any
      // Promise chain. A fulfilled-only snapshot would miss the same-tick boundary.
      const snapshot = { context: { ...getContext() }, guarded: false, control: false }
      snapshots.set(config, snapshot)
      // Reject blocked business calls before any asynchronous interceptor can wait.
      prepareDispatch(config, snapshot)
      return true
    },
  })

  const responseInterceptor = client.interceptors.response.use(response => {
    const snapshot = snapshots.get(response.config)
    if (snapshot) assertCurrent(snapshot)
    return response
  }, async (error: unknown) => {
    const recorded = error !== null && (typeof error === 'object' || typeof error === 'function')
      ? failures.get(error) : undefined
    const snapshot = recorded ?? (isAxiosError(error) && error.config ? snapshots.get(error.config) : undefined)
    if (!snapshot) throw error
    assertCurrent(snapshot)
    if (!snapshot.guarded || !isAxiosError(error)) throw error
    const status = error.response?.status
    let data = error.response?.data
    // 资源请求的 JSON 错误也会按 Blob 返回；只解析有界的身份错误候选。
    if ((status === 409 || status === 428) && data instanceof Blob
      && data.size <= 64 * 1024 && /^application\/(?:json|[\w.+-]+\+json)(?:;|$)/i.test(data.type)) {
      if (error.config?.signal?.aborted) throw canceled()
      try {
        const text = typeof data.text === 'function' ? await data.text() : await new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(String(reader.result))
          reader.onerror = () => reject(reader.error)
          reader.readAsText(data)
        })
        data = JSON.parse(text)
      } catch {
        // 损坏或不可读的响应保留原错误，不推断成身份冲突。
        data = undefined
      }
      assertCurrent(snapshot)
      if (error.config?.signal?.aborted) throw canceled()
    }
    const code = data?.error?.code
    if ((status === 409 || status === 428)
      && (code === 'IDENTITY_VERSION_CONFLICT' || code === 'IDENTITY_VERSION_REQUIRED')
      && (notified?.generation !== snapshot.context.generation
        || notified?.version !== snapshot.context.version)) {
      // Mark before invoking the synchronous callback so concurrent/reentrant errors
      // cannot notify twice. The callback only marks revalidation as required.
      notified = { generation: snapshot.context.generation, version: snapshot.context.version }
      onIdentityConflict()
    }
    throw error
  })

  const dispose = () => {
    if (disposed) return
    disposed = true
    client.interceptors.request.eject(requestInterceptor)
    client.interceptors.response.eject(responseInterceptor)
    if (installedGuards.get(client) === dispose) installedGuards.delete(client)
  }
  installedGuards.set(client, dispose)
  return dispose
}
