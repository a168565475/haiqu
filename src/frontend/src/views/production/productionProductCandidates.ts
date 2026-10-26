import type { InquiryProductCandidate, InquiryProductSelectionOptions } from '@/types/inquiry'
import type { ProductionTaskOptions } from '@/types/productionTask'

export function buildProductionProductCandidates(
  categoryId: string,
  options: Pick<ProductionTaskOptions, 'categories' | 'products' | 'units'>,
): InquiryProductSelectionOptions {
  const category = options.categories?.find(row => row.id === categoryId)
  if (!category) throw new Error('产品类别不存在或不可用。')
  const grouped = new Map<string, Map<string, InquiryProductCandidate[]>>()
  for (const product of options.products) {
    if (product.category_id !== categoryId) continue
    const unit = options.units.find(row => row.id === product.default_unit_id)
    // 产品字段用于候选展示；能否使用该单位仍由确认表单和服务端校验。
    const candidate: InquiryProductCandidate = {
      id: product.id, product_number: product.product_number, product_code: product.product_code,
      item_number: product.item_number, product_name: product.product_name, specification: product.specification,
      unit_id: product.default_unit_id, unit_code: product.unit_code || unit?.unit_code || '',
      unit_name: product.unit_name || unit?.unit_name || '', category_id: category.id, category_name: category.category_name,
    }
    if (!grouped.has(product.product_name)) grouped.set(product.product_name, new Map())
    const specs = grouped.get(product.product_name)!
    if (!specs.has(product.specification)) specs.set(product.specification, [])
    specs.get(product.specification)!.push(candidate)
  }
  return { category, groups: [...grouped].map(([product_name, specs]) => ({
    product_name, specifications: [...specs].map(([specification, products]) => ({ specification, products })),
  })) }
}
