export type ReferenceStatus = 'ACTIVE' | 'INACTIVE'

export interface PageMeta {
  page: number
  page_size: number
  total: number
  total_pages: number
}

export interface PaginatedReferenceData<T> {
  data: T[]
  meta: PageMeta
}

export interface DataResponse<T> {
  data: T
}

export interface PublishedOption {
  id: string
  code: string
  label: string
  english_label: string
  status: ReferenceStatus
  sort_order: number
  color: string
  extra: Record<string, unknown>
}

export interface PublishedOptionsResponse {
  data: PublishedOption[]
  meta: {
    config_version: number | null
    config_revision?: string
  }
}

export interface VersionedReferenceData<T> {
  data: T
  etag: string
}

export interface DictionaryType {
  id: string
  code: string
  chinese_name: string
  english_name: string
  group_code: string
  status: ReferenceStatus
  sort_order: number
  description: string
  item_count: number
  active_item_count: number
  reference_count: number
  created_at: string
  updated_at: string
  archived_at: string | null
}

export interface DictionaryItem {
  id: string
  dictionary_type: string
  type_code: string
  item_code: string
  display_name: string
  english_name: string
  description: string
  status: ReferenceStatus
  sort_order: number
  color: string
  extra_data: Record<string, unknown>
  reference_count: number
  created_at: string
  updated_at: string
  archived_at: string | null
}

export interface SystemParameter {
  id: string
  code: string
  chinese_name: string
  english_name: string
  group_code: string
  value_type: 'STRING' | 'INTEGER' | 'BOOLEAN' | 'DATE_FORMAT' | 'COUNTRY_CODE' | 'CURRENCY_CODE'
  default_value: unknown
  draft_value: unknown
  validation_rules: Record<string, number>
  status: ReferenceStatus
  sort_order: number
  description: string
  updated_at: string
}

export interface ConfigRelease {
  id: string
  version: number
  status: 'DRAFT' | 'PUBLISHED' | 'FAILED'
  notes: string
  published_at: string | null
  published_by: {
    id: string
    employee_code: string
    display_name: string
  } | null
  failure_message: string
  created_at: string
  updated_at: string
}

export interface NumberRule {
  id: string
  number_type: string
  chinese_name: string
  prefix: string
  format_pattern: string
  sequence_name: string
  sequence_padding: number
  date_granularity: 'NONE' | 'YEAR' | 'MONTH' | 'DAY'
  reset_policy: 'NEVER' | 'DAILY' | 'YEARLY'
  is_configured: boolean
  status: ReferenceStatus
  sort_order: number
  description: string
  created_at: string
  updated_at: string
}

export interface ReferenceDataSummary {
  active_dictionary_items: number
  active_system_parameters: number
  pending_changes: number
  config_version: number | null
}

export interface DictionaryTypeInput {
  chinese_name: string
  english_name: string
  group_code: string
  sort_order: number
  description: string
}

export interface DictionaryItemInput {
  dictionary_type: string
  item_code: string
  display_name: string
  english_name: string
  description: string
  sort_order: number
  color: string
  extra_data: Record<string, unknown>
}

export interface ReferenceListQuery {
  page?: number
  page_size?: number
  q?: string
  status?: ReferenceStatus | ''
  type_code?: string
}

export interface ReferenceDataApiError {
  error?: {
    code?: string
    message?: string
    field_errors?: Record<string, string[]>
  }
}

export type MasterDataResource =
  | 'countries'
  | 'currencies'
  | 'exchange-rates'
  | 'units'
  | 'incoterms'
  | 'payment-methods'
  | 'transport-methods'
  | 'ports'
  | 'couriers'

export interface MasterDataSummary {
  category_counts: Record<string, number>
  standard_source_count: number
  standard_sources: string[]
  base_currency: string | null
  config_version: number | null
}

export interface CodedMasterData {
  id: string
  code: string
  chinese_name: string
  english_name: string
  status: ReferenceStatus
  sort_order: number
  source_version: string
  description: string
  extra_data: Record<string, unknown>
  created_at: string
  updated_at: string
  archived_at: string | null
}

export interface Country extends CodedMasterData {
  alpha3_code: string
  numeric_code: string
}

export interface Currency extends CodedMasterData {
  numeric_code: string
  decimal_places: number
  symbol: string
}

export interface Unit extends CodedMasterData {
  symbol: string
  category: string
  decimal_places: number
}

export interface Incoterm extends CodedMasterData {
  rules_version: string
  transport_scope: string
}

export interface Port extends CodedMasterData {
  country: string
  country_code: string
  country_name: string
  administrative_area: string
}

export interface Courier extends CodedMasterData {
  tracking_url_template: string
}

export interface ExchangeRate {
  id: string
  base_currency: string
  base_currency_code: string
  quote_currency: string
  quote_currency_code: string
  rate: string
  effective_date: string
  source_name: string
  source_version: string
  status: ReferenceStatus
  description: string
  entered_by_employee: string | null
  entered_by_name: string
  correction_of: string | null
  created_at: string
  updated_at: string
}

export type MasterDataRecord = CodedMasterData | Country | Currency | Unit | Incoterm | Port | Courier | ExchangeRate

export interface MasterDataListQuery extends ReferenceListQuery {
  source?: string
  base_currency?: string
  quote_currency?: string
  country_code?: string
}

export type MasterDataInput = Record<string, unknown>
