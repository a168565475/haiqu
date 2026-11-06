import { lookup as systemLookup, promises as dns, ADDRCONFIG, type LookupAddress } from 'node:dns'
import { existsSync, readFileSync } from 'node:fs'
import { Agent as HttpAgent } from 'node:http'
import { Agent as HttpsAgent } from 'node:https'
import type { LookupFunction } from 'node:net'
import { networkInterfaces, platform } from 'node:os'

// 仅处理本开发容器的单地址 backend；系统 hosts、复杂选项和多地址排序仍交给系统解析。
const lookupDockerBackend: LookupFunction = (hostname, options, callback) => {
  const fallback = () => systemLookup(hostname, options, callback)
  const family = options.family ?? 0
  const hints = options.hints ?? 0
  if (hostname !== 'backend' || (family !== 0 && family !== 4 && family !== 6)
    || (hints !== 0 && hints !== ADDRCONFIG) || options.order !== undefined || options.verbatim !== undefined) {
    fallback()
    return
  }
  let families = family === 0 ? [4, 6] : [family]
  let hostsOverride = false
  try {
    // hosts 很小，直接读取避免再次排入与 Vite 文件轮询共享的线程池；不缓存覆盖结果。
    const hosts = readFileSync('/etc/hosts', 'utf8')
    hostsOverride = hosts.split('\n').some(line => line.split('#')[0]!.trim().split(/\s+/).slice(1).some(alias => alias.toLowerCase() === hostname))
    if (!hostsOverride && hints === ADDRCONFIG) {
      const addresses = Object.values(networkInterfaces()).flat().filter(address => address && !address.internal)
      families = families.filter(value => addresses.some(address => address?.family === (value === 4 ? 'IPv4' : 'IPv6')))
    }
  } catch {
    // 环境配置不可读取时使用系统原有解析，错误仍由其回调交付。
    fallback()
    return
  }
  if (hostsOverride || !families.length) { fallback(); return }
  void Promise.allSettled(families.map(async value => {
    const addresses = value === 4 ? await dns.resolve4(hostname) : await dns.resolve6(hostname)
    return addresses.map(address => ({ address, family: value }))
  })).then(results => {
    const addresses: LookupAddress[] = []
    for (const result of results) {
      if (result.status === 'fulfilled') addresses.push(...result.value)
      else if (!['ENODATA', 'ENOTFOUND'].includes((result.reason as NodeJS.ErrnoException)?.code || '')) {
        fallback()
        return
      }
    }
    // 单候选不存在 IPv4/IPv6 排序差异；其余情况保留 getaddrinfo 的完整行为。
    if (addresses.length !== 1) { fallback(); return }
    const address = addresses[0]!
    if (options.all) callback(null, addresses)
    else callback(null, address.address, address.family)
  })
}

export function createDevelopmentProxy(targetOverride?: string) {
  const target = targetOverride || 'http://backend:8000'
  const protocol = new URL(target).protocol
  if (protocol !== 'http:' && protocol !== 'https:') throw new Error('开发代理目标必须使用 http 或 https。')
  const useDockerDns = !targetOverride && platform() === 'linux' && existsSync('/.dockerenv')
  const options = { keepAlive: true, ...(useDockerDns ? { lookup: lookupDockerBackend } : {}) }
  return { target, agent: protocol === 'https:' ? new HttpsAgent(options) : new HttpAgent(options) }
}
