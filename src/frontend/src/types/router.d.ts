import 'vue-router'

export interface AppBreadcrumbItem {
  label: string
  to?: string
}

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    layout?: 'erp'
    activeMenu?: string
    outsourcingWorkspace?: 'warehouse'
    headerTitle?: string
    breadcrumbs?: AppBreadcrumbItem[]
    pageWidth?: 'fluid' | 'contained'
    compactSidebar?: boolean
    flushPage?: boolean
  }
}
