export interface EmployeeDirectoryEmployee {
  id: string
  employee_code: string
  display_name: string
  status: 'ACTIVE' | 'INACTIVE' | 'LEFT'
  archived: boolean
  has_account: boolean
  account_active: boolean
  etag: string
}

export interface EmployeeDirectoryDepartment {
  id: number
  parentid: number
  name: string
}

export interface EmployeeDirectoryDepartmentAssignment {
  department_id: string
  department_name: string
  is_primary: boolean
}

export interface EmployeeDirectoryDepartmentPlan {
  status: 'READY' | 'PENDING' | 'PRESERVED'
  reason: string
  assignments: EmployeeDirectoryDepartmentAssignment[]
}

export interface EmployeeDirectoryMember {
  userid: string
  name: string
  department: number[]
  main_department: number | null
  status: number | null
  status_label: string
  action: 'CREATE' | 'EXISTING' | 'REVIEW' | 'SKIP'
  reason: string
  employee: EmployeeDirectoryEmployee | null
  candidates: EmployeeDirectoryEmployee[]
  department_plan?: EmployeeDirectoryDepartmentPlan
}

export interface EmployeeDirectoryPreview {
  corp_id: string
  departments: EmployeeDirectoryDepartment[]
  members: EmployeeDirectoryMember[]
  preview_token: string
  apply_departments: boolean
}

export interface EmployeeDirectoryPreviewResponse {
  data: EmployeeDirectoryPreview
  etag: string
}

export interface EmployeeDirectorySyncInput {
  preview_token: string
  user_ids: string[]
  confirmed_new_user_ids?: string[]
  apply_departments?: boolean
}

export interface EmployeeDirectoryMatchInput {
  preview_token: string
  user_id: string
  employee_id: string
  employee_etag: string
  confirmed: true
  apply_departments?: boolean
}

export interface EmployeeDirectoryResult {
  user_id: string
  employee_id: string
  result: 'CREATED' | 'MATCHED' | 'EXISTING'
  department_status?: 'APPLIED' | 'PENDING' | 'PRESERVED'
  department_reason?: string
}

export interface DepartmentMapping {
  id: string
  wecom_department_id: number
  organization_unit_id: string | null
  updated_at: string
  organization_etag: string | null
  organization_active: boolean
  organization_name: string
}

export interface DepartmentMappingOrganization {
  id: string
  unit_code: string
  unit_name: string
  status: 'ACTIVE' | 'INACTIVE'
  archived: boolean
  etag: string
}

export interface DepartmentMappingSourceDepartment extends EmployeeDirectoryDepartment {
  mapping: DepartmentMapping | null
  candidates: DepartmentMappingOrganization[]
}

export interface DepartmentMappingPreview {
  corp_id: string
  departments: DepartmentMappingSourceDepartment[]
  organizations: DepartmentMappingOrganization[]
  preview_token: string
}

export interface DepartmentMappingPreviewResponse {
  data: DepartmentMappingPreview
  etag: string
}

export interface DepartmentMappingInput {
  preview_token: string
  organization_unit_id: string | null
  organization_etag?: string | null
  confirmed: true
}
