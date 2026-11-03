import type { ProductEntryDraft, ProductEntryField, ProductSelectionInput, ProductSelectionSnapshot } from '@/types/productCatalog'

export const productEntryFields: ProductEntryField[] = ['category_name', 'name', 'item_number', 'specification', 'product_code', 'unit_name', 'color_name', 'material']

export function emptyProductEntry(): ProductEntryDraft {
  return {
    category_id: null, category_name: '', name_id: null, name: '', item_number: '', specification: '', product_code: '',
    unit_id: null, unit_name: '', color_id: null, color_name: '', material: '',
    sources: Object.fromEntries(productEntryFields.map(field => [field, 'typed'])) as ProductEntryDraft['sources'],
  }
}

export function productEntryUnitName(value?: {
  product_selection?: ProductSelectionInput | null
  product_selection_snapshot?: ProductSelectionSnapshot | null
  unit_name?: string
  unit_code?: string
  unit_code_snapshot?: string
} | null): string {
  if (value?.product_selection?.draft) return value.product_selection.draft.unit_name
  return value?.product_selection_snapshot?.unit_name || value?.unit_name || value?.unit_code || value?.unit_code_snapshot || ''
}

export function copyProductEntry(entry: ProductEntryDraft): ProductEntryDraft {
  return { ...entry, sources: { ...entry.sources } }
}

export function productEntryFromSnapshot(snapshot: ProductSelectionSnapshot): ProductEntryDraft {
  if (snapshot.entry_state === 'draft' && snapshot.entry_draft) return copyProductEntry(snapshot.entry_draft)
  return {
    ...emptyProductEntry(), category_id: snapshot.category_id, category_name: snapshot.category_name,
    name_id: snapshot.name_id, name: snapshot.name, item_number: snapshot.item_number, specification: snapshot.specification,
    product_code: snapshot.product_code, unit_id: snapshot.unit_id, unit_name: snapshot.unit_name,
    color_id: snapshot.color_id, color_name: snapshot.color_name, material: snapshot.material,
    sources: {
      category_name: snapshot.category_id ? 'selected' : 'typed', name: snapshot.name_id ? 'selected' : 'typed',
      item_number: snapshot.catalog_id && snapshot.item_number ? 'selected' : 'typed',
      specification: snapshot.catalog_id && snapshot.specification ? 'selected' : 'typed',
      product_code: snapshot.catalog_id && snapshot.product_code ? 'selected' : 'typed',
      unit_name: snapshot.unit_id ? 'selected' : 'typed', color_name: snapshot.color_id ? 'selected' : 'typed',
      material: snapshot.catalog_id && snapshot.material ? 'selected' : 'typed',
    },
  }
}
