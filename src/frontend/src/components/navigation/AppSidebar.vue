<script setup lang="ts">
import { computed, ref, watch, type Component } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ArrowRight } from '@element-plus/icons-vue'
import { ElPopover } from 'element-plus'
import AssemblyLine from '@icon-park/vue-next/es/icons/AssemblyLine'
import Box from '@icon-park/vue-next/es/icons/Box'
import ChartHistogram from '@icon-park/vue-next/es/icons/ChartHistogram'
import Checklist from '@icon-park/vue-next/es/icons/Checklist'
import Commodity from '@icon-park/vue-next/es/icons/Commodity'
import ConnectionPoint from '@icon-park/vue-next/es/icons/ConnectionPoint'
import Cube from '@icon-park/vue-next/es/icons/Cube'
import DatabaseAlert from '@icon-park/vue-next/es/icons/DatabaseAlert'
import FactoryBuilding from '@icon-park/vue-next/es/icons/FactoryBuilding'
import Export from '@icon-park/vue-next/es/icons/Export'
import purchaseReturnsIcon from '@/assets/crm-v2/purchase-returns.svg'
import Folder from '@icon-park/vue-next/es/icons/Folder'
import IdCardH from '@icon-park/vue-next/es/icons/IdCardH'
import Mail from '@icon-park/vue-next/es/icons/Mail'
import MessageOne from '@icon-park/vue-next/es/icons/MessageOne'
import Order from '@icon-park/vue-next/es/icons/Order'
import People from '@icon-park/vue-next/es/icons/People'
import Setting from '@icon-park/vue-next/es/icons/Setting'
import ShoppingCart from '@icon-park/vue-next/es/icons/ShoppingCart'
import Ticket from '@icon-park/vue-next/es/icons/Ticket'
import TransactionOrder from '@icon-park/vue-next/es/icons/TransactionOrder'
import Truck from '@icon-park/vue-next/es/icons/Truck'
import Workbench from '@icon-park/vue-next/es/icons/Workbench'
import '@icon-park/vue-next/styles/index.css'
import { useAuthStore } from '@/stores/auth'
import { resolveWorkbenchMode } from '@/utils/workbench'

withDefaults(
  defineProps<{
    compact?: boolean
    expanded?: boolean
  }>(),
  {
    compact: false,
    expanded: false,
  },
)

interface MenuItem {
  key: string
  label: string
  icon: Component
  iconImage?: string
  to?: { name: string }
  permission?: string
  anyPermissions?: string[]
  allPermissions?: string[]
  available?: boolean
  children?: MenuItem[]
}

const route = useRoute()
const authStore = useAuthStore()
const activeMenu = computed(() => {
  return typeof route.meta.activeMenu === 'string' ? route.meta.activeMenu : ''
})

