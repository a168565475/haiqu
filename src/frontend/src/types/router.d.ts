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
    headerTitle?: string
    breadcrumbs?: AppBreadcrumbItem[]
    pageWidth?: 'fluid' | 'contained'
    compactSidebar?: boolean
    flushPage?: boolean
  }
}
