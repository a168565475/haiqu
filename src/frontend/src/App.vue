<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppHeader from '@/components/navigation/AppHeader.vue'
import AppSidebar from '@/components/navigation/AppSidebar.vue'
import ErpLayout from '@/layouts/ErpLayout.vue'
import PageContainer from '@/layouts/PageContainer.vue'
import { useAuthStore } from '@/stores/auth'
import { usePageTabsStore } from '@/stores/pageTabs'
import { useReferenceCacheSync } from '@/composables/useReferenceCacheSync'
import { pageInstanceKey } from '@/utils/pageInstanceKey'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const pageTabs = usePageTabsStore()
watch(() => [authStore.user?.id, JSON.stringify({
  permissions: [...(authStore.user?.permissions || [])].sort(),
  superuser: authStore.user?.is_superuser,
  salesAccess: authStore.user?.sales_access_enabled,
  moduleAccess: authStore.user?.module_access_enabled,
  employee: authStore.user?.employee,
  dataScope: authStore.user?.data_scope,
  effectiveAccess: authStore.user?.effective_access,
})] as const, ([userId, permissionSignature]) => {
  const previousAccount = pageTabs.accountId
  const previousPermissions = pageTabs.permissionSignature
  pageTabs.synchronizeAccount(userId, permissionSignature, router)
  if (pageTabs.accountId && (pageTabs.accountId !== previousAccount || previousPermissions !== permissionSignature)) {
    pageTabs.recordRoute(route)
  }
}, { immediate: true })
watch(() => route.fullPath, () => pageTabs.recordRoute(route))
useReferenceCacheSync()
const invalidateAuthenticationCheck = () => authStore.invalidateAuthenticationCheck()
const narrowSidebarViewport = ref(typeof window !== 'undefined'
  && window.innerWidth >= 769
  && window.innerWidth <= 1440)
const sidebarManuallyExpanded = ref(false)

const updateSidebarViewport = () => {
  narrowSidebarViewport.value = window.innerWidth >= 769 && window.innerWidth <= 1440
}

onMounted(() => {
  updateSidebarViewport()
  window.addEventListener('resize', updateSidebarViewport)
  window.addEventListener('focus', invalidateAuthenticationCheck)
  document.addEventListener('visibilitychange', invalidateAuthenticationCheck)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', updateSidebarViewport)
  window.removeEventListener('focus', invalidateAuthenticationCheck)
  document.removeEventListener('visibilitychange', invalidateAuthenticationCheck)
})
watch(() => route.fullPath, () => { sidebarManuallyExpanded.value = false })

const sidebarCollapsed = computed(() => !sidebarManuallyExpanded.value
  && narrowSidebarViewport.value)
