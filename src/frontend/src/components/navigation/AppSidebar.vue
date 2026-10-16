<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch, type Component } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Protect from '@icon-park/vue-next/es/icons/Protect'
import Platte from '@icon-park/vue-next/es/icons/Platte'
import flyoutBrand from '@/assets/crm-v2/hitree-inquiry.svg'
import warehouseIcon from '@/assets/navigation/warehouse.svg'
import homeIcon from '@/assets/navigation/house.svg'
import calendarIcon from '@/assets/navigation/calendar.svg'
import documentIcon from '@/assets/navigation/document-lines.svg'
import Home from '@icon-park/vue-next/es/icons/Home'
import Box from '@icon-park/vue-next/es/icons/Box'
import ChartHistogram from '@icon-park/vue-next/es/icons/ChartHistogram'
import ChartHistogramTwo from '@icon-park/vue-next/es/icons/ChartHistogramTwo'
import Checklist from '@icon-park/vue-next/es/icons/Checklist'
import Commodity from '@icon-park/vue-next/es/icons/Commodity'
import ConnectionPoint from '@icon-park/vue-next/es/icons/ConnectionPoint'
import Cube from '@icon-park/vue-next/es/icons/Cube'
import PackageCube from '@icon-park/vue-next/es/icons/WeixinFavorites'
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
import Peoples from '@icon-park/vue-next/es/icons/Peoples'
import Setting from '@icon-park/vue-next/es/icons/Setting'
import ShoppingCart from '@icon-park/vue-next/es/icons/ShoppingCart'
import Ticket from '@icon-park/vue-next/es/icons/Ticket'
import TransactionOrder from '@icon-park/vue-next/es/icons/TransactionOrder'
import Truck from '@icon-park/vue-next/es/icons/Truck'
import '@icon-park/vue-next/styles/index.css'
import { useAuthStore } from '@/stores/auth'

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
  { key: 'workbench', label: '工作台', icon: Home, iconImage: homeIcon, to: { name: 'home' } },
  {
    key: 'customer-management',
    label: '客户',
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
    label: '样品',
    icon: PackageCube,
    children: [
      { key: 'samples', label: '打样申请', icon: Order, to: { name: 'samples' }, permission: 'samples.view_samplerequest' },
      { key: 'sample-library', label: '样品库', icon: Folder, to: { name: 'sample-inventory' }, permission: 'samples.view_sampleinventoryline' },
    ],
  },
  {
    key: 'product-management',
    label: '产品',
    icon: PackageCube,
    children: [
      { key: 'products', label: '产品信息', icon: Commodity, to: { name: 'products' }, permission: 'products.view_productinformation' },
      { key: 'raw-materials', label: '原料信息', icon: Cube, to: { name: 'raw-materials' }, permission: 'products.view_rawmaterialinformation' },
    ],
  },
  {
    key: 'production-management',
    label: '生产',
    icon: FactoryBuilding,
    children: [
      { key: 'production-tasks', label: '生产订单', icon: Checklist, to: { name: 'production-tasks' }, permission: 'production_tasks.view_productiontask' },
      { key: 'boms', label: 'BOM 管理', icon: ConnectionPoint, to: { name: 'boms' }, permission: 'boms.view_bom' },
    ],
  },
  {
    key: 'procurement-management',
    label: '采购',
    icon: ShoppingCart,
    children: [
      { key: 'purchase-orders', label: '采购订单', icon: ShoppingCart, to: { name: 'purchase-orders' }, anyPermissions: ['procurement.view_purchaseorder', 'procurement.view_supplier'] },
      { key: 'purchase-inbounds', label: '采购入库', icon: Truck, to: { name: 'purchase-inbounds' }, anyPermissions: ['inventory.receive_material', 'inventory.quality_confirm_material'] },
      { key: 'purchase-returns', label: '退货明细', icon: Export, iconImage: purchaseReturnsIcon, to: { name: 'purchase-returns' }, permission: 'procurement.view_purchaseorder' },
    ],
  },
  {
    key: 'workshop-management',
    label: '车间',
    icon: FactoryBuilding,
    children: [
      { key: 'workshop-configuration', label: '生产配置', icon: Setting, to: { name: 'workshop-configuration' }, permission: 'workshop_config.view_workshop' },
      { key: 'workshop-scheduling', label: '计划排产', icon: Checklist, iconImage: calendarIcon, to: { name: 'workshop-scheduling' }, permission: 'production_scheduling.view_productionschedule' },
      { key: 'workshop-internal-plan', label: '内部计划', icon: TransactionOrder, iconImage: documentIcon, to: { name: 'workshop-metalworking-plan' }, permission: 'production_scheduling.view_productionschedule' },
      { key: 'workshop-outsourcing', label: '委外加工', icon: Peoples, to: { name: 'workshop-outsourcing' }, anyPermissions: ['outsourcing.view_outsourcingorder', 'material_issues.view_metalprocessingsource'] },
      { key: 'material-issues', label: '生产领料', icon: PackageCube, to: { name: 'material-issues' }, permission: 'material_issues.view_materialissue' },
      { key: 'wage-schemes', label: '工价方案', icon: TransactionOrder, iconImage: documentIcon, to: { name: 'wage-schemes' }, permission: 'workshop_reporting.view_wagescheme' },
      { key: 'work-report-days', label: '报工记录', icon: ChartHistogramTwo, to: { name: 'work-report-days' }, allPermissions: ['workshop_reporting.view_workreport', 'production_scheduling.view_productionschedule'] },
    ],
  },
  {
    key: 'warehouse-management',
    label: '仓库',
    icon: Home,
    iconImage: warehouseIcon,
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

const isMenuActive = (item: MenuItem) => {
  return item.key === activeMenu.value || item.children?.some((child) => child.key === activeMenu.value) === true
}

const navigation = ref<HTMLElement>()
const flyout = ref<HTMLElement>()
const displayedGroupKey = ref('')
const panelOpen = ref(false)
const displayedGroup = computed(() => visibleMenuItems.value.find(item => item.key === displayedGroupKey.value))
let openTimer: ReturnType<typeof setTimeout> | undefined
let closeTimer: ReturnType<typeof setTimeout> | undefined

function cancelTimers() {
  clearTimeout(openTimer)
  clearTimeout(closeTimer)
}

function cancelClose() {
  clearTimeout(closeTimer)
}

function openGroup(key: string) {
  cancelTimers()
  displayedGroupKey.value = key
  panelOpen.value = true
}

function scheduleOpen(key: string) {
  cancelTimers()
  // 短暂经过主栏时不闪出面板；只为最后停留的模块创建一次定时器。
  openTimer = setTimeout(() => openGroup(key), 100)
}

function closePanel() {
  cancelTimers()
  panelOpen.value = false
}

function scheduleClose() {
  cancelTimers()
  // 给从主栏移入面板的斜向移动留出余量。
  closeTimer = setTimeout(closePanel, 160)
}

async function focusGroup(key: string) {
  openGroup(key)
  await nextTick()
  flyout.value?.querySelector<HTMLAnchorElement>('a')?.focus()
}

function handleEscape(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !panelOpen.value) return
  event.preventDefault()
  if (flyout.value?.contains(document.activeElement)) {
    navigation.value?.querySelector<HTMLButtonElement>(`[data-menu-key="${displayedGroupKey.value}"]`)?.focus()
  }
  closePanel()
}

