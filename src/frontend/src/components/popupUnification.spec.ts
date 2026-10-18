import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

function source(file: string): string {
  return readFileSync(resolve(__dirname, file), 'utf8')
}

describe('业务窗口外壳统一', () => {
  it('辅料资料新增使用 AppWindowDialog', () => {
    const content = source('AuxiliaryReferenceCreateDialog.vue')
    expect(content).toContain("import AppWindowDialog from '@/components/common/AppWindowDialog.vue'")
    expect(content).not.toMatch(/<ElDialog\b/)
  })

  it('生产任务产品替换使用 AppWindowDialog', () => {
    const content = source('production/ProductionTaskProductUpdateDialog.vue')
    expect(content).toContain("import AppWindowDialog from '@/components/common/AppWindowDialog.vue'")
    expect(content).not.toMatch(/<ElDialog\b/)
  })

  it('BOM 编辑器中的业务窗口全部使用 AppWindowDialog', () => {
    const content = source('../views/boms/BomEditorView.vue')
    expect(content).toContain("import AppWindowDialog from '@/components/common/AppWindowDialog.vue'")
    expect(content).not.toMatch(/<ElDialog\b/)
  })

  it('业务抽屉全部使用 AppWindowDialog', () => {
    const drawerFiles = [
      '../views/HomeView.vue',
      '../views/contacts/ContactListView.vue',
      'procurement/SupplierCreateDrawer.vue',
      'procurement/PurchaseContractTemplateHistoryDrawer.vue',
      'procurement/PurchaseContractTemplateCreateDrawer.vue',
      'workbench/WorkbenchQuickDrawer.vue',
      'samples/SampleMaterialLineDrawer.vue',
    ]
    drawerFiles.forEach(file => {
      const content = source(file)
      expect(content, file).toContain("import AppWindowDialog from '@/components/common/AppWindowDialog.vue'")
      expect(content, file).not.toMatch(/<ElDrawer\b/)
    })
  })
})
