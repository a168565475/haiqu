import type { SampleProduct } from './sample'
import type { ProductCatalogSelectionOption, ProductSelectionInput, ProductSelectionSnapshot } from './productCatalog'

export interface SampleProductCandidate extends ProductCatalogSelectionOption {
  product_name: string
}

export interface SampleProductEdit {
  product_catalog_id?: string | null
  product_selection?: ProductSelectionInput | null
  product_selection_snapshot?: ProductSelectionSnapshot | null
  id: string
  product_id: string
  category_id: string
  product_name: string
  specification: string
  length_cm: string | null
  armrest_width_cm: string | null
  seat_width_cm: string | null
  back_height_cm: string | null
  seat_height_cm: string | null
  details: Array<Pick<SampleProduct['details'][number], 'id' | 'color_code' | 'tolerance' | 'notes'> & {
    product_color_id: string
    sample_quantity: number | null
  }>
}
