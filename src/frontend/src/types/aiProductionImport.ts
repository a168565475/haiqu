export type AiReasoningEffort = 'auto' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'

export interface AiImportReasoningSettings {
  document_reasoning_effort: AiReasoningEffort
  material_reasoning_effort: AiReasoningEffort
}

export interface AiOpenAiConfig extends Partial<AiImportReasoningSettings> {
  id?: string
  configured?: boolean
  key_configured?: boolean
  label: string
  provider: string
  model: string
  base_url?: string
  key_last4: string
  key_fingerprint: string
  created_at?: string
  updated_at: string | null
}

export interface AiOpenAiConfigInput extends Partial<AiImportReasoningSettings> {
  label: string
  provider: string
  model: string
  base_url?: string
  api_key: string
}

export type AiImportState = 'UPLOADED' | 'CONVERTING' | 'RECOGNIZING' | 'REVIEW' | 'FAILED' | 'TASK_DRAFT' | 'BOM_PENDING'

export interface AiImportIssue {
  id?: string
  code?: string
  severity: 'blocking' | 'warning' | 'info'
  message: string
  source_refs?: string[]
  field_path?: string | null
  action?: string
}

export interface AiImportSource {
  source_id: string
  file_id?: string
  original_name?: string
  sheet?: string
  cell_range?: string
  text?: string
  image_id?: string | null
}

export interface AiImportIssuePayload extends Omit<AiImportIssue, 'severity'> {
  severity?: AiImportIssue['severity']
  issue_key?: string
  kind?: string
  source_ids?: string[]
}

export interface AiImportSourcePayload extends Partial<AiImportSource> {
  ref?: string
  kind?: string
}

export interface AiProductionImportRecord {
  id: string
  state: AiImportState | string
  phase: string
  original_name: string
  progress?: { stage: string; message?: string; updated_at?: string } | null
  result: Record<string, unknown> | null
  active_task_key?: string
  task_choices?: Array<{ task_key: string; task_number: string; state: string; task_id?: string | null }>
  has_created_tasks?: boolean
  has_previous_recognition?: boolean
  review_draft?: AiImportReviewDraft | null
  issues: AiImportIssue[]
  sources: AiImportSource[]
  task_payload?: Record<string, unknown> | null
  bom_payload?: Record<string, unknown> | null
  task_id?: string | null
  task_number?: string
  task_status?: string
  task_products?: Array<{ id: string; client_key?: string; product_name_snapshot?: string; specification_snapshot?: string; quantity?: string }>
  bom_id?: string | null
  bom_ids?: string[]
  error_code?: string
  created_at?: string
  updated_at?: string
}

export interface AiImportReviewDraft {
  task_key?: string
  task_payload: Record<string, unknown> | null
  bom_plans: Array<Record<string, unknown>> | null
}

export type AiImportRecordSummary = Pick<AiProductionImportRecord,
  'id' | 'state' | 'original_name' | 'task_number' | 'task_id' | 'bom_ids' | 'created_at' | 'updated_at'>

export interface AiProductionImportResponse {
  data: AiProductionImportRecord
  replay?: boolean
  etag?: string
}

export interface AiProductionImportPayload extends Omit<AiProductionImportRecord, 'issues' | 'sources'> {
  issues: AiImportIssuePayload[]
  sources: AiImportSource[] | Record<string, AiImportSourcePayload>
}