function handleFocusOut(event: FocusEvent) {
  if (!navigation.value?.contains(event.relatedTarget as Node | null)) closePanel()
}

watch(() => route.fullPath, closePanel)
watch(displayedGroup, group => { if (!group) closePanel() })
onBeforeUnmount(cancelTimers)

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
const settingsActive = computed(() => activeMenu.value === 'settings' && route.name !== 'access-management' && route.name !== 'theme-settings')
</script>
<template>
  <nav ref="navigation" class="app-sidebar" aria-label="ERP 主导航"
    @mouseenter="cancelClose" @mouseleave="scheduleClose"
    @keydown="handleEscape" @focusout="handleFocusOut">
    <div class="app-sidebar__scroll">
      <ul class="app-sidebar__menu">
        <li v-for="item in visibleMenuItems" :key="item.key">
          <button v-if="item.children?.length" type="button" class="app-sidebar__menu-item"
            :class="{ 'is-active': isMenuActive(item), 'is-open': panelOpen && displayedGroupKey === item.key }"
            :data-menu-key="item.key" :aria-expanded="panelOpen && displayedGroupKey === item.key"
            aria-controls="erp-sidebar-flyout" :title="item.label"
            @mouseenter="scheduleOpen(item.key)" @focus="openGroup(item.key)"
            @click="openGroup(item.key)" @keydown.right.prevent="focusGroup(item.key)">
            <span class="app-sidebar__menu-icon" aria-hidden="true">
              <span v-if="item.iconImage" class="app-sidebar__asset-icon" :style='{ maskImage: `url("${item.iconImage}")` }' />
              <component v-else :is="item.icon"
                :class="{ 'app-sidebar__factory-icon': item.icon === FactoryBuilding }"
                :theme="item.key === 'workshop-management' && isMenuActive(item) ? 'filled' : 'outline'"
                size="24" :stroke-width="3.5" fill="currentColor" />
            </span>
            <span class="app-sidebar__menu-label">{{ item.label }}</span>
          </button>
          <RouterLink v-else :to="item.to!" class="app-sidebar__menu-item"
            :class="{ 'is-active': isMenuActive(item) }" :data-menu-key="item.key"
            :aria-current="isMenuActive(item) ? 'page' : undefined" @mouseenter="scheduleClose" @focus="closePanel">
            <span class="app-sidebar__menu-icon" aria-hidden="true">
              <span v-if="item.iconImage" class="app-sidebar__asset-icon" :style='{ maskImage: `url("${item.iconImage}")` }' />
              <component v-else :is="item.icon" theme="outline" size="24" :stroke-width="3.5" fill="currentColor" />
            </span>
            <span class="app-sidebar__menu-label">{{ item.label }}</span>
          </RouterLink>
        </li>
      </ul>
    </div>

    <div class="app-sidebar__footer" @mouseenter="scheduleClose">
      <RouterLink v-if="authStore.user?.username === 'admin' && authStore.user?.is_superuser"
        :to="{ name: 'access-management' }" class="app-sidebar__footer-link"
        :class="{ 'is-active': route.name === 'access-management' }"
        :aria-current="route.name === 'access-management' ? 'page' : undefined"
        data-menu-key="access-management" title="权限管理" @focus="closePanel">
        <Protect theme="outline" size="20" :stroke-width="3.5" fill="currentColor" aria-hidden="true" />
        <span class="app-sidebar__menu-label">权限</span>
      </RouterLink>
      <RouterLink v-if="canViewSystemSettings" :to="{ name: systemEntryRoute }" class="app-sidebar__footer-link"
        :class="{ 'is-active': settingsActive }" :aria-current="settingsActive ? 'page' : undefined"
        data-menu-key="settings" title="系统配置" @focus="closePanel">
        <Setting theme="outline" size="20" :stroke-width="3.5" fill="currentColor" aria-hidden="true" />
        <span class="app-sidebar__menu-label">配置</span>
      </RouterLink>
      <RouterLink v-if="canViewSystemSettings" :to="{ name: 'theme-settings' }" class="app-sidebar__footer-link"
        :class="{ 'is-active': route.name === 'theme-settings' }"
        :aria-current="route.name === 'theme-settings' ? 'page' : undefined"
        data-menu-key="theme-settings" title="界面主题" @focus="closePanel">
        <Platte theme="outline" size="20" :stroke-width="3.5" fill="currentColor" aria-hidden="true" />
        <span class="app-sidebar__menu-label">主题</span>
      </RouterLink>
    </div>

    <Transition v-if="displayedGroup" name="sidebar-flyout" appear>
      <section v-show="panelOpen" id="erp-sidebar-flyout" ref="flyout" class="app-sidebar__flyout"
        data-sidebar-flyout :data-flyout-menu-key="displayedGroup.key"
        :aria-label="`${displayedGroup.label}子菜单`" :aria-hidden="!panelOpen" :inert="!panelOpen"
        @mouseenter="cancelTimers">
        <div class="app-sidebar__flyout-brand">
          <img :src="flyoutBrand" width="90" height="22.5" alt="HiTree" />
        </div>
        <div class="app-sidebar__flyout-heading">
          <span v-if="displayedGroup.iconImage" class="app-sidebar__asset-icon" :style='{ maskImage: `url("${displayedGroup.iconImage}")` }' aria-hidden="true" />
          <component v-else :is="displayedGroup.icon"
            :class="{ 'app-sidebar__factory-icon': displayedGroup.icon === FactoryBuilding }"
            :theme="displayedGroup.key === 'workshop-management' ? 'filled' : 'outline'"
            size="28" :stroke-width="3.5" fill="currentColor" aria-hidden="true" />
          <div>
            <h2>{{ displayedGroup.label }}</h2>
            <p v-if="displayedGroup.key === 'workshop-management'">车间作业</p>
          </div>
        </div>
        <div class="app-sidebar__flyout-menu">
          <component :is="child.to ? RouterLink : 'span'" v-for="child in displayedGroup.children" :key="child.key"
            :to="child.to" class="app-sidebar__flyout-link"
            :class="{ 'is-active': activeMenu === child.key, 'is-disabled': !child.to }"
            :aria-current="activeMenu === child.key ? 'page' : undefined" :aria-disabled="child.to ? undefined : 'true'"
            :title="child.to ? child.label : `${child.label}（暂未开放）`" :data-menu-key="child.key">
            <span class="app-sidebar__flyout-icon" aria-hidden="true">
              <img v-if="child.key === 'purchase-returns'" :src="child.iconImage" width="20" height="20" alt="" />
              <span v-else-if="child.iconImage" class="app-sidebar__asset-icon" :style='{ maskImage: `url("${child.iconImage}")` }' />
              <component v-else :is="child.icon" theme="outline" size="20" :stroke-width="3.5" fill="currentColor" />
            </span>
            <span>{{ child.label }}</span>
          </component>
        </div>
      </section>
    </Transition>
  </nav>
