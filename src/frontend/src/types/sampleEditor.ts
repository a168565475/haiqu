import type { SampleProduct } from './sample'

export interface SampleProductCandidate {
  id: string
  product_name: string
  specification: string
  category_id: string
}

export interface SampleProductEdit {
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
