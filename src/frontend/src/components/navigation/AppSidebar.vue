<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import ConfirmedSidebarIcon from './ConfirmedSidebarIcon.vue'
import ConfirmedSecondarySidebarIcon from './ConfirmedSecondarySidebarIcon.vue'
import '@icon-park/vue-next/styles/index.css'
import { useAuthStore } from '@/stores/auth'
import type { WorkbenchMode } from '@/types/workbench'
import { resolveWorkbenchMode } from '@/utils/workbench'

interface MenuItem {
  key: string
  label: string
  to?: { name: string }
  openInNewTab?: boolean
  defaultChildKey?: string
  permission?: string
  anyPermissions?: string[]
  allPermissions?: string[]
  workbenchMode?: WorkbenchMode
  available?: boolean
  children?: MenuItem[]
}

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const activeMenu = computed(() => {
  return typeof route.meta.activeMenu === 'string' ? route.meta.activeMenu : ''
})

const menuItems: MenuItem[] = [
  {
    key: 'workbench', label: '工作台',
    children: [
      { key: 'manager-workbench', label: '主管工作台', to: { name: 'manager-workbench' }, workbenchMode: 'MANAGER' },
      { key: 'sales-workbench', label: '业务员工作台', to: { name: 'sales-workbench' }, workbenchMode: 'SALES' },
    ],
  },
  {
    key: 'customer-management',
    label: '客户',
    defaultChildKey: 'customers',
    children: [
      { key: 'customers', label: '客户列表', to: { name: 'customers' }, permission: 'customers.view_customeraccount' },
      { key: 'complaints', label: '客诉管理', to: { name: 'complaints' }, permission: 'customers.view_customercomplaint' },
      { key: 'inquiries', label: '询盘管理', to: { name: 'inquiries' }, permission: 'inquiries.view_inquiry' },
      { key: 'quotations', label: '报价管理', to: { name: 'quotations' }, permission: 'quotations.view_quotation' },
      { key: 'sales-orders', label: '销售订单', to: { name: 'sales-orders' } },
      { key: 'tasks', label: '任务中心', to: { name: 'tasks' }, permission: 'workflow.view_businesstask' },
      { key: 'analytics', label: '分析中心', permission: 'customers.view_customeraccount' },
    ],
  },
  {
    key: 'sample-management',
    label: '样品',
    defaultChildKey: 'samples',
    children: [
      { key: 'samples', label: '打样申请', to: { name: 'samples' }, permission: 'samples.view_samplerequest' },
      { key: 'sample-library', label: '样品库', to: { name: 'sample-inventory' }, permission: 'samples.view_sampleinventoryline' },
    ],
  },
  {
    key: 'product-management',
    label: '产品',
    defaultChildKey: 'products',
    children: [
      { key: 'products', label: '产品信息', to: { name: 'products' }, permission: 'products.view_productinformation' },
      { key: 'product-catalog', label: '产品管理', to: { name: 'product-catalog' }, permission: 'product_catalog.view_productcatalog' },
      { key: 'raw-materials', label: '原料信息', to: { name: 'raw-materials' }, permission: 'products.view_rawmaterialinformation' },
      { key: 'material-catalog', label: '原料管理', to: { name: 'material-catalog' }, permission: 'material_catalog.view_materialcatalog' },
    ],
  },
  {
    key: 'production-management',
    label: '生产',
    defaultChildKey: 'production-tasks',
    children: [
      { key: 'production-tasks', label: '生产订单', to: { name: 'production-tasks' }, permission: 'production_tasks.view_productiontask' },
      { key: 'boms', label: 'BOM 管理', to: { name: 'boms' }, permission: 'boms.view_bom' },
    ],
  },
  {
    key: 'procurement-management',
    label: '采购',
    defaultChildKey: 'purchase-orders',
    children: [
      { key: 'purchase-orders', label: '采购订单', to: { name: 'purchase-orders' }, anyPermissions: ['procurement.view_purchaseorder', 'procurement.view_supplier'] },
      { key: 'purchase-inbounds', label: '采购入库', to: { name: 'purchase-inbounds' }, anyPermissions: ['inventory.receive_material', 'inventory.quality_confirm_material'] },
      { key: 'purchase-returns', label: '退货明细', to: { name: 'purchase-returns' }, permission: 'procurement.view_purchaseorder' },
    ],
  },
  {
    key: 'workshop-management',
    label: '车间',
    defaultChildKey: 'workshop-scheduling',
    children: [
      { key: 'workshop-scheduling', label: '计划排产', to: { name: 'workshop-scheduling' }, permission: 'production_scheduling.view_productionschedule' },
      { key: 'workshop-internal-plan', label: '内部计划', to: { name: 'workshop-metalworking-plan' }, permission: 'production_scheduling.view_productionschedule' },
      { key: 'workshop-outsourcing', label: '委外加工', to: { name: 'workshop-outsourcing' }, anyPermissions: ['outsourcing.view_outsourcingorder', 'material_issues.view_metalprocessingsource'] },
      { key: 'material-issues', label: '生产领料', to: { name: 'material-issues' }, permission: 'material_issues.view_materialissue' },
      { key: 'wage-schemes', label: '工价方案', to: { name: 'wage-schemes' }, permission: 'workshop_reporting.view_wagescheme' },
      { key: 'work-report-days', label: '报工记录', to: { name: 'work-report-days' }, allPermissions: ['workshop_reporting.view_workreport', 'production_scheduling.view_productionschedule'] },
      { key: 'workshop-configuration', label: '生产配置', to: { name: 'workshop-configuration' }, permission: 'workshop_config.view_workshop' },
    ],
  },
  {
    key: 'warehouse-management',
    label: '仓库',
    defaultChildKey: 'finished-goods-inventory',
    children: [
      { key: 'finished-goods-inventory', label: '成品库存', to: { name: 'finished-goods-inventory' }, permission: 'inventory.view_finishedgoodsreceipt' },
      { key: 'material-inventory', label: '材料库存', to: { name: 'material-inventory' }, permission: 'inventory.view_materialinbound' },
      { key: 'defective-inventory', label: '不良品库存', permission: 'inventory.view_finishedgoodsreceipt' },
      { key: 'inventory-warning', label: '库存预警', permission: 'inventory.view_finishedgoodsreceipt' },
    ],
  },
  {
    key: 'boards',
    label: '看板',
    children: [
      { key: 'production-line-board', label: '产线大屏', to: { name: 'production-line-board' }, openInNewTab: true },
      { key: 'warehouse-board', label: '仓库大屏', to: { name: 'warehouse-board' }, openInNewTab: true },
      { key: 'production-progress-board', label: '生产进度看板', to: { name: 'production-progress-board' }, openInNewTab: true },
      { key: 'production-board', label: '生产大屏', to: { name: 'production-board' }, openInNewTab: true },
    ],
  },
]