</template>

<style scoped lang="scss">
.app-sidebar {
  --sidebar-ink: #0d121d;
  --sidebar-accent: #c94f25;
  --sidebar-rail-icon: #f1ede6;
  height: 100%;
  display: flex;
  flex-direction: column;
  color: #f4f3f0;
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
}

.app-sidebar__scroll {
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: #66645e transparent;
}

.app-sidebar__menu {
  margin: 0;
  padding: 0;
  list-style: none;
}

.app-sidebar__menu-item,
.app-sidebar__footer-link {
  position: relative;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  width: 100%;
  border: 0;
  color: inherit;
  background: transparent;
  font: inherit;
  text-decoration: none;
  cursor: pointer;
}

.app-sidebar__menu-item {
  height: 64px;
  flex-direction: column;
  justify-content: center;
  gap: 3px;
  padding: 2px 0;
}

.app-sidebar__menu-icon {
  display: flex;
  flex: none;
  width: 40px;
  height: 36px;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: var(--sidebar-rail-icon);
}

.app-sidebar__menu-label { font-size: 13px; line-height: 20px; }

.app-sidebar__asset-icon { display: block; flex: none; width: 24px; height: 24px; background: currentColor; mask: no-repeat center / contain; }
.app-sidebar__factory-icon { transform: scaleX(-1); }

