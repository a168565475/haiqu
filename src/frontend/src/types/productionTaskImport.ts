import type { ProductionTaskInput } from './productionTask'

export interface ExtractedField { status: 'EXTRACTED' | 'MISSING' | 'CONFLICT'; value: string | boolean | null; raw_text?: string | null; source_ids: string[] }
export interface ImportCandidate {
  object_id: string; candidate_key: string; task_number_original: string | null; product_summary: string
  version_description: string | null; grouping_uncertain: boolean; uncertainty_reason: string | null
  sheets: { name: string; state: string }[]
}
export interface ImportIssue { id: string; type: string; message: string; blocking: boolean; source_ids: string[]; field_path: string | null }
export type ImportPayload = Omit<ProductionTaskInput, 'contract_number' | 'contract_number_token' | 'import_object_id' | 'result_revision'>
export interface ImportReview {
  payload: ImportPayload; confirmed_fields: string[]
  issues: Record<string, { status: 'RESOLVED' | 'TODO'; note: string }>
  selected_images: Record<string, string | null>
}
export interface ProductionTaskImport {
  id: string; state: string; phase: string; original_name: string; scan_status: string; expires_at: string
  attempt_no: number; result_revision: number; candidates: ImportCandidate[]; selected_candidate: Partial<ImportCandidate>
  extraction: { fields?: Record<string, ExtractedField>; products?: { line_key: string; fields: Record<string, ExtractedField> }[]
    image_candidates?: { image_id: string; proposed_product_line_key: string | null; note: string | null; proposed_use: string; source_ids: string[] }[]
    unmapped_content?: { summary: string; source_ids: string[] }[] }
  matching: { products?: Record<string, { status: string; candidates: { id: string; name: string; specification: string; version: string }[]; units: { id: string; name: string; code: string }[] }>
    salespersons?: { id: string; name: string }[]; followers?: { id: string; name: string }[] }
  review: Partial<ImportReview>; issues: ImportIssue[]; error_code: string; blocked_reason: string
  saved_task_id: string | null; saved_task_number: string; saved_at: string | null
  duplicates: { id: string; state: string; saved_task_number: string; object_id: string }[]
}
export interface VersionedImport { data: ProductionTaskImport; etag: string }
