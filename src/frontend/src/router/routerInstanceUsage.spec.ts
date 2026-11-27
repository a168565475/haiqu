import { readdirSync, readFileSync } from 'node:fs'
import { dirname, relative, resolve } from 'node:path'
import { expect, it } from 'vitest'

it('只有应用启动入口可以导入路由实例，业务页面使用当前应用的路由', () => {
  const source = resolve(__dirname, '..')
  const routerDir = resolve(source, 'router')
  const routerEntries = new Set([routerDir, resolve(routerDir, 'index'), resolve(routerDir, 'index.ts')])
  const violations: string[] = []

  for (const file of readdirSync(source, { recursive: true, encoding: 'utf8' })) {
    if (!/\.(?:vue|[jt]sx?)$/.test(file) || /\.(?:spec|test)\.[jt]sx?$/.test(file) || file === 'main.ts') continue
    const path = resolve(source, file)
    const imports = readFileSync(path, 'utf8').matchAll(/(?:\bfrom\s*|\bimport\s*(?:\(\s*)?)['"]((?:@\/|\.)[^'"\r\n]*)['"]/g)
    for (const [, id] of imports) {
      const target = id.startsWith('@/') ? resolve(source, id.slice(2)) : resolve(dirname(path), id)
      if (routerEntries.has(target)) violations.push(relative(source, path))
    }
  }

  expect(violations).toEqual([])
})