const menuItems: MenuItem[] = [
  { key: 'workbench', label: '工作台', icon: Workbench, to: { name: 'home' } },
  {
    key: 'customer-management',
    label: '客户管理',
    icon: People,
    children: [
      { key: 'customers', label: '客户列表', icon: IdCardH, to: { name: 'customers' }, permission: 'customers.view_customeraccount' },
      { key: 'complaints', label: '客诉管理', icon: MessageOne, to: { name: 'complaints' }, permission: 'customers.view_customercomplaint' },
      { key: 'inquiries', label: '询盘管理', icon: Mail, to: { name: 'inquiries' }, permission: 'inquiries.view_inquiry' },
      { key: 'quotations', label: '报价管理', icon: Ticket, to: { name: 'quotations' }, permission: 'quotations.view_quotation' },
      { key: 'sales-orders', label: '销售订单', icon: TransactionOrder, to: { name: 'sales-orders' } },
      { key: 'tasks', label: '任务中心', icon: Checklist, to: { name: 'tasks' }, permission: 'workflow.view_businesstask' },
      { key: 'analytics', label: '分析中心', icon: ChartHistogram, permission: 'customers.view_customeraccount' },
    ],
  },
  {
    key: 'sample-management',
    label: '样品管理',
    icon: Order,
    children: [
      { key: 'samples', label: '打样申请', icon: Order, to: { name: 'samples' }, permission: 'samples.view_samplerequest' },
      { key: 'sample-library', label: '样品库', icon: Folder, to: { name: 'sample-inventory' }, permission: 'samples.view_sampleinventoryline' },
    ],
  },
  {
    key: 'product-management',
    label: '产品管理',
    icon: Commodity,
    children: [
      { key: 'products', label: '产品信息', icon: Commodity, to: { name: 'products' }, permission: 'products.view_productinformation' },
      { key: 'raw-materials', label: '原料信息', icon: Cube, to: { name: 'raw-materials' }, permission: 'products.view_rawmaterialinformation' },
    ],
  },
  {
    key: 'production-management',
    label: '生产管理',
    icon: FactoryBuilding,
    children: [
      { key: 'production-tasks', label: '生产订单', icon: Checklist, to: { name: 'production-tasks' }, permission: 'production_tasks.view_productiontask' },
      { key: 'boms', label: 'BOM 管理', icon: ConnectionPoint, to: { name: 'boms' }, permission: 'boms.view_bom' },
    ],
  },
  {
    key: 'procurement-management',
    label: '采购管理',
    icon: ShoppingCart,
    children: [
      { key: 'purchase-orders', label: '采购订单', icon: ShoppingCart, to: { name: 'purchase-orders' }, anyPermissions: ['procurement.view_purchaseorder', 'procurement.view_supplier'] },
      { key: 'purchase-inbounds', label: '采购入库', icon: Truck, to: { name: 'purchase-inbounds' }, anyPermissions: ['inventory.receive_material', 'inventory.quality_confirm_material'] },
      { key: 'purchase-returns', label: '退货明细', icon: Export, iconImage: purchaseReturnsIcon, to: { name: 'purchase-returns' }, permission: 'procurement.view_purchaseorder' },
    ],
  },
  {
    key: 'workshop-management',
    label: '生产车间',
    icon: AssemblyLine,
    children: [
      { key: 'workshop-configuration', label: '生产配置', icon: Setting, to: { name: 'workshop-configuration' }, permission: 'workshop_config.view_workshop' },
      { key: 'workshop-scheduling', label: '计划排产', icon: Checklist, to: { name: 'workshop-scheduling' }, permission: 'production_scheduling.view_productionschedule' },
      { key: 'workshop-internal-plan', label: '内部计划', icon: FactoryBuilding, to: { name: 'workshop-metalworking-plan' }, permission: 'production_scheduling.view_productionschedule' },
      { key: 'workshop-outsourcing', label: '委外加工', icon: Export, to: { name: 'workshop-outsourcing' }, anyPermissions: ['outsourcing.view_outsourcingorder', 'material_issues.view_metalprocessingsource'] },
      { key: 'material-issues', label: '生产领料', icon: Truck, to: { name: 'material-issues' }, permission: 'material_issues.view_materialissue' },
      { key: 'wage-schemes', label: '工价方案', icon: Ticket, to: { name: 'wage-schemes' }, permission: 'workshop_reporting.view_wagescheme' },
      { key: 'work-report-days', label: '报工记录', icon: TransactionOrder, to: { name: 'work-report-days' }, allPermissions: ['workshop_reporting.view_workreport', 'production_scheduling.view_productionschedule'] },
    ],
  },
  {
    key: 'warehouse-management',
    label: '仓库管理',
    icon: Truck,
    children: [
      { key: 'finished-goods-inventory', label: '成品库存', icon: Box, to: { name: 'finished-goods-inventory' }, permission: 'inventory.view_finishedgoodsreceipt' },
      { key: 'material-inventory', label: '材料库存', icon: Cube, to: { name: 'material-inventory' }, permission: 'inventory.view_materialinbound' },
      { key: 'defective-inventory', label: '不良品库存', icon: Box, permission: 'inventory.view_finishedgoodsreceipt' },
      { key: 'inventory-warning', label: '库存预警', icon: DatabaseAlert, permission: 'inventory.view_finishedgoodsreceipt' },
    ],
  },
]

const canShowMenuItem = (item: MenuItem) => {
  if (item.available === false) {
    return false
  }
  if (item.anyPermissions) {
    return authStore.user?.is_superuser === true || authStore.hasAnyPermission(item.anyPermissions)
  }
  if (item.allPermissions) {
    return authStore.user?.is_superuser === true || item.allPermissions.every(permission => authStore.hasPermission(permission))
  }
  if (item.key === 'sales-orders' && authStore.user?.sales_access_enabled) return authStore.hasPermission('sales_orders.view_salesorder')
  return !item.permission || authStore.hasPermission(item.permission)
}

