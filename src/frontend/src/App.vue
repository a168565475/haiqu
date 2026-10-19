<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppHeader from '@/components/navigation/AppHeader.vue'
import AppSidebar from '@/components/navigation/AppSidebar.vue'
import ErpLayout from '@/layouts/ErpLayout.vue'
import PageContainer from '@/layouts/PageContainer.vue'
import { useAuthStore } from '@/stores/auth'
import { installWeComRoleGuard } from '@/api/wecomSession'
import { usePageTabsStore } from '@/stores/pageTabs'
import { useReferenceCacheSync } from '@/composables/useReferenceCacheSync'
import { pageInstanceKey } from '@/utils/pageInstanceKey'
import { glassListRouteNames } from '@/config/glassListRoutes'
import { glassDetailRouteNames } from '@/config/glassDetailRoutes'
import { glassFormRouteNames } from '@/config/glassFormRoutes'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const removeWeComRoleGuard = installWeComRoleGuard(router, authStore)
const pageTabs = usePageTabsStore()
watch(() => [authStore.user?.id, JSON.stringify({
  permissions: [...(authStore.user?.permissions || [])].sort(),
  superuser: authStore.user?.is_superuser,
  salesAccess: authStore.user?.sales_access_enabled,
  moduleAccess: authStore.user?.module_access_enabled,
  employee: authStore.user?.employee,
  dataScope: authStore.user?.data_scope,
  effectiveAccess: authStore.user?.effective_access,
  waitingForRole: authStore.user?.waiting_for_role,
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

onMounted(() => {
  window.addEventListener('focus', invalidateAuthenticationCheck)
  document.addEventListener('visibilitychange', invalidateAuthenticationCheck)
})
onBeforeUnmount(() => {
  removeWeComRoleGuard()
  window.removeEventListener('focus', invalidateAuthenticationCheck)
  document.removeEventListener('visibilitychange', invalidateAuthenticationCheck)
})

const quotationRoutes = ['quotations', 'quotation-edit', 'quotation-preview', 'quotation-versions', 'quotation-packaging', 'quotation-price-history']
const quotationRoute = computed(() => quotationRoutes.includes(String(route.name || '')))
const wageSchemeRoute = computed(() => ['wage-schemes', 'wage-scheme-new', 'wage-scheme-change', 'wage-scheme-detail'].includes(String(route.name || '')))
const settingsRoutes = ['wecom-settings', 'access-management', 'email-account-settings', 'reference-data-settings', 'theme-settings', 'master-data-center', 'production-data', 'inquiry-handling-settings', 'number-rules']
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
  'customer-duplicates', 'contacts',
  'inquiries', 'inquiry-create', 'inquiry-edit', 'inquiry-detail',
  ...quotationRoutes,
  'sales-orders', 'sales-order-create', 'sales-order-edit', 'sales-order-detail',
  'complaints', 'complaint-detail',
  'tasks', 'task-detail',
]
const glassDetailRoute = computed(() => (glassDetailRouteNames as readonly string[]).includes(String(route.name || '')))
const glassFormRoute = computed(() => (glassFormRouteNames as readonly string[]).includes(String(route.name || '')))
const compactBusinessRoute = computed(() => !glassDetailRoute.value && !glassFormRoute.value && compactBusinessRoutes.includes(String(route.name || '')))
const glassListRoute = computed(() => (glassListRouteNames as readonly string[]).includes(String(route.name || '')))
const viewportTableRoute = computed(() => (!glassDetailRoute.value || ['workshop-outsourcing-tube-detail', 'material-issue-detail'].includes(String(route.name))) && (glassListRoute.value || [
  'assembly-finished-receipt', 'finished-goods-inventory', 'internal-semi-receipt', 'semi-receipt-records',
  'workshop-outsourcing-tube-new', 'workshop-outsourcing-tube-detail', 'workshop-outsourcing-tube-return', 'inventory-tube-return',
  'access-management', 'complaints', 'inquiries', 'quotations', 'sales-orders', 'tasks', 'samples', 'sample-inventory',
  'products', 'raw-materials', 'material-catalog', 'product-catalog', 'production-tasks', 'boms', 'work-report-days',
  // 这些页面已提供内部滚动，由外壳分配高度，避免旧视口常量撑出额外滚动条。
  'customers', 'purchase-orders', 'purchase-inbounds', 'purchase-returns',
  'supplier-purchase-sheet-editor', 'sample-edit', 'sample-materials', 'sample-warehouse-review',
  'material-issue-detail',
  'suppliers', 'supplier-purchase-sheets', 'purchase-contract-templates', 'purchase-sheet-template-select',
  'material-inventory', 'workshop-scheduling',
  'workshop-metalworking-plan', 'workshop-cutting-plan', 'workshop-sewing-plan', 'workshop-assembly-plan',
  'sample-outbound', 'sample-loans',
  'reference-data-settings', 'master-data-center', 'production-data', 'number-rules',
].includes(String(route.name || ''))))
const contentScrollRoutes = [
  'customer-transfer',
  'bom-edit',
  'complaint-detail',
  'production-task-create', 'production-task-manual-create', 'production-task-edit', 'production-task-detail',
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
        'customer-list-layout': route.name === 'customers',
        'customer-detail-layout': ['customer-detail', 'customer-timeline', 'customer-tasks', 'customer-inquiries', 'customer-quotations', 'customer-samples', 'customer-orders', 'customer-complaints'].includes(String(route.name)),
        'glass-list-layout': glassListRoute,
        'glass-detail-layout': glassDetailRoute,
        'glass-form-layout': glassFormRoute,
        'settings-layout': settingsRoute,
        'business-compact-layout': compactBusinessRoute,
        'production-scheduling-detail-layout': route.name === 'workshop-scheduling-detail',
        'wage-scheme-layout': wageSchemeRoute,
        'wage-scheme-detail-layout': route.name === 'wage-scheme-detail',
        'sample-form-layout': route.name === 'sample-edit',
        'sample-create-layout': route.name === 'sample-new',
        'sample-material-layout': route.name === 'sample-materials',
        'bom-create-layout': route.name === 'bom-create',
        'bom-editor-layout': route.name === 'bom-edit',
        'viewport-table-layout': viewportTableRoute,
        'content-scroll-layout': contentScrollRoute,
      }"
    >
      <template #sidebar>
        <AppSidebar />
      </template>
      <template #header>
        <AppHeader />
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
.customer-list-layout :deep(.page-container) { padding: 0; }
.content-scroll-layout :deep(#erp-main-content) { overflow-x: hidden; overflow-y: auto; }
.quotation-layout :deep(#erp-main-content) { overflow: auto; background: transparent; }
.quotation-layout :deep(.page-container) { padding: 14px; }
.wage-scheme-detail-layout :deep(#erp-main-content) { overflow-x: hidden; overflow-y: auto; }
.quotation-layout :deep(.page-container__content) { min-height: 100%; }
.quotation-list-layout :deep(#erp-main-content) { overflow: hidden; }
.quotation-list-layout :deep(.page-container) { padding-bottom: 5px; }
.quotation-list-layout :deep(.page-container__content) { min-height: 0; }
.glass-list-layout :deep(#erp-main-content .page-container) { padding: 0; }
.glass-detail-layout :deep(#erp-main-content) { overflow: auto; background: transparent; }
.glass-detail-layout.viewport-table-layout :deep(#erp-main-content) { overflow: hidden; }
.glass-detail-layout :deep(#erp-main-content .page-container) { padding: 14px; }
@media screen {
  .glass-detail-layout :deep(#erp-main-content .page-container),
  .customer-detail-layout :deep(#erp-main-content .page-container) { padding: 0; }
}
.glass-form-layout :deep(#erp-main-content .page-container) { padding: 14px; }
.glass-form-layout.bom-editor-layout :deep(#erp-main-content .page-container),
.glass-form-layout.wage-scheme-layout :deep(#erp-main-content .page-container) { padding: 0; }
.settings-layout :deep(#erp-main-content) { overflow: auto; background: transparent; }
.settings-layout :deep(.page-container) { padding: 14px; }
.production-scheduling-detail-layout :deep(#erp-main-content) { overflow: auto; background: transparent; }
.bom-create-layout :deep(#erp-main-content) { overflow-x: hidden; overflow-y: auto; }
.bom-create-layout :deep(.page-container), .bom-create-layout :deep(.page-container__content) { min-height: max-content; }
.sample-form-layout :deep(.page-container) { padding: 0; }
.sample-create-layout :deep(.page-container) { padding: 0; }
.sample-create-layout :deep(#erp-main-content .sample-create-page .application-heading-actions .el-button) {
  height: 32px !important;
  min-height: 32px !important;
  border-radius: var(--erp-radius-control) !important;
  line-height: 20px !important;
}
.sample-material-layout :deep(.page-container) { padding: 0; }

.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .page-container:not(.page-container--flush)) {
  padding: 14px;
}

.business-compact-layout.quotation-list-layout:not(.glass-list-layout) :deep(#erp-main-content .page-container:not(.page-container--flush)) {
  padding-bottom: 5px;
}

.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content) {
  background: transparent;
}

.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .el-button) {
  height: 32px !important;
  min-height: 32px !important;
  border-radius: 5px !important;
}

.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .el-input__wrapper),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .el-select__wrapper),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .el-date-editor.el-input__wrapper),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .el-input-number) {
  height: 32px !important;
  min-height: 32px !important;
  border-radius: 5px !important;
}

.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .el-textarea__inner) {
  border-radius: 5px !important;
}

.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .el-form-item) {
  margin-bottom: 10px !important;
}

.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .header-actions),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .heading-actions),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .editor-actions),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .filter-panel),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .filters),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .task-filters),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .quotation-filter__grid),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .quotation-toolbar),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .task-toolbar),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .table-toolbar),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .filter-grid),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .filter-card),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .contact-toolbar),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .batch-actions),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .view-actions),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .quotation-list-page__heading-actions),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .quotation-toolbar > div),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .quotation-filter__actions),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .filter-actions),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .detail-toolbar),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .batch-head),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .task-titlebar__actions),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .task-toolbar__selection),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .task-toolbar__tools) {
  gap: 10px !important;
}

