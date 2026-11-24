// @vitest-environment node
// 临时资源：仅 127.0.0.1 随机端口 HTTP 服务器；每项 finally 关闭服务器和 Agent，不创建文件。
import { createServer, get, Agent as HttpAgent, type Server } from 'node:http'
import { Agent as HttpsAgent } from 'node:https'
import { ADDRCONFIG, V4MAPPED, type LookupAddress, type LookupOptions } from 'node:dns'
import type { AddressInfo, LookupFunction } from 'node:net'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createDevelopmentProxy } from './devProxy'

const mocks = vi.hoisted(() => ({
  lookup: vi.fn(), resolve4: vi.fn(), resolve6: vi.fn(),
  existsSync: vi.fn(), readFileSync: vi.fn(), platform: vi.fn(), networkInterfaces: vi.fn(),
}))
vi.mock('node:dns', async original => {
  const actual = await original<typeof import('node:dns')>()
  return { ...actual, lookup: mocks.lookup, promises: { ...actual.promises, resolve4: mocks.resolve4, resolve6: mocks.resolve6 } }
})
vi.mock('node:fs', () => ({ existsSync: mocks.existsSync, readFileSync: mocks.readFileSync }))
vi.mock('node:os', () => ({ platform: mocks.platform, networkInterfaces: mocks.networkInterfaces }))

const agents: HttpAgent[] = []
function agentOptions(agent: HttpAgent) {
  return (agent as HttpAgent & { options: { keepAlive?: boolean; lookup?: LookupFunction } }).options
}
function proxy(target?: string) {
  const result = createDevelopmentProxy(target)
  agents.push(result.agent)
  return result
}
function lookup(agent: HttpAgent, options: LookupOptions = { all: true, hints: ADDRCONFIG }, hostname = 'backend') {
  const resolve = agentOptions(agent).lookup!
  return new Promise<{ address: string | LookupAddress[]; family?: number }>((done, reject) => {
    resolve(hostname, options, (error, address, family) => error ? reject(error) : done({ address, family }))
  })
}
async function startServer(closeConnection = false) {
  const server = createServer((_request, response) => {
    if (closeConnection) response.setHeader('Connection', 'close')
    response.end('ok')
  })
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  return server
}
async function closeServer(server: Server) {
  server.closeAllConnections()
  await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
  expect(server.listening).toBe(false)
}
function request(agent: HttpAgent, port: number, headers: Record<string, string> = {}) {
  return new Promise<string>((resolve, reject) => {
    const outgoing = get({ hostname: 'backend', port, path: '/', agent, headers }, response => {
      let text = ''
      response.setEncoding('utf8')
      response.on('data', chunk => { text += chunk })
      response.on('end', () => resolve(text))
      response.on('error', reject)
    })
    outgoing.on('error', reject)
  })
}
beforeEach(() => {
  vi.resetAllMocks()
  mocks.platform.mockReturnValue('linux')
  mocks.existsSync.mockReturnValue(true)
  mocks.readFileSync.mockReturnValue('127.0.0.1 localhost\n::1 localhost\n')
  mocks.networkInterfaces.mockReturnValue({ eth0: [{ family: 'IPv4', internal: false }] })
  mocks.resolve4.mockResolvedValue(['127.0.0.1'])
  mocks.resolve6.mockRejectedValue(Object.assign(new Error('no AAAA'), { code: 'ENODATA' }))
  mocks.lookup.mockImplementation((_hostname, options, callback) => {
    if (options.all) callback(null, [{ address: '127.0.0.1', family: 4 }])
    else callback(null, '127.0.0.1', 4)
  })
})
afterEach(() => { agents.splice(0).forEach(agent => agent.destroy()) })

