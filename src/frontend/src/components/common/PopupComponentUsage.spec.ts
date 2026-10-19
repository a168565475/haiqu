import { readdirSync, readFileSync } from 'node:fs'
import { resolve, relative } from 'node:path'
import { parse as parseSfc } from '@vue/compiler-sfc'
import { baseParse, parserOptions, NodeTypes, type RootNode, type ElementNode } from '@vue/compiler-dom'
import ts from 'typescript'
import { expect, it } from 'vitest'

const sourceRoot = resolve(__dirname, '../..')
function vueFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = resolve(directory, entry.name)
    return entry.isDirectory() ? vueFiles(path) : entry.name.endsWith('.vue') ? [path] : []
  })
}

it('业务弹窗和抽屉必须通过 AppWindowDialog，不能依赖全局注册绕过统一组件', () => {
  const violations: string[] = []
  for (const path of vueFiles(sourceRoot)) {
    if (path === resolve(__dirname, 'AppWindowDialog.vue')) continue
    const { descriptor } = parseSfc(readFileSync(path, 'utf8'))
    const script = ts.createSourceFile(path, [descriptor.script?.content, descriptor.scriptSetup?.content].filter(Boolean).join('\n'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
    const sharedAliases = new Set<string>()
    const rawAliases = new Set(['eldialog', 'eldrawer'])
    for (const statement of script.statements) {
      if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) continue
      const clause = statement.importClause
      if (statement.moduleSpecifier.text.endsWith('/AppWindowDialog.vue') && clause?.name) sharedAliases.add(clause.name.text.toLowerCase())
      if (statement.moduleSpecifier.text === 'element-plus' && clause?.namedBindings && ts.isNamedImports(clause.namedBindings)) {
        for (const item of clause.namedBindings.elements) {
          if (['ElDialog', 'ElDrawer'].includes(item.propertyName?.text ?? item.name.text)) rawAliases.add(item.name.text.toLowerCase())
        }
      }
    }
    if (!descriptor.template) continue
    const visit = (node: RootNode | ElementNode) => {
      for (const child of node.children) {
        if (child.type !== NodeTypes.ELEMENT) continue
        const tag = child.tag.replaceAll('-', '').toLowerCase()
        const customDialog = child.props.some(prop => prop.type === NodeTypes.ATTRIBUTE && prop.name === 'role' && prop.value?.content === 'dialog')
        if ((rawAliases.has(tag) && !sharedAliases.has(tag)) || tag === 'dialog' || customDialog) violations.push(`${relative(sourceRoot, path)}:${child.loc.start.line} <${child.tag}>`)
        visit(child)
      }
    }
    visit(baseParse(descriptor.template.content, parserOptions))
  }
  expect(violations).toEqual([])
})
