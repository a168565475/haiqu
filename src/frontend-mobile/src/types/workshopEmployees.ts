export interface WorkshopOption {
  id: string
  name: string
  status: 'ACTIVE' | 'INACTIVE'
}

export interface WorkshopEmployee {
  id: string
  name: string
  employee: string | null
  employee_name: string | null
  employee_code: string | null
  employee_status: string | null
  employee_archived: boolean
  workshop: string | null
  workshop_name: string
  position: string
  department: string
  roles: string
  is_supervisor: boolean
  status: 'ACTIVE' | 'LEFT'
  status_display: string
  can_edit: boolean
  role_workshop: string | null
  role_workshop_name: string | null
  created_at: string
  updated_at: string
}

export interface WorkshopEmployeeInput {
  workshop: string
  position: string
  is_supervisor: boolean
  status: 'ACTIVE' | 'LEFT'
}

export interface WorkshopEmployeeOptions {
  workshops: WorkshopOption[]
  editable_workshops: WorkshopOption[]
}

export interface WorkshopEmployeePage {
  data: WorkshopEmployee[]
  meta: { page: number; page_size: number; total: number; total_pages: number }
}

export interface WorkshopEmployeeQuery {
  page: number
  q?: string
  workshop?: string
  position_state?: 'SET' | 'UNSET' | 'ROLE_PENDING' | 'ROLE_ALL'
}

export interface VersionedWorkshopEmployee { data: WorkshopEmployee; etag: string }