const expandSidebar = () => {
  if (sidebarCollapsed.value) sidebarManuallyExpanded.value = true
}
const quotationRoutes = ['quotations', 'quotation-edit', 'quotation-preview', 'quotation-versions', 'quotation-packaging', 'quotation-price-history']
const quotationRoute = computed(() => quotationRoutes.includes(String(route.name || '')))
const wageSchemeRoute = computed(() => ['wage-schemes', 'wage-scheme-new', 'wage-scheme-change', 'wage-scheme-detail'].includes(String(route.name || '')))
const settingsRoutes = ['access-management', 'email-account-settings', 'reference-data-settings', 'theme-settings', 'master-data-center', 'production-data', 'inquiry-handling-settings', 'number-rules']
const settingsRoute = computed(() => settingsRoutes.includes(String(route.name || '')))
const fastReadLoadingRoute = computed(() => [
  'contacts', 'customer-duplicates',
  'customer-tasks', 'customer-complaints', 'customer-inquiries', 'customer-quotations', 'customer-samples', 'customer-orders',
  'customers', 'customer-detail', 'customer-contacts', 'customer-timeline',
  'inquiries', 'inquiry-detail', 'products', 'production-tasks', 'production-task-detail',
  'raw-materials',
  'complaints', 'complaint-detail',
  'tasks', 'task-detail',
  'sales-orders', 'sales-order-detail',
  'quotations', 'quotation-preview',
  'samples', 'sample-detail', 'sample-material-detail', 'sample-inventory', 'sample-outbound', 'sample-loans',
  'material-inventory', 'finished-goods-inventory', 'material-inbound-details',
  'boms', 'purchase-orders', 'purchase-order-confirm', 'purchase-inbounds', 'material-purchase-inbound', 'purchase-returns', 'material-quality-confirmation',
].includes(String(route.name || '')))
const compactBusinessRoutes = [
  'customer-duplicates', 'customer-transfer', 'contacts',
  'inquiries', 'inquiry-create', 'inquiry-edit', 'inquiry-detail',
  ...quotationRoutes,
  'sales-orders', 'sales-order-create', 'sales-order-edit', 'sales-order-detail',
  'complaints', 'complaint-detail',
  'tasks', 'task-detail',
]
const compactBusinessRoute = computed(() => compactBusinessRoutes.includes(String(route.name || '')))
const viewportTableRoute = computed(() => ['assembly-finished-receipt', 'finished-goods-inventory', 'internal-semi-receipt', 'semi-receipt-records', 'workshop-outsourcing-tube-new', 'workshop-outsourcing-tube-detail', 'workshop-outsourcing-tube-return', 'inventory-tube-return', 'access-management', 'complaints', 'inquiries', 'quotations', 'sales-orders', 'tasks', 'samples', 'sample-inventory', 'products', 'raw-materials', 'production-tasks', 'boms', 'work-report-days'].includes(String(route.name || '')))
const contentScrollRoutes = [
  'customer-transfer',
  'bom-edit',
  'complaint-detail',
  'production-task-create', 'production-task-edit', 'production-task-detail',
  'sample-fees', 'sample-fulfillment', 'sample-material-detail',
  'task-detail',
  'wage-scheme-new', 'wage-scheme-change',
  'work-report-new', 'work-report-edit', 'work-report-day-detail',
  'workshop-outsourcing-new', 'workshop-outsourcing-rework-detail', 'workshop-outsourcing-detail', 'workshop-outsourcing-factory-detail',
  'purchase-order-detail', 'purchase-inbound-detail',
]
const contentScrollRoute = computed(() => contentScrollRoutes.includes(String(route.name || '')))
</script>

<template>
  <RouterView v-slot="{ Component, route }">
    <ErpLayout
      v-if="route.meta.layout === 'erp'"
      :class="{
        'sample-library-layout': ['sample-inventory', 'sample-inventory-receipt-detail', 'sample-outbound-detail', 'sample-loan-detail', 'sample-outbound', 'sample-loans'].includes(String(route.name)),
        'quotation-layout': quotationRoute,
        'quotation-list-layout': route.name === 'quotations',
        'settings-layout': settingsRoute,
        'business-compact-layout': compactBusinessRoute,
        'production-scheduling-detail-layout': route.name === 'workshop-scheduling-detail',
        'wage-scheme-layout': wageSchemeRoute,
        'wage-scheme-detail-layout': route.name === 'wage-scheme-detail',
        'sample-form-layout': route.name === 'sample-edit',
        'sample-create-layout': route.name === 'sample-new',
        'sample-material-layout': route.name === 'sample-materials',
        'bom-create-layout': route.name === 'bom-create',
        'viewport-table-layout': viewportTableRoute,
        'content-scroll-layout': contentScrollRoute,
      }"
      :compact-sidebar="sidebarCollapsed"
      :sidebar-expanded="sidebarManuallyExpanded"
    >
      <template #sidebar>
        <AppSidebar :compact="sidebarCollapsed" :expanded="sidebarManuallyExpanded" />
      </template>
      <template #header>
        <AppHeader
          :compact="sidebarCollapsed"
          @expand-sidebar="expandSidebar"
        />
      </template>
      <PageContainer
        :key="pageInstanceKey(route, authStore.user?.id)"
        :class="{ 'fast-read-loading': fastReadLoadingRoute }"
        :width="route.meta.pageWidth"
        :flush="route.meta.flushPage === true || route.name === 'inquiries'"
        :fit-viewport="viewportTableRoute"
      >
        <component :is="Component" />
      </PageContainer>
    </ErpLayout>
    <component :is="Component" v-else />
  </RouterView>
</template>