describe('开发代理连接与 DNS', () => {
  it('HTTP/HTTPS 目标使用对应的连接复用 Agent，自定义目标保留系统解析', () => {
    const http = proxy('http://localhost:8000')
    const https = proxy('https://example.test:8443')
    expect(http.agent).toBeInstanceOf(HttpAgent)
    expect(https.agent).toBeInstanceOf(HttpsAgent)
    expect(agentOptions(http.agent).keepAlive).toBe(true)
    expect(agentOptions(https.agent).keepAlive).toBe(true)
    expect(agentOptions(http.agent).lookup).toBeUndefined()
    expect(agentOptions(https.agent).lookup).toBeUndefined()
    expect(https.target).toBe('https://example.test:8443')
  })

  it('Docker 默认服务名避开系统 lookup，支持单地址及 all 数组并且不缓存旧地址', async () => {
    const { agent } = proxy()
    expect(await lookup(agent)).toMatchObject({ address: [{ address: '127.0.0.1', family: 4 }] })
    mocks.resolve4.mockResolvedValueOnce(['127.0.0.2'])
    expect(await lookup(agent, { family: 4 })).toEqual({ address: '127.0.0.2', family: 4 })
    expect(mocks.resolve4).toHaveBeenCalledTimes(2)
    expect(mocks.resolve6).not.toHaveBeenCalled()
    expect(mocks.lookup).not.toHaveBeenCalled()
  })

  it('明确 IPv6 查询保留地址家族；多地址交回系统排序', async () => {
    const { agent } = proxy()
    mocks.resolve6.mockResolvedValueOnce(['::1'])
    expect(await lookup(agent, { family: 6, all: true })).toMatchObject({ address: [{ address: '::1', family: 6 }] })
    mocks.resolve4.mockResolvedValueOnce(['127.0.0.1', '127.0.0.2'])
    await lookup(agent, { family: 4, all: true })
    expect(mocks.lookup).toHaveBeenCalledWith('backend', { family: 4, all: true }, expect.any(Function))
  })

  it('ADDRCONFIG 没有所需家族时交回系统，不擅自换用 IPv4', async () => {
    const options = { family: 6, hints: ADDRCONFIG, all: true }
    await lookup(proxy().agent, options)
    expect(mocks.lookup).toHaveBeenCalledWith('backend', options, expect.any(Function))
    expect(mocks.resolve4).not.toHaveBeenCalled()
    expect(mocks.resolve6).not.toHaveBeenCalled()
  })

  it('双栈有多个候选时保留系统的原始排序', async () => {
    mocks.resolve6.mockResolvedValueOnce(['::1'])
    await lookup(proxy().agent, { all: true })
    expect(mocks.lookup).toHaveBeenCalledWith('backend', { all: true }, expect.any(Function))
  })

  it.each([
    ['localhost', {}], ['127.0.0.1', {}], ['::1', {}],
    ['backend', { hints: V4MAPPED }], ['backend', { order: 'ipv6first' }], ['backend', { verbatim: true }],
  ] as const)('%s 的系统解析语义不被替换：%j', async (hostname, options) => {
    await lookup(proxy().agent, options, hostname)
    expect(mocks.lookup).toHaveBeenCalledWith(hostname, options, expect.any(Function))
    expect(mocks.resolve4).not.toHaveBeenCalled()
    expect(mocks.resolve6).not.toHaveBeenCalled()
  })

  it('hosts 新增覆盖或读取失败时交回系统解析', async () => {
    const { agent } = proxy()
    await lookup(agent)
    mocks.readFileSync.mockReturnValueOnce('127.0.0.1 LOCALHOST backend # local override')
    await lookup(agent)
    mocks.readFileSync.mockImplementationOnce(() => { throw Object.assign(new Error('unreadable'), { code: 'EACCES' }) })
    await lookup(agent)
    expect(mocks.lookup).toHaveBeenCalledTimes(2)
    expect(mocks.resolve4).toHaveBeenCalledTimes(1)
  })

  it('非 Docker 环境或显式覆盖默认目标继续使用原生 lookup', () => {
    mocks.existsSync.mockReturnValue(false)
    expect(agentOptions(proxy().agent).lookup).toBeUndefined()
    mocks.existsSync.mockReturnValue(true)
    expect(agentOptions(proxy('http://backend:8000').agent).lookup).toBeUndefined()
    mocks.platform.mockReturnValue('win32')
    expect(agentOptions(proxy().agent).lookup).toBeUndefined()
  })

  it('真实 HTTP 连续请求复用一个连接，每次请求仍携带自己的身份头', async () => {
    const { agent } = proxy()
    const server = await startServer()
    let connections = 0
    const identities: string[] = []
    server.on('connection', () => { connections++ })
    server.on('request', request => { identities.push(String(request.headers['x-identity-version'])) })
    try {
      const port = (server.address() as AddressInfo).port
      expect(await request(agent, port, { 'X-Identity-Version': 'first' })).toBe('ok')
      expect(await request(agent, port, { 'X-Identity-Version': 'second' })).toBe('ok')
      expect(connections).toBe(1)
      expect(identities).toEqual(['first', 'second'])
      expect(mocks.resolve4).toHaveBeenCalledTimes(1)
    } finally { agent.destroy(); await closeServer(server) }
  })

  it('DNS 错误正常失败；后续请求重新解析并可恢复', async () => {
    const { agent } = proxy()
    const server = await startServer()
    const failure = Object.assign(new Error('not found'), { code: 'ENOTFOUND' })
    mocks.resolve4.mockRejectedValueOnce(failure)
    mocks.lookup.mockImplementationOnce((_hostname, _options, callback) => callback(failure))
    try {
      const port = (server.address() as AddressInfo).port
      await expect(request(agent, port)).rejects.toMatchObject({ code: 'ENOTFOUND' })
      expect(await request(agent, port)).toBe('ok')
      expect(mocks.resolve4).toHaveBeenCalledTimes(2)
    } finally { agent.destroy(); await closeServer(server) }
  })

  it('上游关闭连接后下一请求重新解析，没有永久地址缓存', async () => {
    const { agent } = proxy()
    const server = await startServer(true)
    try {
      const port = (server.address() as AddressInfo).port
      expect(await request(agent, port)).toBe('ok')
      expect(await request(agent, port)).toBe('ok')
      expect(mocks.resolve4).toHaveBeenCalledTimes(2)
    } finally { agent.destroy(); await closeServer(server) }
  })

  it('上游中断连接正常报错，不自动重放；下一次请求可建立新连接', async () => {
    const { agent } = proxy()
    const server = await startServer()
    server.prependOnceListener('request', incoming => incoming.socket.destroy())
    try {
      const port = (server.address() as AddressInfo).port
      await expect(request(agent, port)).rejects.toMatchObject({ code: 'ECONNRESET' })
      expect(mocks.resolve4).toHaveBeenCalledTimes(1)
      expect(await request(agent, port)).toBe('ok')
      expect(mocks.resolve4).toHaveBeenCalledTimes(2)
    } finally { agent.destroy(); await closeServer(server) }
  })
})