const visibleMenuItems = computed(() => {
  return menuItems.flatMap((item) => {
    if (item.children) {
      const visibleChildren = item.children.filter(canShowMenuItem)
      return visibleChildren.length > 0 ? [{ ...item, children: visibleChildren }] : []
    }
    return canShowMenuItem(item) ? [item] : []
  })
})

const expandedGroups = ref<Record<string, boolean>>({})
watch(
  activeMenu,
  (menuKey) => {
    const activeGroup = menuItems.find((item) => item.children?.some((child) => child.key === menuKey))
    if (activeGroup) expandedGroups.value = { [activeGroup.key]: true }
  },
  { immediate: true },
)
const isMenuActive = (item: MenuItem) => {
  return item.key === activeMenu.value || item.children?.some((child) => child.key === activeMenu.value) === true
}
const toggleMenuGroup = (key: string) => {
  const shouldExpand = !expandedGroups.value[key]
  expandedGroups.value = shouldExpand ? { [key]: true } : {}
}

const systemPermissions = [
  'reference_data.view_dictionarytype',
  'reference_data.view_referencedictionary',
  'reference_data.view_systemparameterdefinition',
  'reference_data.view_country',
  'reference_data.view_currency',
  'reference_data.view_exchangerate',
  'reference_data.view_unit',
  'reference_data.view_incoterm',
  'reference_data.view_paymentmethod',
  'reference_data.view_transportmethod',
  'reference_data.view_port',
  'reference_data.view_courier',
  'reference_data.view_numberrule',
  'workflow.view_slapolicy',
]
const canManageOwnEmailAccounts = computed(() => authStore.user?.employee !== null && authStore.user?.employee !== undefined)
const canViewSystemSettings = computed(() => canManageOwnEmailAccounts.value || authStore.user?.is_superuser || authStore.hasAnyPermission(systemPermissions))
const canViewReferenceSettings = computed(() => authStore.user?.is_superuser || authStore.hasAnyPermission(systemPermissions.slice(0, 3)))
const systemEntryRoute = computed(() => {
  if (canViewReferenceSettings.value) return 'reference-data-settings'
  if (authStore.hasPermission('workflow.view_slapolicy')) return 'inquiry-handling-settings'
  if (canManageOwnEmailAccounts.value) return 'email-account-settings'
  return 'master-data-center'
})
const workbenchLabel = computed(() => resolveWorkbenchMode(authStore.user) === 'MANAGER' ? '主管工作台' : '业务工作台')
</script>