.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content :where(.header-actions, .heading-actions, .editor-actions, .filter-panel, .filters, .task-filters, .quotation-filter__grid, .quotation-toolbar, .task-toolbar, .table-toolbar, .filter-grid, .filter-card, .contact-toolbar, .batch-actions, .view-actions, .quotation-list-page__heading-actions, .quotation-filter__actions, .filter-actions, .detail-toolbar, .batch-head, .task-titlebar__actions, .task-toolbar__selection, .task-toolbar__tools) .el-button + .el-button),
.business-compact-layout:not(.glass-list-layout) :deep(#erp-main-content .quotation-toolbar > div .el-button + .el-button) {
  margin-left: 0 !important;
}

:global(body:has(.business-compact-layout) .el-overlay:not(:has(.cus05-contact-drawer, .cus05-history-drawer)) .el-dialog),
:global(body:has(.business-compact-layout) .el-drawer:not(.cus05-contact-drawer, .cus05-history-drawer)) {
  border-radius: 5px !important;
}

:global(body:has(.business-compact-layout) .el-overlay:not(:has(.cus05-contact-drawer, .cus05-history-drawer)) .el-button),
:global(body:has(.business-compact-layout) .el-drawer:not(.cus05-contact-drawer, .cus05-history-drawer) .el-button),
:global(body:has(.business-compact-layout) .el-popper:not(.erp-list-filter-popover) .el-button) {
  height: 32px !important;
  min-height: 32px !important;
  border-radius: 5px !important;
}

