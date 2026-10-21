import type { PageMeta } from './referenceData'

export type EditableResourceKind = 'employees' | 'crafts' | 'operations'
export type ResourceKind = 'workshops' | EditableResourceKind
export type RecordStatus = 'ACTIVE' | 'INACTIVE'
export type WorkshopEmployeeStatus = 'ACTIVE' | 'LEFT'
export type CraftType = 'INTERNAL' | 'EXTERNAL'
export type PlanCategory = 'METAL' | 'CUTTING' | 'SEWING' | 'ASSEMBLY'
export type OutsourcingCode = 'POWDER_COATING' | 'EMBROIDERY' | 'SCREEN_PRINTING' | 'CUTTING' | 'SEWING'

export interface Workshop {
  id: string
  name: string
  status: RecordStatus
  status_display: string
  employee_count: number
  active_employee_count: number
  active_supervisor_count: number
  craft_count: number
  active_craft_count: number
  operation_count: number
  created_at: string
  updated_at: string
}

export interface WorkshopEmployee {
  id: string
  workshop: string
  workshop_name: string
  position: string
  name: string
  employee: string | null
  employee_code: string | null
  employee_name: string | null
  employee_status: string | null
  employee_archived: boolean
  is_supervisor: boolean
  status: WorkshopEmployeeStatus
  status_display: string
  created_at: string
  updated_at: string
}

export interface Craft {
  id: string
  craft_type: CraftType
  craft_type_display: string
  plan_category: PlanCategory | null
  plan_category_display: string | null
  outsourcing_code: OutsourcingCode | null
  outsourcing_code_display: string | null
  workshop: string | null
  workshop_name: string | null
  name: string
  status: RecordStatus
  status_display: string
  operation_count: number
  active_operation_count: number
  created_at: string
  updated_at: string
}

export interface Operation {
  id: string
  operation_number: string
  product_name: string
  craft: string
  craft_name: string
  craft_type: CraftType
  craft_type_display: string
  workshop: string | null
  workshop_name: string | null
  name: string
  reporting_unit: string | null
  reporting_unit_name: string | null
  status: RecordStatus
  status_display: string
  created_at: string
  updated_at: string
}

export type WorkshopConfigRecord = Workshop | WorkshopEmployee | Craft | Operation

export interface WorkshopEmployeeInput {
  workshop: string
  position: string
  employee?: string
  is_supervisor: boolean
  status: WorkshopEmployeeStatus
}

export interface WorkshopEmployeeOption {
  id: string
  employee_code: string
  display_name: string
  status: string
  etag: string
}

export interface WorkshopEmployeeOptions {
  data: WorkshopEmployeeOption[]
  meta: PageMeta
}

export interface CraftInput {
  craft_type: CraftType
  plan_category: PlanCategory | null
  outsourcing_code: OutsourcingCode | null
  workshop: string | null
  name: string
  status: RecordStatus
}

export interface OperationInput {
  operation_number: string
  product_name: string
  craft: string
  name: string
  reporting_unit?: string | null
  status: RecordStatus
}

export type WorkshopConfigInput = WorkshopEmployeeInput | CraftInput | OperationInput

export interface PaginatedWorkshopConfig<T extends WorkshopConfigRecord> {
  data: T[]
  meta: PageMeta
}

export interface VersionedWorkshopConfig<T extends WorkshopConfigRecord> {
  data: T
  etag: string
}

export type WorkshopConfigQuery = Record<string, string | number | boolean | undefined>
export type WorkshopConfigSummary = Record<string, number>