<template>
  <nav
    class="app-sidebar app-sidebar--crm-v2"
    :class="{ 'app-sidebar--compact': compact, 'app-sidebar--expanded': expanded }"
    aria-label="ERP 主导航"
  >
    <div class="app-sidebar__scroll">
      <ul class="app-sidebar__menu">
        <li v-for="item in visibleMenuItems" :key="item.key" class="app-sidebar__menu-group">
          <template v-if="item.children?.length">
            <ElPopover
              v-if="compact"
              trigger="hover"
              placement="right-start"
              :offset="12"
              :show-after="100"
              :hide-after="160"
              :show-arrow="false"
              popper-class="app-sidebar-flyout-popper"
            >
              <template #reference>
                <button
                  type="button"
                  class="app-sidebar__menu-item app-sidebar__menu-button"
                  :class="{ 'is-active': isMenuActive(item) }"
                  aria-haspopup="true"
                  :aria-label="`${item.label}，悬停显示子菜单`"
                  :title="item.label"
                  :data-menu-key="item.key"
                >
                  <span class="app-sidebar__menu-icon" aria-hidden="true">
                    <component :is="item.icon" theme="outline" size="20" :stroke-width="9.6" fill="currentColor" />
                  </span>
                  <span class="app-sidebar__menu-label">{{ item.label }}</span>
                </button>
              </template>

              <div class="app-sidebar__flyout" :aria-label="`${item.label}子菜单`" :data-flyout-menu-key="item.key">
                <div class="app-sidebar__flyout-title">{{ item.label }}</div>
                <component
                  :is="child.to ? RouterLink : 'div'"
                  v-for="child in item.children"
                  :key="child.key"
                  :to="child.to"
                  class="app-sidebar__flyout-link"
                  :class="{ 'is-active': activeMenu === child.key, 'is-disabled': !child.to }"
                  :aria-current="activeMenu === child.key ? 'page' : undefined"
                  :aria-disabled="child.to ? undefined : 'true'"
                  :title="child.to ? child.label : `${child.label}（暂未开放）`"
                  :data-menu-key="child.key"
                >
                  <span class="app-sidebar__flyout-icon" aria-hidden="true">
                    <img v-if="child.iconImage" :src="child.iconImage" width="18" height="18" alt="" />
                    <component v-else :is="child.icon" theme="outline" size="18" :stroke-width="9.6" fill="currentColor" />
                  </span>
                  <span>{{ child.label }}</span>
                </component>
              </div>
            </ElPopover>

            <template v-else>
            <button
              type="button"
              class="app-sidebar__menu-item app-sidebar__menu-button"
              :class="{ 'is-active': isMenuActive(item) }"
              :aria-expanded="Boolean(expandedGroups[item.key])"
              :aria-controls="`${item.key}-submenu`"
              :title="item.label"
              :data-menu-key="item.key"
              @click="toggleMenuGroup(item.key)"
            >
              <span class="app-sidebar__menu-icon" aria-hidden="true">
                <component
                  :is="item.icon"
                  theme="outline"
                  size="20"
                  :stroke-width="9.6"
                  fill="currentColor"
                />
              </span>
              <span class="app-sidebar__menu-label">{{ item.label }}</span>
              <span class="app-sidebar__menu-arrow" :class="{ 'is-expanded': expandedGroups[item.key] }" aria-hidden="true">
                <ArrowRight />
              </span>
            </button>

            <ul v-show="expandedGroups[item.key]" :id="`${item.key}-submenu`" class="app-sidebar__submenu">
              <li v-for="child in item.children" :key="child.key" class="app-sidebar__submenu-entry">
                <component
                  :is="child.to ? RouterLink : 'div'"
                  :to="child.to"
                  class="app-sidebar__submenu-link"
                  :class="{ 'is-active': activeMenu === child.key, 'is-disabled': !child.to }"
                  :aria-current="activeMenu === child.key ? 'page' : undefined"
                  :aria-disabled="child.to ? undefined : 'true'"
                  :title="child.to ? child.label : `${child.label}（暂未开放）`"
                  :data-menu-key="child.key"
                >
                  <span class="app-sidebar__submenu-icon" aria-hidden="true">
                    <img v-if="child.iconImage" :src="child.iconImage" width="20" height="20" alt="" />
                    <component
                      v-else
                        :is="child.icon"
                      theme="outline"
                      size="20"
                        :stroke-width="9.6"
                      fill="currentColor"
                    />
                  </span>
                  <span class="app-sidebar__submenu-label">{{ child.label }}</span>
                </component>
              </li>
            </ul>
            </template>
          </template>

          <template v-else>
            <component
              :is="item.to ? RouterLink : 'div'"
              :to="item.to"
              class="app-sidebar__menu-item"
              :class="{ 'is-active': activeMenu === item.key }"
              :aria-current="activeMenu === item.key ? 'page' : undefined"
              :aria-disabled="item.to ? undefined : 'true'"
              :title="item.label"
              :data-menu-key="item.key"
            >
              <span class="app-sidebar__menu-icon" aria-hidden="true">
                <component
                  :is="item.icon"
                  theme="outline"
                  size="20"
                      :stroke-width="9.6"
                  fill="currentColor"
                />
              </span>
              <span class="app-sidebar__menu-label">{{ item.label }}</span>
            </component>

            <div
              v-if="item.key === 'workbench' && activeMenu === 'workbench'"
              class="app-sidebar__submenu-link app-sidebar__submenu-item is-active"
              aria-current="page"
            >
              {{ workbenchLabel }}
            </div>
          </template>
        </li>
        <li v-if="authStore.user?.username === 'admin' && authStore.user.is_superuser" class="app-sidebar__menu-group">
          <RouterLink
            :to="{ name: 'access-management' }"
            class="app-sidebar__menu-item"
            :class="{ 'is-active': route.name === 'access-management' }"
            :aria-current="route.name === 'access-management' ? 'page' : undefined"
            title="权限管理"
            data-menu-key="access-management"
          >
            <span class="app-sidebar__menu-icon" aria-hidden="true">
              <Setting theme="outline" size="20" :stroke-width="9.6" fill="currentColor" />
            </span>
            <span class="app-sidebar__menu-label">权限管理</span>
          </RouterLink>
        </li>
        <li v-if="canViewSystemSettings" class="app-sidebar__menu-group">
          <RouterLink
            :to="{ name: systemEntryRoute }"
            class="app-sidebar__menu-item"
            :class="{ 'is-active': activeMenu === 'settings' && route.name !== 'access-management' && route.name !== 'theme-settings' }"
            :aria-current="activeMenu === 'settings' && route.name !== 'access-management' && route.name !== 'theme-settings' ? 'page' : undefined"
            title="系统配置"
            data-menu-key="settings"
          >
            <span class="app-sidebar__menu-icon" aria-hidden="true">
              <Setting theme="outline" size="20" :stroke-width="9.6" fill="currentColor" />
            </span>
            <span class="app-sidebar__menu-label">系统配置</span>
          </RouterLink>
        </li>
        <li v-if="canViewSystemSettings" class="app-sidebar__menu-group">
          <RouterLink
            :to="{ name: 'theme-settings' }"
            class="app-sidebar__menu-item"
            :class="{ 'is-active': route.name === 'theme-settings' }"
            :aria-current="route.name === 'theme-settings' ? 'page' : undefined"
            title="界面主题"
            data-menu-key="theme-settings"
          >
            <span class="app-sidebar__menu-icon" aria-hidden="true">
              <Setting theme="outline" size="20" :stroke-width="9.6" fill="currentColor" />
            </span>
            <span class="app-sidebar__menu-label">界面主题</span>
          </RouterLink>
        </li>
      </ul>
    </div>
  </nav>