const canShowMenuItem = (item: MenuItem) => {
  if (item.workbenchMode) {
    return resolveWorkbenchMode(authStore.user, item.workbenchMode) !== null
  }
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
const hoveredChildKey = ref('')
const hoverPlateTop = ref(0)
const hoverPlateHeight = ref(0)
const hoverPlateStyle = computed(() => ({
  transform: `translateY(${hoverPlateTop.value}px)`,
  height: `${hoverPlateHeight.value}px`,
  opacity: hoveredChildKey.value ? 1 : 0,
}))
let openTimer: ReturnType<typeof setTimeout> | undefined
let closeTimer: ReturnType<typeof setTimeout> | undefined

function clearFlyoutHover() {
  hoveredChildKey.value = ''
}

function hoverFlyoutChild(event: MouseEvent, child: MenuItem) {
  if (!panelOpen.value || !child.to || activeMenu.value === child.key) {
    clearFlyoutHover()
    return
  }
  const row = event.currentTarget as HTMLElement
  // 使用滚动容器内的布局坐标，让共享背景与对应菜单行一起滚动。
  hoverPlateTop.value = row.offsetTop
  hoverPlateHeight.value = row.offsetHeight
  hoveredChildKey.value = child.key
}

function cancelTimers() {
  clearTimeout(openTimer)
  clearTimeout(closeTimer)
}

function cancelClose() {
  clearTimeout(closeTimer)
}

function openGroup(key: string) {
  cancelTimers()
  if (displayedGroupKey.value !== key) clearFlyoutHover()
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
  clearFlyoutHover()
  panelOpen.value = false
}

async function navigateToDefault(item: MenuItem) {
  // item 的子菜单已按当前权限过滤；默认列表不可访问时仍提供其他可用入口。
  const target = item.children?.find(child => child.key === item.defaultChildKey)
  if (!target?.to) {
    openGroup(item.key)
    return
  }
  closePanel()
  await router.push(target.to)
}

function scheduleClose() {
  cancelTimers()
  clearFlyoutHover()
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
watch(displayedGroup, group => {
  clearFlyoutHover()
  if (!group) closePanel()
})
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
            @click="navigateToDefault(item)" @keydown.right.prevent="focusGroup(item.key)">
            <span class="app-sidebar__menu-icon" data-primary-icon-wrapper aria-hidden="true">
              <ConfirmedSidebarIcon :name="item.key" />
            </span>
            <span class="app-sidebar__menu-label">{{ item.label }}</span>
          </button>
          <RouterLink v-else :to="item.to!" class="app-sidebar__menu-item"
            :class="{ 'is-active': isMenuActive(item) }" :data-menu-key="item.key"
            :aria-current="isMenuActive(item) ? 'page' : undefined" @mouseenter="scheduleClose" @focus="closePanel">
            <span class="app-sidebar__menu-icon" data-primary-icon-wrapper aria-hidden="true">
              <ConfirmedSidebarIcon :name="item.key" />
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
        <span class="app-sidebar__footer-icon" data-primary-icon-wrapper aria-hidden="true">
          <ConfirmedSidebarIcon name="access-management" />
        </span>
        <span class="app-sidebar__menu-label">权限</span>
      </RouterLink>
      <RouterLink v-if="canViewSystemSettings" :to="{ name: systemEntryRoute }" class="app-sidebar__footer-link"
        :class="{ 'is-active': settingsActive }" :aria-current="settingsActive ? 'page' : undefined"
        data-menu-key="settings" title="系统配置" @focus="closePanel">
        <span class="app-sidebar__footer-icon" data-primary-icon-wrapper aria-hidden="true">
          <ConfirmedSidebarIcon name="settings" />
        </span>
        <span class="app-sidebar__menu-label">配置</span>
      </RouterLink>
      <RouterLink v-if="canViewSystemSettings" :to="{ name: 'theme-settings' }" class="app-sidebar__footer-link"
        :class="{ 'is-active': route.name === 'theme-settings' }"
        :aria-current="route.name === 'theme-settings' ? 'page' : undefined"
        data-menu-key="theme-settings" title="界面主题" @focus="closePanel">
        <span class="app-sidebar__footer-icon" data-primary-icon-wrapper aria-hidden="true">
          <ConfirmedSidebarIcon name="theme-settings" />
        </span>
        <span class="app-sidebar__menu-label">主题</span>
      </RouterLink>
    </div>

    <Transition v-if="displayedGroup" name="sidebar-flyout" appear>
      <section v-show="panelOpen" id="erp-sidebar-flyout" ref="flyout" class="app-sidebar__flyout"
        data-sidebar-flyout :data-flyout-menu-key="displayedGroup.key"
        :aria-label="`${displayedGroup.label}子菜单`" :aria-hidden="!panelOpen" :inert="!panelOpen"
        @mouseenter="cancelTimers" @mouseleave="clearFlyoutHover">
        <div class="app-sidebar__flyout-heading">
          <span class="app-sidebar__menu-icon" aria-hidden="true"><ConfirmedSidebarIcon :name="displayedGroup.key" /></span>
          <div>
            <h2>{{ displayedGroup.label }}</h2>
            <p v-if="displayedGroup.key === 'workshop-management'">车间作业</p>
          </div>
        </div>
        <div :key="displayedGroup.key" class="app-sidebar__flyout-menu" :class="{ 'is-open': panelOpen }"
          @mouseleave="clearFlyoutHover" @scroll="clearFlyoutHover">
          <span class="app-sidebar__hover-plate" data-sidebar-hover-plate
            :data-hover-menu-key="hoveredChildKey" :style="hoverPlateStyle" aria-hidden="true" />
          <component :is="child.to ? RouterLink : 'span'" v-for="(child, index) in displayedGroup.children" :key="child.key"
            :to="child.to" class="app-sidebar__flyout-link"
            :style="{ '--sidebar-row-index': index }"
            :target="child.openInNewTab ? '_blank' : undefined"
            :rel="child.openInNewTab ? 'noopener noreferrer' : undefined"
            :aria-label="child.openInNewTab ? `${child.label}（在新标签页打开）` : undefined"
            :class="{ 'is-active': activeMenu === child.key, 'is-disabled': !child.to }"
            :aria-current="activeMenu === child.key ? 'page' : undefined" :aria-disabled="child.to ? undefined : 'true'"
            :title="child.to ? child.label : `${child.label}（暂未开放）`" :data-menu-key="child.key"
            @mouseenter="hoverFlyoutChild($event, child)">
            <span class="app-sidebar__flyout-icon" aria-hidden="true">
              <ConfirmedSecondarySidebarIcon :name="child.key" />
            </span>
            <span class="app-sidebar__flyout-label">{{ child.label }}</span>
          </component>
        </div>
      </section>
    </Transition>
  </nav>
</template>

<style scoped lang="scss">
.app-sidebar {
  --sidebar-ink: #363832;
  --sidebar-accent: #c84e28;
  --sidebar-hover: #f2f2ee;
  --sidebar-active: #fbece5;
  --sidebar-icon-ink: #283133;
  --sidebar-icon-accent: #c84e28;
  --sidebar-icon-fill: #e18761;
  --sidebar-icon-muted: #e7e9e4;
  --icon-ink: #283133;
  --icon-accent: #c84e28;
  --icon-muted: #e7e9e4;
  --sidebar-motion-ease: cubic-bezier(.2, .8, .2, 1);
  position: relative;
  box-sizing: border-box;
  height: 100%;
  display: flex;
  flex-direction: column;
  padding-top: 8px;
  border-radius: 10px;
  color: var(--sidebar-ink);
  background: #fafaf7;
  font-family: 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
}

.app-sidebar__scroll {
  flex: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: #c8c8be transparent;
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
  width: calc(100% - 8px);
  height: 64px;
  margin: 0 4px;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
  padding: 7px 0;
  border-radius: 8px;
}

.app-sidebar__menu-icon {
  display: flex;
  flex: none;
  width: 26px;
  height: 26px;
  align-items: center;
  justify-content: center;
  color: currentColor;
}

.app-sidebar__menu-label { font-size: 13px; line-height: 20px; }

.app-sidebar__menu-icon,
.app-sidebar__footer-icon { transition: transform 200ms var(--sidebar-motion-ease); }

.app-sidebar__menu-icon :deep(svg),
.app-sidebar__footer-icon :deep(svg),
.app-sidebar__flyout-icon :deep(svg) { transform-origin: 50% 60%; }

.app-sidebar__menu-item:hover:not(.is-active) .app-sidebar__menu-icon,
.app-sidebar__footer-link:hover:not(.is-active) .app-sidebar__footer-icon {
  transform: translateY(-3px) scale(1.07);
}

.app-sidebar__menu-item:hover:not(.is-active) .app-sidebar__menu-icon :deep(svg),
.app-sidebar__footer-link:hover:not(.is-active) .app-sidebar__footer-icon :deep(svg),
.app-sidebar__flyout-link:not(.is-active):not(.is-disabled):hover .app-sidebar__flyout-icon :deep(svg) {
  animation: sidebar-icon-nod 380ms var(--sidebar-motion-ease) both;
}

.app-sidebar__menu-item:hover,
.app-sidebar__menu-item.is-open,
.app-sidebar__footer-link:hover { background: var(--sidebar-hover); }

.app-sidebar__menu-item.is-active,
.app-sidebar__footer-link.is-active {
  --sidebar-icon-ink: var(--sidebar-accent);
  --sidebar-icon-muted: #f5d6c7;
  color: var(--sidebar-accent);
  background: var(--sidebar-active);
  font-weight: 600;
}

.app-sidebar__menu-item.is-active::before,
.app-sidebar__footer-link.is-active::before,
.app-sidebar__flyout-link.is-active::before {
  content: '';
  position: absolute;
  inset: 6px auto 6px 0;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--sidebar-accent);
}

.app-sidebar__menu-item.is-active::before { left: -4px; }
.app-sidebar__footer-link.is-active::before { top: 10px; bottom: 10px; }

.app-sidebar__footer {
  flex: none;
  margin: 8px 8px 0;
  padding: 8px 0;
  border-top: 1px solid #e4e5dd;
}

.app-sidebar__footer-icon { display: block; flex: none; width: 20px; height: 20px; }

.app-sidebar__footer-link { height: 32px; justify-content: center; gap: 6px; border-radius: 8px; }

.app-sidebar__flyout {
  position: absolute;
  z-index: 1;
  top: 0;
  left: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  width: 200px;
  height: 100%;
  color: var(--sidebar-ink);
  background: #fafaf7;
  border: 1px solid #e4e5dd;
  border-radius: 8px;
  box-shadow: 8px 0 20px -12px rgb(31 29 24 / 16%);
  transition: transform 180ms cubic-bezier(.2, .8, .2, 1), opacity 180ms ease;
}

.app-sidebar__flyout-heading {
  flex: none;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 20px 16px 18px;
}

.app-sidebar__flyout-heading h2 { margin: 0; color: var(--sidebar-ink); font-size: 20px; line-height: 26px; font-weight: 700; }
.app-sidebar__flyout-heading p { margin: 4px 0 0; color: #8c8983; font-size: 12px; line-height: 18px; }

.app-sidebar__flyout-menu {
  position: relative;
  isolation: isolate;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 0 6px 16px;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: #b6afa3 transparent;
}

.app-sidebar__hover-plate {
  position: absolute;
  z-index: 0;
  top: 0;
  right: 6px;
  left: 6px;
  border-radius: 8px;
  background: var(--sidebar-hover);
  pointer-events: none;
  transition: transform 180ms var(--sidebar-motion-ease), height 180ms var(--sidebar-motion-ease), opacity 120ms ease;
}

.app-sidebar__flyout-link {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  gap: 14px;
  box-sizing: border-box;
  min-height: 44px;
  margin-bottom: 4px;
  padding: 10px 16px;
  overflow: hidden;
  border-radius: 8px;
  color: var(--sidebar-ink);
  text-decoration: none;
  font-size: 15px;
  line-height: 24px;
}

.app-sidebar__flyout-icon { display: flex; flex: none; width: 22px; height: 22px; align-items: center; }
.app-sidebar__flyout-label { min-width: 0; transition: transform 180ms var(--sidebar-motion-ease); }
.app-sidebar__flyout-link:not(.is-active):not(.is-disabled):hover .app-sidebar__flyout-label { transform: translateX(3px); }
.app-sidebar__flyout-link.is-active {
  --icon-ink: var(--sidebar-accent);
  --icon-muted: #f5d6c7;
  color: var(--sidebar-accent);
  background: linear-gradient(90deg, #fbece580, transparent), #fafaf7;
  font-weight: 600;
}
.app-sidebar__flyout-link.is-active::before { top: 4px; bottom: 4px; }
.app-sidebar__flyout-link.is-disabled { color: #8a8378; cursor: not-allowed; background: transparent; }
.app-sidebar__flyout-link.is-disabled .app-sidebar__flyout-icon { opacity: .48; }

.app-sidebar__flyout-menu.is-open .app-sidebar__flyout-link:not(.is-active) {
  animation: sidebar-row-enter 220ms var(--sidebar-motion-ease) both;
  animation-delay: calc(var(--sidebar-row-index) * 18ms);
}

@keyframes sidebar-icon-nod {
  0%, 100% { transform: rotate(0); }
  35% { transform: rotate(-7deg); }
  65% { transform: rotate(3deg); }
}

@keyframes sidebar-row-enter {
  from { opacity: .4; transform: translateX(-4px); }
  to { opacity: 1; transform: translateX(0); }
}

.app-sidebar :is(a, button):focus-visible { outline: 2px solid #3898ec; outline-offset: -3px; }
.sidebar-flyout-enter-from,
.sidebar-flyout-leave-to { opacity: 0; transform: translateX(-10px); }
.sidebar-flyout-leave-active { pointer-events: none; }

@media (prefers-reduced-motion: reduce) {
  .app-sidebar__flyout,
  .app-sidebar__hover-plate { transition: none; }

  .app-sidebar__menu-icon,
  .app-sidebar__footer-icon,
  .app-sidebar__flyout-label,
  .app-sidebar__flyout-link,
  .app-sidebar__menu-icon :deep(svg),
  .app-sidebar__footer-icon :deep(svg),
  .app-sidebar__flyout-icon :deep(svg) {
    animation: none !important;
    transition: none !important;
    transform: none !important;
  }

  .sidebar-flyout-enter-from,
  .sidebar-flyout-leave-to { transform: none; }
}
</style>
