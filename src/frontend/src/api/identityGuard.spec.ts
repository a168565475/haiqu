import axios, {
  AxiosError,
  AxiosHeaders,
  CanceledError,
  isCancel,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { installIdentityRequestGuard, type IdentityRequestContext } from './identityGuard'

// Adapter unit tests only. These do not exercise a real Session/API or browser switching.
const baseURL = 'https://erp.example.test'
const businessUrl = '/api/v1/customers/'
const disposers: Array<() => void> = []
afterEach(() => { disposers.splice(0).reverse().forEach(dispose => dispose()) })

function response(config: InternalAxiosRequestConfig, data: unknown = { ok: true }): AxiosResponse {
  return { status: 200, statusText: 'OK', headers: {}, config, data }
}

function httpError(config: InternalAxiosRequestConfig, status: number, code: string): AxiosError {
  return new AxiosError('adapter rejection', undefined, config, undefined,
    { ...response(config, { error: { code }, private: 'old identity data' }), status })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

function pendingAdapter() {
  const started = deferred<InternalAxiosRequestConfig>()
  const result = deferred<AxiosResponse>()
  const adapter: AxiosAdapter = config => { started.resolve(config); return result.promise }
  return { started, result, adapter }
}

function setup(overrides: Partial<IdentityRequestContext> = {}) {
  const context: IdentityRequestContext = { generation: 1, version: 'identity-v1', blocked: false, ...overrides }
  const adapter = vi.fn((config: InternalAxiosRequestConfig) => Promise.resolve(response(config)))
  const client = axios.create({ baseURL, adapter, withCredentials: true, withXSRFToken: true,
    xsrfCookieName: 'csrftoken', xsrfHeaderName: 'X-CSRFToken' })
  const getContext = vi.fn(() => context)
  const onConflict = vi.fn()
  const dispose = installIdentityRequestGuard(client, getContext, onConflict)
  disposers.push(dispose)
  return { client, context, adapter, getContext, onConflict, dispose }
}

function expectCanceled(error: unknown) {
  expect(error).toBeInstanceOf(CanceledError)
  expect(isCancel(error)).toBe(true)
  expect(error).toMatchObject({ code: 'ERR_CANCELED' })
  expect((error as AxiosError).config).toBeUndefined()
  expect((error as AxiosError).request).toBeUndefined()
  expect((error as AxiosError).response).toBeUndefined()
  expect((error as Error).cause).toBeUndefined()
}

const controls = [
  ['get', '/api/auth/me/'],
  ['get', '/api/auth/switch-targets/'],
  ['post', '/api/auth/login/'],
  ['post', '/api/auth/logout/'],
  ['post', '/api/auth/switch/'],
  ['post', '/api/auth/return-admin/'],
] as const

describe('identity request guard — adapter unit boundaries', () => {
  it('attaches only the current identity version without altering CSRF, ETag or caller signal', async () => {
    const { client, adapter } = setup()
    const controller = new AbortController()
    client.defaults.headers.common['X-Identity-Version'] = 'old-default'
    await client.patch(businessUrl, { name: 'unchanged payload' }, {
      headers: { 'x-identity-version': false, 'X-CSRFToken': 'csrf-exact', 'If-Match': '"resource-etag"' },
      signal: controller.signal,
    })
    const config = adapter.mock.calls[0]![0]
    expect(config.headers.get('X-Identity-Version')).toBe('identity-v1')
    expect(config.headers.get('X-CSRFToken')).toBe('csrf-exact')
    expect(config.headers.get('If-Match')).toBe('"resource-etag"')
    expect(config.signal).toBe(controller.signal)
    expect(config.withCredentials).toBe(true)
    expect(config.withXSRFToken).toBe(true)
    expect(config.xsrfCookieName).toBe('csrftoken')
    expect(config.xsrfHeaderName).toBe('X-CSRFToken')
    expect(JSON.parse(config.data)).toEqual({ name: 'unchanged payload' })
  })

  it('removes a caller/default identity header when there is no identity version', async () => {
    const { client, adapter } = setup({ version: null })
    client.defaults.headers.common['X-Identity-Version'] = 'old-default'
    await client.get(businessUrl, { headers: { 'x-identity-version': 'old-caller', 'If-Match': 'preserved' } })
    expect(adapter.mock.calls[0]![0].headers.has('X-Identity-Version')).toBe(false)
    expect(adapter.mock.calls[0]![0].headers.get('If-Match')).toBe('preserved')
  })

  it.each([
    'https://external.example.test/api/v1/customers/',
    '//external.example.test/api/v1/customers/',
    'https://erp.example.test.evil.test/api/v1/customers/',
    'http://erp.example.test/api/v1/customers/',
    'https://erp.example.test:8443/api/v1/customers/',
    '/api-not-business/customers/',
    '/assets/logo.svg',
  ])('does not leak identity headers to %s', async url => {
    const { client, adapter, onConflict } = setup({ blocked: true })
    client.defaults.headers.common['X-Identity-Version'] = 'old-default'
    await client.get(url, { headers: { 'x-identity-version': 'old-caller' } })
    expect(adapter.mock.calls[0]![0].headers.has('X-Identity-Version')).toBe(false)
    expect(onConflict).not.toHaveBeenCalled()
  })

  it('does not trust a per-request baseURL override', async () => {
    const { client, adapter } = setup({ blocked: true })
    await client.get('/api/v1/customers/', { baseURL: 'https://external.example.test',
      headers: { 'X-Identity-Version': 'must-not-leak' } })
    expect(adapter.mock.calls[0]![0].headers.has('X-Identity-Version')).toBe(false)
  })

  it('allows an absolute URL on the trusted origin and ignores query strings for control matching', async () => {
    const { client, adapter } = setup({ blocked: true })
    await client.get(`${baseURL}/api/auth/me/?probe=1`)
    expect(adapter.mock.calls[0]![0].headers.get('X-Identity-Version')).toBe('identity-v1')
  })

  it.each(controls)('allows blocked control %s %s but still freezes its identity', async (method, url) => {
    const { client, adapter } = setup({ blocked: true })
    await client.request({ method, url, data: method === 'post' ? {} : undefined })
    expect(adapter).toHaveBeenCalledTimes(1)
    expect(adapter.mock.calls[0]![0].headers.get('X-Identity-Version')).toBe('identity-v1')
  })

  it.each([
    ['get', businessUrl], ['post', businessUrl],
    ['post', '/api/auth/me/'], ['get', '/api/auth/login/'],
    ['delete', '/api/auth/logout/'], ['post', '/api/auth/switch-targets/'],
    ['get', '/api/auth/me'], ['get', '/api/auth/me/extra/'],
    ['post', '/api/auth/switch/extra/'], ['post', '/api/auth/development-auto-login/'],
    ['post', '/api/auth/wecom/qr/'],
  ])('rejects blocked non-control %s %s immediately, without dispatch or replay', async (method, url) => {
    const { client, context, adapter, onConflict } = setup({ blocked: true })
    const error = await client.request({ method, url }).catch(error => error)
    expectCanceled(error)
    expect(adapter).not.toHaveBeenCalled()
    context.blocked = false
    await Promise.resolve()
    expect(adapter).not.toHaveBeenCalled()
    expect(onConflict).not.toHaveBeenCalled()
  })

  it('captures the same tick synchronously even with a later asynchronous request interceptor', async () => {
    const { client, context, adapter, getContext } = setup()
    const gate = deferred<void>()
    client.interceptors.request.use(async config => { await gate.promise; return config })
    const request = client.get(businessUrl).catch(error => error)
    expect(getContext).toHaveBeenCalled() // runWhen, before the asynchronous chain starts
    context.generation += 1
    context.version = 'identity-v2'
    gate.resolve()
    expectCanceled(await request)
    expect(adapter).not.toHaveBeenCalled()
  })

  it('rejects blocked business calls before a later asynchronous interceptor can start waiting', async () => {
    const { client, adapter } = setup({ blocked: true })
    const gate = deferred<void>()
    const laterInterceptor = vi.fn(async (config: InternalAxiosRequestConfig) => { await gate.promise; return config })
    client.interceptors.request.use(laterInterceptor)
    expectCanceled(await client.get(businessUrl).catch(error => error))
    expect(laterInterceptor).not.toHaveBeenCalled()
    expect(adapter).not.toHaveBeenCalled()
  })

  it('does not queue a blocked same-tick request until the context becomes unblocked', async () => {
    const { client, context, adapter } = setup({ blocked: true })
    client.interceptors.request.use(async config => config)
    const request = client.get(businessUrl).catch(error => error)
    context.blocked = false
    expectCanceled(await request)
    expect(adapter).not.toHaveBeenCalled()
  })

  it('fails closed if a later request interceptor replaces the config object and loses its snapshot', async () => {
    const { client, adapter } = setup()
    client.interceptors.request.use(async config => ({ ...config }))
    expectCanceled(await client.get(businessUrl).catch(error => error))
    expect(adapter).not.toHaveBeenCalled()
  })

  it('rechecks dispatch after transformRequest changes the identity', async () => {
    const { client, context, adapter } = setup()
    const error = await client.post(businessUrl, {}, { transformRequest: [data => {
      context.version = 'identity-v2'
      return JSON.stringify(data)
    }] }).catch(error => error)
    expectCanceled(error)
    expect(adapter).not.toHaveBeenCalled()
  })

  it('rechecks destination and strips a header added after its request interceptor', async () => {
    const context = { generation: 1, version: 'identity-v1', blocked: false }
    const adapter = vi.fn((config: InternalAxiosRequestConfig) => Promise.resolve(response(config)))
    const client = axios.create({ baseURL, adapter })
    // Request LIFO: this older interceptor runs after the guard's fulfilled callback.
    client.interceptors.request.use(config => {
      config.url = 'https://external.example.test/api/v1/customers/'
      config.headers.set('X-Identity-Version', 'late-secret')
      return config
    }, undefined, { synchronous: true })
    disposers.push(installIdentityRequestGuard(client, () => context, vi.fn()))
    await client.get(businessUrl)
    expect(adapter.mock.calls[0]![0].headers.has('X-Identity-Version')).toBe(false)
  })

  it('preserves caller AbortSignal cancellation and never dispatches an already-aborted request', async () => {
    const { client, adapter, onConflict } = setup()
    const controller = new AbortController()
    controller.abort()
    const error = await client.get(businessUrl, { signal: controller.signal }).catch(error => error)
    expect(isCancel(error)).toBe(true)
    expect(adapter).not.toHaveBeenCalled()
    expect(onConflict).not.toHaveBeenCalled()
  })

  it.each(['success', 'http', 'network', 'plain-network'] as const)(
    'isolates old %s results, including failures without a config', async outcome => {
      const { client, context, onConflict } = setup()
      const pending = pendingAdapter()
      client.defaults.adapter = pending.adapter
      const request = client.get(businessUrl).catch(error => error)
      const config = await pending.started.promise
      context.generation += 1
      context.version = 'identity-v2'
      if (outcome === 'success') pending.result.resolve(response(config, { private: 'old identity data' }))
      else if (outcome === 'http') pending.result.reject(httpError(config, 409, 'IDENTITY_VERSION_CONFLICT'))
      else if (outcome === 'network') pending.result.reject(new AxiosError('old network failure', 'ERR_NETWORK', config))
      else pending.result.reject(new Error('old adapter failure without config'))
      expectCanceled(await request)
      expect(onConflict).not.toHaveBeenCalled()
    },
  )

  it.each(controls.flatMap(([method, url]) => ['success', 'http', 'network'].map(outcome => ({ method, url, outcome }))))(
    'isolates late blocked control $outcome from $method $url', async ({ method, url, outcome }) => {
      const { client, context, onConflict } = setup({ blocked: true })
      const pending = pendingAdapter()
      client.defaults.adapter = pending.adapter
      const request = client.request({ method, url }).catch(error => error)
      const config = await pending.started.promise
      context.generation += 1
      if (outcome === 'success') pending.result.resolve(response(config, { authenticated: true, user: { id: 'old-user' } }))
      else if (outcome === 'http') pending.result.reject(httpError(config, 428, 'IDENTITY_VERSION_REQUIRED'))
      else pending.result.reject(new AxiosError('old control network failure', 'ERR_NETWORK', config))
      expectCanceled(await request)
      expect(onConflict).not.toHaveBeenCalled()
    },
  )

  it.each(['success', 'http'] as const)('rechecks a %s result after response transforms', async outcome => {
    const { client, context, onConflict } = setup()
    const pending = pendingAdapter()
    client.defaults.adapter = pending.adapter
    const request = client.get(businessUrl, { transformResponse: [data => {
      context.generation += 1
      return data
    }] }).catch(error => error)
    const config = await pending.started.promise
    if (outcome === 'success') pending.result.resolve(response(config))
    else pending.result.reject(httpError(config, 409, 'IDENTITY_VERSION_CONFLICT'))
    expectCanceled(await request)
    expect(onConflict).not.toHaveBeenCalled()
  })

  it('does not actively abort caller signals when identity changes; it isolates the eventual result', async () => {
    const { client, context } = setup()
    const pending = pendingAdapter()
    const controller = new AbortController()
    const request = client.get(businessUrl, { adapter: pending.adapter, signal: controller.signal }).catch(error => error)
    const config = await pending.started.promise
    context.generation += 1
    expect(controller.signal.aborted).toBe(false)
    pending.result.resolve(response(config))
    expectCanceled(await request)
  })

  it('isolates a version-only change even if generation is unchanged', async () => {
    const { client, context } = setup()
    const pending = pendingAdapter()
    client.defaults.adapter = pending.adapter
    const request = client.get(businessUrl).catch(error => error)
    const config = await pending.started.promise
    context.version = 'identity-v2'
    pending.result.resolve(response(config))
    expectCanceled(await request)
  })

  it('isolates a business response when blocked becomes true without a generation change', async () => {
    const { client, context } = setup()
    const pending = pendingAdapter()
    client.defaults.adapter = pending.adapter
    const request = client.get(businessUrl).catch(error => error)
    const config = await pending.started.promise
    context.blocked = true
    pending.result.resolve(response(config))
    expectCanceled(await request)
  })

  it.each(['success', 'http', 'network'] as const)('preserves a current %s result', async outcome => {
    const { client, onConflict } = setup()
    const pending = pendingAdapter()
    client.defaults.adapter = pending.adapter
    const request = client.get(businessUrl).then(value => value, error => error)
    const config = await pending.started.promise
    const result = response(config, { current: true })
    const error = outcome === 'http' ? httpError(config, 403, 'PERMISSION_DENIED')
      : new AxiosError('current network failure', 'ERR_NETWORK', config)
    if (outcome === 'success') pending.result.resolve(result)
    else pending.result.reject(error)
    expect(await request).toBe(outcome === 'success' ? result : error)
    expect(onConflict).not.toHaveBeenCalled()
  })

  it.each([[409, 'IDENTITY_VERSION_CONFLICT'], [428, 'IDENTITY_VERSION_REQUIRED']] as const)(
    'notifies once for a same-context identity error %s/%s, with no hidden requests', async (status, code) => {
      const { client, adapter, context, onConflict } = setup()
      adapter.mockImplementation(config => Promise.reject(httpError(config, status, code)))
      const errors = await Promise.all([client.get(businessUrl).catch(error => error),
        client.get(businessUrl).catch(error => error)])
      expect(errors.every(error => error instanceof AxiosError && !isCancel(error))).toBe(true)
      expect(onConflict).toHaveBeenCalledTimes(1)
      expect(onConflict).toHaveBeenCalledWith()
      expect(adapter).toHaveBeenCalledTimes(2)
      context.generation += 1
      await client.get(businessUrl).catch(() => undefined)
      expect(onConflict).toHaveBeenCalledTimes(2)
      expect(adapter).toHaveBeenCalledTimes(3)
    },
  )

  it.each([
    [409, 'BUSINESS_CONFLICT'], [412, 'PRECONDITION_FAILED'], [428, 'PRECONDITION_REQUIRED'],
    [403, 'PERMISSION_DENIED'], [401, 'AUTHENTICATION_REQUIRED'], [403, 'WECOM_ROLE_REQUIRED'],
    [412, 'IDENTITY_VERSION_CONFLICT'], [403, 'IDENTITY_VERSION_REQUIRED'],
    [409, 'IDENTITY_VERSION_CONFLICT_EXTRA'],
  ] as const)('preserves ordinary HTTP %s/%s without identity side effects', async (status, code) => {
    const { client, adapter, onConflict } = setup()
    let original!: AxiosError
    adapter.mockImplementation(config => { original = httpError(config, status, code); return Promise.reject(original) })
    expect(await client.get(businessUrl).catch(error => error)).toBe(original)
    expect(onConflict).not.toHaveBeenCalled()
    expect(adapter).toHaveBeenCalledTimes(1)
  })

  it('synchronously marks blocked on a conflict without fetching /me or replaying a write', async () => {
    const { client, context, adapter, onConflict } = setup()
    onConflict.mockImplementation(() => { context.blocked = true })
    adapter.mockImplementation(config => Promise.reject(httpError(config, 409, 'IDENTITY_VERSION_CONFLICT')))
    const error = await client.post(businessUrl, { operation: 'do-not-replay' }).catch(error => error)
    expect(isCancel(error)).toBe(false)
    expect(context.blocked).toBe(true)
    expect(adapter).toHaveBeenCalledTimes(1)
    expectCanceled(await client.get(businessUrl).catch(error => error))
    expect(adapter).toHaveBeenCalledTimes(1)
    expect(onConflict).toHaveBeenCalledTimes(1)
  })

  it.each(['success', 'http', 'network'] as const)(
    'leaves external %s results untouched even across identity changes', async outcome => {
      const { client, context, onConflict } = setup()
      const pending = pendingAdapter()
      client.defaults.adapter = pending.adapter
      const request = client.get('https://external.example.test/api/v1/customers/',
        { headers: { 'X-Identity-Version': 'remove-this' } }).then(value => value, error => error)
      const config = await pending.started.promise
      expect(config.headers.has('X-Identity-Version')).toBe(false)
      context.generation += 1
      context.blocked = true
      const result = response(config)
      const error = outcome === 'http' ? httpError(config, 409, 'IDENTITY_VERSION_CONFLICT')
        : new AxiosError('external network failure', 'ERR_NETWORK', config)
      if (outcome === 'success') pending.result.resolve(result)
      else pending.result.reject(error)
      expect(await request).toBe(outcome === 'success' ? result : error)
      expect(onConflict).not.toHaveBeenCalled()
    },
  )

  it('reinstall/dispose are idempotent and a previous disposer cannot remove the new guard', async () => {
    const { client, adapter, dispose, onConflict } = setup()
    const nextContext = { generation: 2, version: 'identity-v2', blocked: false }
    const nextConflict = vi.fn()
    const nextDispose = installIdentityRequestGuard(client, () => nextContext, nextConflict)
    disposers.push(nextDispose)
    dispose()
    dispose()
    await client.get(businessUrl)
    expect(adapter).toHaveBeenCalledTimes(1)
    expect(adapter.mock.calls[0]![0].headers.get('X-Identity-Version')).toBe('identity-v2')
    adapter.mockImplementation(config => Promise.reject(httpError(config, 409, 'IDENTITY_VERSION_CONFLICT')))
    await client.get(businessUrl).catch(() => undefined)
    expect(nextConflict).toHaveBeenCalledTimes(1)
    expect(onConflict).not.toHaveBeenCalled()
    nextDispose()
    nextDispose()
    nextContext.blocked = true
    adapter.mockImplementation(config => Promise.resolve(response(config)))
    await client.get(businessUrl)
    expect(adapter.mock.calls[2]![0].headers.has('X-Identity-Version')).toBe(false)
  })

  it('disposal cancels already-dispatched trusted results without calling an obsolete callback', async () => {
    const { client, dispose, onConflict } = setup()
    const pending = pendingAdapter()
    client.defaults.adapter = pending.adapter
    const request = client.get(businessUrl).catch(error => error)
    const config = await pending.started.promise
    dispose()
    pending.result.reject(httpError(config, 409, 'IDENTITY_VERSION_CONFLICT'))
    expectCanceled(await request)
    expect(onConflict).not.toHaveBeenCalled()
  })

  it('also isolates stale errors before a later business response interceptor can inspect them', async () => {
    const { client, context } = setup()
    const seen = vi.fn()
    client.interceptors.response.use(undefined, error => { seen(error); throw error })
    const pending = pendingAdapter()
    client.defaults.adapter = pending.adapter
    const request = client.get(businessUrl).catch(error => error)
    const config = await pending.started.promise
    context.generation += 1
    pending.result.reject(httpError(config, 401, 'AUTHENTICATION_REQUIRED'))
    const error = await request
    expectCanceled(error)
    expect(seen).toHaveBeenCalledWith(error)
    expect((seen.mock.calls[0]![0] as AxiosError).response).toBeUndefined()
  })

  it('supports relative request paths under a configured API base path', async () => {
    const adapter = vi.fn((config: InternalAxiosRequestConfig) => Promise.resolve(response(config)))
    const client = axios.create({ baseURL: `${baseURL}/api/`, adapter })
    disposers.push(installIdentityRequestGuard(client,
      () => ({ generation: 1, version: 'identity-v1', blocked: false }), vi.fn()))
    await client.get('v1/customers/')
    expect(AxiosHeaders.from(adapter.mock.calls[0]![0].headers).get('X-Identity-Version')).toBe('identity-v1')
  })
})