</template>

<style scoped lang="scss">
.app-sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 18px 14px 48px;
  color: #cbd5e1;
}

.app-sidebar__scroll {
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 4px;
  overscroll-behavior-y: contain;
  scrollbar-color: rgba(148, 163, 184, 0.34) transparent;
  scrollbar-width: none;
}

.app-sidebar__scroll::-webkit-scrollbar {
  width: 0;
  height: 0;
  display: none;
}

.app-sidebar__scroll::-webkit-scrollbar-track {
  background: transparent;
}

.app-sidebar__scroll::-webkit-scrollbar-thumb {
  min-height: 48px;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.34);
}

.app-sidebar__scroll::-webkit-scrollbar-thumb:hover {
  background: rgba(203, 213, 225, 0.58);
}

.app-sidebar__scroll::-webkit-scrollbar-button {
  width: 0;
  height: 0;
  display: none;
}

.app-sidebar__menu {
  margin: 0;
  padding: 0;
  list-style: none;
}

.app-sidebar__menu-group + .app-sidebar__menu-group {
  margin-top: 8px;
}

.app-sidebar__menu-item,
.app-sidebar__system {
  width: 100%;
  height: 44px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 12px;
  border-radius: 6px;
  color: #cbd5e1;
  font-size: 15px;
  font-weight: 500;
  line-height: 1;
  text-decoration: none;
  white-space: nowrap;
  transition: color 160ms ease, background-color 160ms ease;
}

