import type { PageMeta } from './referenceData'

export type SupplierType = 'MATERIAL' | 'FINISHED'
export type SupplierCategory =
  | 'TUBE'
  | 'HARDWARE'
  | 'PLASTIC_PART'
  | 'PACKAGING'
  | 'FABRIC'
  | 'AUXILIARY'
  | 'FINISHED_GOODS'
export type SupplierPaymentCycle = 'MONTHLY'

export interface Supplier {
  id: string
  supplier_number: string
  supplier_type: SupplierType
  supplier_type_display: string
  supplier_categories: SupplierCategory[]
  supplier_category_labels: string[]
  supplier_name: string
  payment_cycle: SupplierPaymentCycle | ''
  payment_cycle_display: string
  remark: string
  phone: string
  is_disabled: boolean
  status_display: string
  submitted_by_name: string
  submitted_at: string | null
  updated_by_name: string
  created_at: string
  updated_at: string
  duplicate_suppliers?: DuplicateSupplier[]
}

export interface DuplicateSupplier {
  id: string
  supplier_number: string
  is_disabled: boolean
  status_display: string
}

export interface SupplierInput {
  supplier_type: SupplierType
  supplier_categories: SupplierCategory[]
  supplier_name: string
  payment_cycle: SupplierPaymentCycle | ''
  remark: string
  phone: string
  is_disabled: boolean
}

export interface SupplierQuery {
  page?: number
  page_size?: number
  q?: string
  supplier_type?: SupplierType | ''
  category?: SupplierCategory | ''
  payment_cycle?: SupplierPaymentCycle | ''
  is_disabled?: boolean | ''
  ordering?: string
}

export interface ChoiceOption<T extends string> {
  value: T
  label: string
}

export interface SupplierOptions {
  supplier_types: ChoiceOption<SupplierType>[]
  supplier_categories: ChoiceOption<SupplierCategory>[]
  payment_cycles: ChoiceOption<SupplierPaymentCycle>[]
  next_supplier_number: string
}

export interface SupplierStats {
  total: number
  material: number
  finished: number
  disabled: number
}

export interface PaginatedSuppliers {
  data: Supplier[]
  meta: PageMeta
}

export interface VersionedSupplier {
  data: Supplier
  etag: string
}
