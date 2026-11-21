import { materialAttributeTable } from './materialAttributes'

const materialCategories = [
  { key: 'TUBE', label: '管材', aliases: ['管材', '管材类', '型材', '型材明细'] },
  { key: 'HARDWARE', label: '五金件', aliases: ['五金', '五金件', '五金件类'] },
  { key: 'PLASTIC', label: '塑料件', aliases: ['塑料', '塑料件', '塑料件类'] },
  { key: 'PACKAGING', label: '包材', aliases: ['包材', '包材类'] },
  { key: 'FABRIC', label: '面料', aliases: ['面料', '面料类'] },
  { key: 'AUXILIARY', label: '辅料', aliases: ['辅料', '辅料类'] },
  { key: 'OTHER', label: '其他材料', aliases: [] },
]

export const receiptMaterialLeadingColumnWidths = [56, 58, 180, 194]

export function receiptMaterialAttributeColumnWidth(label: string) {
  return label === '颜色' ? 192 : 112
}

export function receiptMaterialTableWidth(tables: { columns: string[] }[], commonWidths: number[]) {
  const attributeWidths = tables.map(table => table.columns.reduce((total, label) => total + receiptMaterialAttributeColumnWidth(label), 0))
  return commonWidths.reduce((total, width) => total + width, 0) + Math.max(...attributeWidths)
}

type ReceiptMaterialLine = Parameters<typeof materialAttributeTable>[0][number] & {
  section_type?: string; section_type_snapshot?: string
  section_title?: string; section_title_snapshot?: string
  category?: string; category_snapshot?: string
}

function materialCategory(line: ReceiptMaterialLine): string {
  const saved = line.material_selection_snapshot?.category_key
  const matchingSaved = materialCategories.find(category => category.key === saved)
  if (matchingSaved) return matchingSaved.key
  if ((line.section_type ?? line.section_type_snapshot) === 'PROFILE') return 'TUBE'
  const sectionTitle = line.section_title ?? line.section_title_snapshot ?? ''
  const categoryName = line.category ?? line.category_snapshot ?? ''
  return (materialCategories.find(category => category.aliases.includes(sectionTitle))
    ?? materialCategories.find(category => category.aliases.includes(categoryName)))?.key ?? 'OTHER'
}

export function receiptMaterialTables<Row extends { line: ReceiptMaterialLine; included: boolean }>(rows: Row[], grouped = true) {
  const sections = grouped && rows.length ? materialCategories : [{ key: 'ALL', label: '', aliases: [] }]
  const rowsByCategory = new Map<string, Row[]>()
  for (const row of rows) {
    const key = grouped ? materialCategory(row.line) : 'ALL'
    const group = rowsByCategory.get(key)
    if (group) group.push(row)
    else rowsByCategory.set(key, [row])
  }
  let number = 0
  return sections.filter(section => section.key === 'ALL' || rowsByCategory.has(section.key)).map(section => {
    const sectionRows = rowsByCategory.get(section.key) ?? []
    const { columns, cells } = materialAttributeTable(sectionRows.map(row => row.line))
    const selected = sectionRows.filter(row => row.included).length
    return {
      key: section.key, label: section.label, columns, selected,
      rows: sectionRows.map((row, index) => ({ row, number: ++number, attributes: cells[index]! })),
    }
  })
}