:global(body:has(.business-compact-layout) .el-overlay:not(:has(.cus05-contact-drawer, .cus05-history-drawer)) .el-input__wrapper),
:global(body:has(.business-compact-layout) .el-overlay:not(:has(.cus05-contact-drawer, .cus05-history-drawer)) .el-select__wrapper),
:global(body:has(.business-compact-layout) .el-overlay:not(:has(.cus05-contact-drawer, .cus05-history-drawer)) .el-date-editor.el-input__wrapper),
:global(body:has(.business-compact-layout) .el-overlay:not(:has(.cus05-contact-drawer, .cus05-history-drawer)) .el-input-number),
:global(body:has(.business-compact-layout) .el-drawer:not(.cus05-contact-drawer, .cus05-history-drawer) .el-input__wrapper),
:global(body:has(.business-compact-layout) .el-drawer:not(.cus05-contact-drawer, .cus05-history-drawer) .el-select__wrapper),
:global(body:has(.business-compact-layout) .el-drawer:not(.cus05-contact-drawer, .cus05-history-drawer) .el-date-editor.el-input__wrapper),
:global(body:has(.business-compact-layout) .el-popper:not(.erp-list-filter-popover) .el-input__wrapper),
:global(body:has(.business-compact-layout) .el-popper:not(.erp-list-filter-popover) .el-select__wrapper) {
  height: 32px !important;
  min-height: 32px !important;
  border-radius: 5px !important;
}

:global(body:has(.business-compact-layout) .el-popper:not(.erp-list-filter-popover)),
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

:global(body:has(.business-compact-layout) .el-overlay:not(:has(.cus05-contact-drawer, .cus05-history-drawer)) .el-textarea__inner),
:global(body:has(.business-compact-layout) .el-drawer:not(.cus05-contact-drawer, .cus05-history-drawer) .el-textarea__inner) {
  border-radius: 5px !important;
}

:global(body:has(.business-compact-layout) .el-overlay:not(:has(.cus05-contact-drawer, .cus05-history-drawer)) .el-form-item),
:global(body:has(.business-compact-layout) .el-drawer:not(.cus05-contact-drawer, .cus05-history-drawer) .el-form-item),
:global(body:has(.business-compact-layout) .el-popper:not(.erp-list-filter-popover) .el-form-item) {
  margin-bottom: 10px !important;
}

:global(body:has(.business-compact-layout) .el-overlay:not(:has(.cus05-contact-drawer, .cus05-history-drawer)) .el-dialog__header) { padding: 16px 20px 12px; }
:global(body:has(.business-compact-layout) .el-overlay:not(:has(.cus05-contact-drawer, .cus05-history-drawer)) .el-dialog__body) { padding: 12px 20px; }
:global(body:has(.business-compact-layout) .el-overlay:not(:has(.cus05-contact-drawer, .cus05-history-drawer)) .el-dialog__footer) { padding: 12px 20px 16px; }
:global(body:has(.business-compact-layout) .el-drawer:not(.cus05-contact-drawer, .cus05-history-drawer) .el-drawer__header) { min-height: 60px; margin-bottom: 0; padding: 14px 20px; }
:global(body:has(.business-compact-layout) .el-drawer:not(.cus05-contact-drawer, .cus05-history-drawer) .el-drawer__body) { padding: 14px 20px; }
:global(body:has(.business-compact-layout) .el-drawer:not(.cus05-contact-drawer, .cus05-history-drawer) .el-drawer__footer) { padding: 12px 20px 16px; }

</style>