<style scoped lang="scss">
// 仅缩短读取完成后的遮罩退场；loading 状态仍由真实请求决定。
.fast-read-loading :deep(.el-loading-mask) { transition-duration: 120ms; }
.sample-library-layout :deep(#erp-main-content) { overflow: auto; }
.viewport-table-layout :deep(#erp-main-content) { overflow: hidden; }
.content-scroll-layout :deep(#erp-main-content) { overflow-x: hidden; overflow-y: auto; }
.quotation-layout :deep(#erp-main-content) { overflow: auto; background: var(--erp-page-background); }
.quotation-layout :deep(.page-container) { padding: 14px; }
.wage-scheme-layout :deep(.app-header__search-shell) { width: 280px; }
.wage-scheme-detail-layout :deep(#erp-main-content) { overflow-x: hidden; overflow-y: auto; }
.quotation-layout :deep(.page-container__content) { min-height: 100%; }
.quotation-list-layout :deep(#erp-main-content) { overflow: hidden; }
.quotation-list-layout :deep(.page-container) { padding-bottom: 5px; }
.quotation-list-layout :deep(.page-container__content) { min-height: 0; }
.settings-layout :deep(#erp-main-content) { overflow: auto; background: var(--erp-page-background); }
.settings-layout :deep(.page-container) { padding: 14px; }
.production-scheduling-detail-layout :deep(#erp-main-content) { overflow: auto; background: var(--erp-page-background); }
.bom-create-layout :deep(#erp-main-content) { overflow-x: hidden; overflow-y: auto; }
.bom-create-layout :deep(.page-container), .bom-create-layout :deep(.page-container__content) { min-height: max-content; }
.sample-form-layout :deep(.page-container) { padding: 0; }
.sample-create-layout :deep(.page-container) { padding: 0; }
.sample-create-layout :deep(#erp-main-content .sample-create-page .application-heading-actions .el-button) {
  height: 32px !important;
  min-height: 32px !important;
  border-radius: 5px !important;
  line-height: 20px !important;
}
.sample-material-layout :deep(.page-container) { padding: 0; }

.business-compact-layout :deep(#erp-main-content .page-container:not(.page-container--flush)) {
  padding: 14px;
}

.business-compact-layout.quotation-list-layout :deep(#erp-main-content .page-container:not(.page-container--flush)) {
  padding-bottom: 5px;
}

.business-compact-layout :deep(#erp-main-content) {
  background: var(--erp-page-background);
}

.business-compact-layout :deep(#erp-main-content .el-button) {
  height: 32px !important;
  min-height: 32px !important;
  border-radius: 5px !important;
}

.business-compact-layout :deep(#erp-main-content .el-input__wrapper),
.business-compact-layout :deep(#erp-main-content .el-select__wrapper),
.business-compact-layout :deep(#erp-main-content .el-date-editor.el-input__wrapper),
.business-compact-layout :deep(#erp-main-content .el-input-number) {
  height: 32px !important;
  min-height: 32px !important;
  border-radius: 5px !important;
}

.business-compact-layout :deep(#erp-main-content .el-textarea__inner) {
  border-radius: 5px !important;
}

.business-compact-layout :deep(#erp-main-content .el-form-item) {
  margin-bottom: 10px !important;
}

.business-compact-layout :deep(#erp-main-content .header-actions),
.business-compact-layout :deep(#erp-main-content .heading-actions),
.business-compact-layout :deep(#erp-main-content .editor-actions),
.business-compact-layout :deep(#erp-main-content .filter-panel),
.business-compact-layout :deep(#erp-main-content .filters),
.business-compact-layout :deep(#erp-main-content .task-filters),
.business-compact-layout :deep(#erp-main-content .quotation-filter__grid),
.business-compact-layout :deep(#erp-main-content .quotation-toolbar),
.business-compact-layout :deep(#erp-main-content .task-toolbar),
.business-compact-layout :deep(#erp-main-content .table-toolbar),
.business-compact-layout :deep(#erp-main-content .filter-grid),
.business-compact-layout :deep(#erp-main-content .filter-card),
.business-compact-layout :deep(#erp-main-content .contact-toolbar),
.business-compact-layout :deep(#erp-main-content .batch-actions),
.business-compact-layout :deep(#erp-main-content .view-actions),
.business-compact-layout :deep(#erp-main-content .quotation-list-page__heading-actions),
.business-compact-layout :deep(#erp-main-content .quotation-toolbar > div),
.business-compact-layout :deep(#erp-main-content .quotation-filter__actions),
.business-compact-layout :deep(#erp-main-content .filter-actions),
.business-compact-layout :deep(#erp-main-content .detail-toolbar),
.business-compact-layout :deep(#erp-main-content .batch-head),
.business-compact-layout :deep(#erp-main-content .task-titlebar__actions),
.business-compact-layout :deep(#erp-main-content .task-toolbar__selection),
.business-compact-layout :deep(#erp-main-content .task-toolbar__tools) {
  gap: 10px !important;
}

.business-compact-layout :deep(#erp-main-content :where(.header-actions, .heading-actions, .editor-actions, .filter-panel, .filters, .task-filters, .quotation-filter__grid, .quotation-toolbar, .task-toolbar, .table-toolbar, .filter-grid, .filter-card, .contact-toolbar, .batch-actions, .view-actions, .quotation-list-page__heading-actions, .quotation-filter__actions, .filter-actions, .detail-toolbar, .batch-head, .task-titlebar__actions, .task-toolbar__selection, .task-toolbar__tools) .el-button + .el-button),
.business-compact-layout :deep(#erp-main-content .quotation-toolbar > div .el-button + .el-button) {
  margin-left: 0 !important;
}

:global(body:has(.business-compact-layout) .el-overlay .el-dialog),
:global(body:has(.business-compact-layout) .el-drawer) {
  border-radius: 5px !important;
}

:global(body:has(.business-compact-layout) .el-overlay .el-button),
:global(body:has(.business-compact-layout) .el-drawer .el-button),
:global(body:has(.business-compact-layout) .el-popper .el-button) {
  height: 32px !important;
  min-height: 32px !important;
  border-radius: 5px !important;
}

:global(body:has(.business-compact-layout) .el-overlay .el-input__wrapper),
:global(body:has(.business-compact-layout) .el-overlay .el-select__wrapper),
:global(body:has(.business-compact-layout) .el-overlay .el-date-editor.el-input__wrapper),
:global(body:has(.business-compact-layout) .el-overlay .el-input-number),
:global(body:has(.business-compact-layout) .el-drawer .el-input__wrapper),
:global(body:has(.business-compact-layout) .el-drawer .el-select__wrapper),
:global(body:has(.business-compact-layout) .el-drawer .el-date-editor.el-input__wrapper),
:global(body:has(.business-compact-layout) .el-popper .el-input__wrapper),
:global(body:has(.business-compact-layout) .el-popper .el-select__wrapper) {
  height: 32px !important;
  min-height: 32px !important;
  border-radius: 5px !important;
}

:global(body:has(.business-compact-layout) .el-popper),
:global(body:has(.business-compact-layout) .el-select-dropdown),
:global(body:has(.business-compact-layout) .el-dropdown-menu) {
  border-radius: 5px !important;
}

:global(body:has(.business-compact-layout) .el-select-dropdown__item),
:global(body:has(.business-compact-layout) .el-dropdown-menu__item) {
  height: 32px !important;
  min-height: 32px !important;
  line-height: 32px !important;
  border-radius: 5px !important;
}

:global(body:has(.business-compact-layout) .el-overlay .el-textarea__inner),
:global(body:has(.business-compact-layout) .el-drawer .el-textarea__inner) {
  border-radius: 5px !important;
}

:global(body:has(.business-compact-layout) .el-overlay .el-form-item),
:global(body:has(.business-compact-layout) .el-drawer .el-form-item),
:global(body:has(.business-compact-layout) .el-popper .el-form-item) {
  margin-bottom: 10px !important;
}

:global(body:has(.business-compact-layout) .el-overlay .el-dialog__header) { padding: 16px 20px 12px; }
:global(body:has(.business-compact-layout) .el-overlay .el-dialog__body) { padding: 12px 20px; }
:global(body:has(.business-compact-layout) .el-overlay .el-dialog__footer) { padding: 12px 20px 16px; }
:global(body:has(.business-compact-layout) .el-drawer__header) { min-height: 60px; margin-bottom: 0; padding: 14px 20px; }
:global(body:has(.business-compact-layout) .el-drawer__body) { padding: 14px 20px; }
:global(body:has(.business-compact-layout) .el-drawer__footer) { padding: 12px 20px 16px; }

</style>