.app-sidebar__menu-button {
  border: 0;
  background: transparent;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.app-sidebar__menu-arrow {
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-left: auto;
  color: currentColor;
  transform: rotate(0deg);
  transition: transform 160ms ease;
}

.app-sidebar__menu-arrow.is-expanded {
  transform: rotate(90deg);
}

.app-sidebar__menu-item.is-active,
.app-sidebar__system.is-active {
  color: #fff;
  background: rgba(255, 255, 255, 0.08);
}

.app-sidebar__menu-button.is-active {
  background: transparent;
}

.app-sidebar__menu-item:hover:not(.is-active),
.app-sidebar__system:hover:not(.is-active) {
  color: #fff;
  background: rgba(255, 255, 255, 0.06);
  box-shadow: none;
}

a.app-sidebar__menu-item:focus-visible {
  outline: 2px solid #94a3b8;
  outline-offset: 2px;
}

button.app-sidebar__menu-item:focus-visible,
a.app-sidebar__submenu-link:focus-visible {
  outline: 2px solid #94a3b8;
  outline-offset: 2px;
}

a.app-sidebar__system:focus-visible {
  outline: 2px solid #94a3b8;
  outline-offset: 2px;
}

.app-sidebar__menu-icon {
  flex: none;
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.app-sidebar__menu-icon :deep(svg) {
  width: 22px;
  height: 22px;
}

.app-sidebar__menu-icon :deep(.i-icon),
.app-sidebar__submenu-icon :deep(.i-icon) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 0;
}

.app-sidebar__submenu {
  position: relative;
  margin: 6px 0 0;
  padding: 0 0 0 4px;
  list-style: none;
}

.app-sidebar__submenu::before {
  content: '';
  position: absolute;
  top: 4px;
  bottom: 4px;
  left: 20px;
  width: 1px;
  background: rgba(148, 163, 184, 0.2);
}

.app-sidebar__submenu-entry + .app-sidebar__submenu-entry {
  margin-top: 4px;
}

.app-sidebar__submenu-link {
  min-height: 40px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 12px 0 28px;
  border-radius: 6px;
  color: #aeb9c9;
  font-size: 14px;
  line-height: 1;
  text-decoration: none;
  white-space: nowrap;
  transition: color 160ms ease, background-color 160ms ease;
}

.app-sidebar__submenu-link:hover:not(.is-active):not(.is-disabled) {
  color: #fff;
  background: rgba(255, 255, 255, 0.06);
}

.app-sidebar__submenu-link.is-active {
  position: relative;
  color: #0f172a;
  background: #f8fafc;
  font-weight: 600;
}

.app-sidebar__submenu-link.is-active::before {
  content: '';
  position: absolute;
  left: 7px;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #d97706;
}

.app-sidebar__submenu-link.is-disabled {
  color: #64748b;
  cursor: not-allowed;
}

.app-sidebar__submenu-icon {
  flex: none;
  width: 19px;
  height: 19px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.app-sidebar__submenu-icon :deep(svg) {
  width: 19px;
  height: 19px;
}

.app-sidebar__submenu-item {
  height: 40px;
  display: flex;
  align-items: center;
  margin-top: 8px;
  padding-left: 40px;
  color: #aeb9c9;
  font-size: 14px;
  line-height: 1;
  white-space: nowrap;
}

.app-sidebar__system {
  flex: none;
  position: relative;
  margin-top: 16px;
}

.app-sidebar__system::before {
  content: '';
  position: absolute;
  top: -9px;
  left: 0;
  right: 0;
  height: 1px;
  background: rgba(148, 163, 184, 0.18);
}

.app-sidebar--compact {
  padding: 19px 12px 48px;
}

.app-sidebar--compact .app-sidebar__menu-item,
.app-sidebar--compact .app-sidebar__system {
  width: 40px;
  justify-content: center;
  padding: 0;
}

.app-sidebar--compact .app-sidebar__menu-label,
.app-sidebar--compact .app-sidebar__menu-arrow,
.app-sidebar--compact .app-sidebar__submenu-item,
.app-sidebar--compact .app-sidebar__submenu-label {
  display: none;
}

.app-sidebar--compact .app-sidebar__submenu {
  margin-top: 4px;
  padding-left: 0;
}

.app-sidebar--compact .app-sidebar__submenu::before {
  display: none;
}

.app-sidebar--compact .app-sidebar__submenu-link {
  width: 40px;
  height: 36px;
  min-height: 36px;
  justify-content: center;
  padding: 0;
}

.app-sidebar--compact .app-sidebar__submenu-icon {
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.app-sidebar--compact .app-sidebar__submenu-icon :deep(svg) {
  width: 18px;
  height: 18px;
}

.app-sidebar--compact .app-sidebar__submenu-link.is-active::before {
  display: none;
}


@media (max-width: 1440px) and (min-width: 769px) {
  .app-sidebar {
    padding: 19px 12px 48px;
  }

  .app-sidebar__menu-item,
  .app-sidebar__system {
    width: 40px;
    justify-content: center;
    padding: 0;
  }

  .app-sidebar__menu-label,
  .app-sidebar__menu-arrow,
  .app-sidebar__submenu-item {
    display: none;
  }

  .app-sidebar__submenu {
    margin-top: 4px;
    padding-left: 0;
  }

  .app-sidebar__submenu::before {
    display: none;
  }

  .app-sidebar__submenu-link {
    width: 40px;
    height: 36px;
    min-height: 36px;
    justify-content: center;
    padding: 0;
  }

  .app-sidebar__submenu-label {
    display: none;
  }

  .app-sidebar__submenu-icon {
    width: 18px;
    height: 18px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .app-sidebar__submenu-icon :deep(svg) {
    width: 18px;
    height: 18px;
  }

  .app-sidebar__submenu-link.is-active::before {
    display: none;
  }
}

.app-sidebar--crm-v2 {
  box-sizing: border-box;
  padding: 18px 10px 48px;
  color: #f7f4ec;
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
}


.app-sidebar--crm-v2 .app-sidebar__scroll {
  padding-right: 0;
  scrollbar-color: rgba(198, 195, 186, 0.32) transparent;
}

.app-sidebar--crm-v2 .app-sidebar__menu-group + .app-sidebar__menu-group {
  margin-top: 4px;
}

.app-sidebar--crm-v2 .app-sidebar__menu-item,
.app-sidebar--crm-v2 .app-sidebar__system {
  height: 44px;
  gap: 12px;
  padding: 0 14px;
  border-radius: 6px;
  color: #f7f4ec;
  font-size: 14px;
  font-weight: 400;
  line-height: 20px;
}

.app-sidebar--crm-v2 .app-sidebar__menu-button.is-active {
  color: #f7f4ec;
  background: transparent;
  font-weight: 500;
}

.app-sidebar--crm-v2 [data-menu-key='workbench'].is-active {
  background: transparent;
}

.app-sidebar--crm-v2 .app-sidebar__menu-item:hover:not(.is-active),
.app-sidebar--crm-v2 .app-sidebar__system:hover:not(.is-active) {
  color: #faf8f2;
  background: #2a2926;
}

.app-sidebar--crm-v2 .app-sidebar__menu-icon,
.app-sidebar--crm-v2 .app-sidebar__menu-icon :deep(svg) {
  width: 20px;
  height: 20px;
}

.app-sidebar--crm-v2 .app-sidebar__menu-icon {
  color: #c4bfb3;
}

.app-sidebar--crm-v2 .app-sidebar__menu-item.is-active .app-sidebar__menu-icon,
.app-sidebar--crm-v2 .app-sidebar__system.is-active .app-sidebar__menu-icon {
  color: #f5f0e6;
}

.app-sidebar--crm-v2 .app-sidebar__menu-arrow,
.app-sidebar--crm-v2 .app-sidebar__menu-arrow :deep(svg) {
  width: 18px;
  height: 18px;
}

.app-sidebar--crm-v2 .app-sidebar__submenu {
  margin: 4px 0 0;
  padding: 0;
}

.app-sidebar--crm-v2 .app-sidebar__submenu::before {
  display: none;
}

.app-sidebar--crm-v2 .app-sidebar__submenu-icon,
.app-sidebar--crm-v2 .app-sidebar__submenu-icon :deep(svg) {
  width: 20px;
  height: 20px;
}

.app-sidebar--crm-v2 .app-sidebar__submenu-icon {
  display: inline-flex;
  color: #c4bfb3;
}

.app-sidebar--crm-v2 .app-sidebar__submenu-entry + .app-sidebar__submenu-entry {
  margin-top: 4px;
}

.app-sidebar--crm-v2 .app-sidebar__submenu-link {
  position: relative;
  width: 210px;
  height: 40px;
  min-height: 40px;
  gap: 10px;
  padding: 0 14px 0 30px;
  border-radius: 6px;
  color: #f7f4ec;
  font-size: 13px;
  line-height: 20px;
}

.app-sidebar--crm-v2 .app-sidebar__submenu-link:hover:not(.is-active):not(.is-disabled) {
  color: #faf8f2;
  background: #2a2926;
}

.app-sidebar--crm-v2 .app-sidebar__submenu-link:hover:not(.is-active):not(.is-disabled) .app-sidebar__submenu-icon {
  color: #f5f0e6;
}

.app-sidebar--crm-v2 .app-sidebar__submenu-link.is-active {
  color: #1f1d18;
  background: #fcfbf7;
  font-weight: 500;
}

.app-sidebar--crm-v2 .app-sidebar__submenu-link.is-active .app-sidebar__submenu-icon {
  color: #1f1d18;
}

.app-sidebar--crm-v2 .app-sidebar__submenu-link.is-active::before {
  top: 0;
  bottom: 0;
  left: 0;
  width: 4px;
  height: 40px;
  border-radius: 3px 0 0 3px;
  background: #c84e28;
}

.app-sidebar--crm-v2 .app-sidebar__system {
  margin-top: 16px;
  padding: 0 16px;
  font-size: 13px;
}

.app-sidebar--crm-v2 .app-sidebar__system::before {
  top: -9px;
  right: 6px;
  left: 6px;
  background: #2a2926;
}

@media (max-width: 1440px) and (min-width: 769px) {
  .app-sidebar--crm-v2 {
    padding: 18px 12px 48px;
  }

  .app-sidebar--crm-v2 .app-sidebar__menu-item,
  .app-sidebar--crm-v2 .app-sidebar__system,
  .app-sidebar--crm-v2 .app-sidebar__submenu-link {
    width: 40px;
    justify-content: center;
    padding: 0;
  }

  .app-sidebar--crm-v2 .app-sidebar__submenu-icon {
    width: 18px;
    height: 18px;
    display: inline-flex;
  }

  .app-sidebar--crm-v2 .app-sidebar__submenu-icon :deep(svg) {
    width: 18px;
    height: 18px;
  }

  .app-sidebar--crm-v2 .app-sidebar__submenu-link.is-active::before {
    display: none;
  }
}

.app-sidebar--expanded {
  padding: 18px 10px 48px;
}

.app-sidebar--expanded .app-sidebar__menu-item,
.app-sidebar--expanded .app-sidebar__system {
  width: 100%;
  justify-content: flex-start;
  padding: 0 14px;
}

.app-sidebar--expanded .app-sidebar__menu-label,
.app-sidebar--expanded .app-sidebar__menu-arrow,
.app-sidebar--expanded .app-sidebar__submenu-label {
  display: inline-flex;
}

.app-sidebar--expanded .app-sidebar__submenu-link {
  width: 210px;
  height: 40px;
  min-height: 40px;
  justify-content: flex-start;
  padding: 0 14px 0 30px;
}

.app-sidebar--crm-v2.app-sidebar--expanded .app-sidebar__submenu-link.is-active::before {
  display: block;
}

.app-sidebar__flyout {
  width: 210px;
  box-sizing: border-box;
  padding: 6px;
  color: #f7f4ec;
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
}

.app-sidebar__flyout-title {
  padding: 7px 10px 9px;
  color: #a9a398;
  font-size: 12px;
  line-height: 18px;
}

.app-sidebar__flyout-link {
  min-height: 38px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 10px;
  border-radius: 5px;
  color: #f7f4ec;
  font-size: 13px;
  line-height: 18px;
  text-decoration: none;
}

.app-sidebar__flyout-link:hover:not(.is-disabled),
.app-sidebar__flyout-link:focus-visible:not(.is-disabled) {
  color: #faf8f2;
  background: #34332f;
  outline: none;
}

.app-sidebar__flyout-link.is-active {
  color: #1f1d18;
  background: #fcfbf7;
  font-weight: 500;
}

.app-sidebar__flyout-link.is-disabled {
  color: #716d65;
  cursor: not-allowed;
}

.app-sidebar__flyout-icon {
  width: 18px;
  height: 18px;
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.app-sidebar__flyout-icon :deep(.i-icon),
.app-sidebar__flyout-icon :deep(svg) {
  width: 18px;
  height: 18px;
}

:global(.app-sidebar-flyout-popper.el-popper) {
  min-width: 0;
  padding: 0;
  overflow: hidden;
  border: 1px solid #34332f;
  border-radius: 7px;
  background: #1c1c1a;
  box-shadow: 0 12px 28px rgba(31, 29, 24, 0.24);
}
</style>