.app-sidebar__menu-item:hover,
.app-sidebar__menu-item.is-open,
.app-sidebar__footer-link:hover { background: #292925; }

.app-sidebar__menu-item.is-active,
.app-sidebar__footer-link.is-active { background: #272724; font-weight: 600; }

.app-sidebar__menu-item.is-active .app-sidebar__menu-icon {
  color: #1e1e1c;
  background: #f9f8f3;
}

.app-sidebar__menu-item.is-active::before,
.app-sidebar__footer-link.is-active::before,
.app-sidebar__flyout-link.is-active::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 4px;
  background: var(--sidebar-accent);
}

.app-sidebar__footer {
  flex: none;
  margin: 8px 8px 0;
  padding: 8px 0 10px;
  border-top: 1px solid #45453e;
}

.app-sidebar__footer-link { height: 36px; justify-content: center; gap: 7px; border-radius: 4px; }
.app-sidebar__footer-link > .i-icon { color: var(--sidebar-rail-icon); }

.app-sidebar__flyout {
  position: fixed;
  z-index: 1;
  top: 0;
  bottom: 0;
  left: 80px;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  width: 200px;
  color: var(--sidebar-ink);
  background: #fcfaf6;
  border-right: 1px solid #e4dfd6;
  box-shadow: 8px 0 20px -12px rgb(31 29 24 / 16%);
  transition: transform 180ms cubic-bezier(.2, .8, .2, 1), opacity 180ms ease;
}

.app-sidebar__flyout-brand {
  flex: none;
  height: 72px;
  display: flex;
  align-items: center;
  padding: 0 20px;
}

.app-sidebar__flyout-brand img { display: block; width: 90px; height: 22.5px; filter: brightness(0); }

.app-sidebar__flyout-heading {
  flex: none;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 20px 18px;
}

.app-sidebar__flyout-heading h2 { margin: 0; color: #0c1520; font-size: 22px; line-height: 30px; font-weight: 700; }
.app-sidebar__flyout-heading > .app-sidebar__factory-icon { color: #22221f; }
.app-sidebar__flyout-heading p { margin: 4px 0 0; color: #8c8983; font-size: 12px; line-height: 18px; }
.app-sidebar__flyout-heading > .app-sidebar__asset-icon { width: 28px; height: 28px; }

.app-sidebar__flyout-menu {
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 0 6px 16px;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: #b6afa3 transparent;
}

.app-sidebar__flyout-link {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  box-sizing: border-box;
  min-height: 44px;
  margin-bottom: 4px;
  padding: 10px 16px;
  overflow: hidden;
  border-radius: 6px;
  color: var(--sidebar-ink);
  text-decoration: none;
  font-size: 15px;
  line-height: 24px;
}

.app-sidebar__flyout-icon { display: flex; flex: none; align-items: center; }
.app-sidebar__flyout-icon .app-sidebar__asset-icon { width: 20px; height: 20px; }
.app-sidebar__flyout-icon img { filter: brightness(0); }
.app-sidebar__flyout-link:hover { background: #f5f1e9; }
.app-sidebar__flyout-link.is-active { color: #040506; background: #f2eee5; font-size: 16px; font-weight: 600; }
.app-sidebar__flyout-link.is-active .app-sidebar__flyout-icon { color: var(--sidebar-accent); }
.app-sidebar__flyout-link.is-disabled { color: #8a8378; cursor: not-allowed; background: transparent; }

.app-sidebar :is(a, button):focus-visible { outline: 2px solid #3898ec; outline-offset: -3px; }
.sidebar-flyout-enter-from,
.sidebar-flyout-leave-to { opacity: 0; transform: translateX(-10px); }
.sidebar-flyout-leave-active { pointer-events: none; }

@media (prefers-reduced-motion: reduce) {
  .app-sidebar__flyout { transition: none; }
}
</style>
