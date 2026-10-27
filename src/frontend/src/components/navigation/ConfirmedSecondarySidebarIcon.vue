<script setup lang="ts">
defineProps<{ name: string }>()
</script>

<template>
  <svg
    class="confirmed-secondary-sidebar-icon sub-icon"
    :data-confirmed-secondary-sidebar-icon="name"
    aria-hidden="true"
    focusable="false"
    viewBox="0 0 24 24"
    width="100%"
    height="100%"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    style="stroke:var(--icon-ink,#283133);fill:none"
  >
    <g v-if="name === 'finance-accounts'">
      <title>公司账户信息</title>
      <path d="m3 8 9-5 9 5H3Z" class="finance-bank-roof"/>
      <path d="M3 21h18M5 10v8m5-8v8m4-8v8m5-8v8"/>
      <path d="M7 21h10" class="accent part" style="stroke:var(--icon-accent,var(--erp-menu-accent))"/>
    </g>
    <g v-else-if="name === 'finance-subjects'">
      <title>会计科目</title>
      <path d="M5 3v15h5M5 7h5m4 0h5m-5 11h5"/>
      <rect x="10" y="4" width="4" height="6" rx="1" style="fill:var(--icon-muted,var(--erp-menu-icon-muted))"/>
      <rect x="10" y="15" width="4" height="6" rx="1" class="accent part" style="stroke:var(--icon-accent,var(--erp-menu-accent));fill:var(--erp-menu-selected-background)"/>
    </g>
    <g v-else-if="name === 'finance-statements'">
      <title>应收对账单</title>
      <path d="M5 3h14v18l-3-2-4 2-4-2-3 2V3Z" class="finance-statement-body" style="fill:var(--icon-muted,var(--erp-menu-icon-muted))"/>
      <path d="M8 7h8m-8 4h8" class="finance-statement-lines"/>
      <path d="m8 15 2 2 5-4" class="accent part finance-statement-lines" style="stroke:var(--icon-accent,var(--erp-menu-accent))"/>
    </g>
    <g v-else-if="name === 'finance-receipts'">
      <title>收款确认单</title>
      <rect x="3" y="4" width="18" height="16" rx="2" class="finance-receipt-body" style="fill:var(--icon-muted,var(--erp-menu-icon-muted))"/>
      <path d="M3 9h18m-5 5 2 2-2 2M9 16h9" class="accent part finance-receipt-lines" style="stroke:var(--icon-accent,var(--erp-menu-accent))"/>
      <path d="M6 6.5h3" class="finance-receipt-lines"/>
    </g>
    <g v-else-if="name === 'employee-list'">
      <title>员工管理</title>
      <circle cx="9" cy="7" r="3" style="fill:var(--icon-muted,#e7e9e4)" />
      <path d="M3 20v-3a6 6 0 0 1 12 0v3" />
      <path class="accent part" d="M17 6h4m-4 5h4m-4 5h4" style="stroke:var(--icon-accent,#c84e28)" />
    </g>

    <g v-else-if="name === 'attendance'">
      <title>考勤管理</title>
      <rect x="3" y="5" width="18" height="16" rx="2" style="fill:var(--icon-muted,#e7e9e4)" />
      <path d="M7 3v4m10-4v4M3 10h18" />
      <path class="accent part" d="m8 15 3 3 5-5" style="stroke:var(--icon-accent,#c84e28)" />
    </g>

    <g v-else-if="name === 'manager-workbench'">
      <title>主管工作台</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><circle cx="12" cy="5" r="2.5"/><path d="M7.5 11c0-2.5 2-3.5 4.5-3.5s4.5 1 4.5 3.5Z"/></g>
      <path d="M12 11v4H5v2m7-2h7v2"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28);fill:var(--icon-accent,#c84e28)"><circle cx="5" cy="20" r="2"/><circle cx="19" cy="20" r="2"/></g>
    </g>

    <g v-else-if="name === 'sales-workbench'">
      <title>业务员工作台</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><rect x="3" y="4" width="18" height="17" rx="2"/></g>
      <path d="M9 4V2h6v2"/><circle cx="8.5" cy="10" r="2"/><path d="M5.5 17v-1a3 3 0 0 1 6 0v1"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M15 10h3m-3 4h3m-3 4h2"/></g>
    </g>

    <g v-else-if="name === 'production-workbench'">
      <title>生产负责人工作台</title>
      <path d="M3 21V11l6-4v4l6-4v14Z" style="fill:var(--icon-muted,#e7e9e4)"/>
      <path d="M15 21h6V3h-4v8M6 16h1m4 0h1"/>
      <path class="accent part" d="M18 14v4m-2-2h4" style="stroke:var(--icon-accent,#c84e28)"/>
    </g>

    <g v-else-if="name === 'production-overview'">
      <title>生产总览</title>
      <rect x="3" y="3" width="18" height="15" rx="2" style="fill:var(--icon-muted,#e7e9e4)"/>
      <path d="M8 21h8m-4-3v3"/>
      <path class="accent part" d="M6 14l4-4 4 2 4-6" style="stroke:var(--icon-accent,#c84e28)"/>
    </g>

    <g v-else-if="name === 'workshop-workbench'">
      <title>车间主管工作台</title>
      <rect x="3" y="4" width="18" height="17" rx="2" style="fill:var(--icon-muted,#e7e9e4)"/>
      <path d="M8 2v4m8-4v4M3 9h18m-9 0v12M3 15h9"/>
      <path class="accent part" d="m14 15 2 2 3-4" style="stroke:var(--icon-accent,#c84e28)"/>
    </g>

    <g v-else-if="name === 'customers'">
      <title>客户列表</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><rect x="4" y="3" width="16" height="18" rx="1.5"/></g>
      <path d="M2 7h3m-3 5h3m-3 5h3"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28);fill:var(--icon-selected-fill,none)"><circle cx="12.5" cy="9" r="2.5"/><path d="M8.5 17c0-3 1.5-4 4-4s4 1 4 4Z"/></g>
    </g>

    <g v-else-if="name === 'complaints'">
      <title>客诉管理</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M3 4h18v12h-9l-6 5v-5H3Z"/></g>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M12 7.5v3.5"/><circle cx="12" cy="13.5" r=".45" style="fill:var(--icon-accent,#c84e28);stroke:none"/></g>
    </g>

    <g v-else-if="name === 'inquiries'">
      <title>询盘管理</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M7 11V2h10v9"/></g>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M10.5 5a1.5 1.5 0 1 1 2 1.4c-.5.2-.5.6-.5 1"/><circle cx="12" cy="9" r=".4" style="fill:var(--icon-accent,#c84e28);stroke:none"/></g>
      <path d="m3 10 9 5 9-5v11H3Zm0 0 4-3m14 3-4-3M3 21l6-5m12 5-6-5"/>
    </g>

    <g v-else-if="name === 'quotations'">
      <title>报价管理</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="m3 12 9-9h9v9l-9 9Z"/></g>
      <circle cx="17" cy="7" r="1.3"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="m7 10 4 4 4-4m-4 4v5m-3-5h6m-6 3h6"/></g>
    </g>

    <g v-else-if="name === 'sales-orders'">
      <title>销售订单</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="m2 6 7-4 7 4v10l-7 4-7-4Z"/></g>
      <path d="m2 6 7 4 7-4M9 10v10"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M15 19h7m-3-3 3 3-3 3"/></g>
    </g>

    <g v-else-if="name === 'tasks'">
      <title>任务中心</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><rect x="4" y="4" width="16" height="17" rx="1.5"/></g>
      <path d="M8 4V2h8v2m-3 6h4m-4 6h4"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="m7 10 1.5 1.5L11 8.5M7 16l1.5 1.5 2.5-3"/></g>
    </g>

    <g v-else-if="name === 'analytics'">
      <title>分析中心</title>
      <path d="M3 3v18h18"/>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M6 18v-4h3v4m3 0v-7h3v7m3 0V8h3v10"/></g>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="m5 11 5-4 4 2 6-6m-4 0h4v4"/></g>
    </g>

    <g v-else-if="name === 'samples'">
      <title>打样申请</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><rect x="10" y="3" width="7" height="14" rx="1.2"/></g>
      <rect x="4" y="5" width="7" height="14" rx="1.2" transform="rotate(-19 7.5 12)"/><circle cx="8.7" cy="16" r=".7"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M17 18h6m-3-3v6"/></g>
    </g>

    <g v-else-if="name === 'sample-library'">
      <title>样品库</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M2 7V4h8l2 3h10v14H2Z"/></g>
      <rect x="6" y="11" width="4" height="7" rx=".6" transform="rotate(-12 8 14.5)"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28);fill:var(--icon-accent,#c84e28)"><rect x="14" y="10" width="4" height="8" rx=".6"/></g>
    </g>

    <g v-else-if="name === 'products'">
      <title>产品信息</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="m2 6 8-4 8 4v10l-8 4-8-4Z"/></g>
      <path d="m2 6 8 4 8-4M10 10v10"/>
      <g style="fill:var(--icon-muted,#e7e9e4)"><circle cx="18" cy="18" r="4.5"/></g>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M18 17.5V20"/><circle cx="18" cy="15.5" r=".45" style="fill:var(--icon-accent,#c84e28);stroke:none"/></g>
    </g>

    <g v-else-if="name === 'product-catalog'">
      <title>产品管理</title>
      <path d="M12 7v4H5.5v4M12 11h6.5v4"/>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M2 15h7v6H2Zm13 0h7v6h-7Z"/></g>
      <path d="M5.5 15v2m13-2v2"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28);fill:var(--icon-accent,#c84e28)"><rect x="9" y="2" width="6" height="5" rx=".7"/></g>
    </g>

    <g v-else-if="name === 'raw-materials'">
      <title>原料信息</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M9 4h11v15H9Z"/><path d="M2 6v13c0 2.7 6 2.7 6 0V6"/><ellipse cx="5" cy="6" rx="3" ry="2"/></g>
      <path d="M2 17c0 2.7 6 2.7 6 0"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M12 8h5m-5 4h5m-5 4h5"/></g>
    </g>

    <g v-else-if="name === 'material-catalog'">
      <title>原料管理</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><rect x="4" y="3" width="16" height="18" rx="1.5"/></g>
      <path d="M8 3v18m3-6h6m-6 3h6"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28);fill:var(--icon-accent,#c84e28)"><path d="M11 6h6v5h-6Z"/></g>
    </g>

    <g v-else-if="name === 'production-tasks'">
      <title>生产订单</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M2 21V10h3V3h4v8l5-3v4l5-3v7"/></g>
      <path d="M2 21h9M6 15h1m3 0h1M6 18h1"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="m13 19 3 3 6-7"/></g>
    </g>

    <g v-else-if="name === 'boms'">
      <title>BOM 管理</title>
      <path d="M12 9v4H4v3m8-3v3m0-3h8v3"/>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="m8 4 4-2 4 2v4l-4 2-4-2Z"/><circle cx="4" cy="19" r="2.5"/><circle cx="20" cy="19" r="2.5"/></g>
      <path d="m8 4 4 2 4-2M12 6v4"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28);fill:var(--icon-accent,#c84e28)"><circle cx="12" cy="19" r="2.5"/></g>
    </g>

    <g v-else-if="name === 'purchase-orders'">
      <title>采购订单</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M6 9h16l-2 8H7L5 6H2"/><path d="M11 9V2h8v7"/></g>
      <circle cx="8" cy="21" r="1.3"/><circle cx="18" cy="21" r="1.3"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M13.5 5h3m-3 2h2"/></g>
    </g>

    <g v-else-if="name === 'purchase-inbounds'">
      <title>采购入库</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M3 11v10h18V11l-4-4h-2M3 11l4-4h2"/></g>
      <path d="M3 14h6m6 0h6"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M12 2v13m-3-3 3 3 3-3"/></g>
    </g>

    <g v-else-if="name === 'purchase-returns' || name === 'purchase-return-records'">
      <title>{{ name === 'purchase-return-records' ? '退货记录' : '退货明细' }}</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="m2 13 6-3 6 3v7l-6 3-6-3Z"/></g>
      <path d="m2 13 6 3 6-3M8 16v7"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M21 13V7a3 3 0 0 0-3-3h-7m3-3-3 3 3 3"/></g>
    </g>

    <g v-else-if="name === 'workshop-scheduling'">
      <title>计划排产</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><rect x="3" y="4" width="18" height="17" rx="1.5"/></g>
      <path d="M7 2v4m10-4v4M3 9h18"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M6 12h5m-1 3h8m-5 3h5"/></g>
    </g>

    <g v-else-if="name === 'workshop-internal-plan'">
      <title>内部计划</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M2 21V11h3V4h4v8l5-3v4l4-3v4"/></g>
      <path d="M2 21h9M6 16h2m-2 3h2"/>
      <g style="fill:var(--icon-muted,#e7e9e4)"><circle cx="18" cy="18" r="4.5"/></g>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M18 15.5V18l2 1"/></g>
    </g>

    <g v-else-if="name === 'workshop-outsourcing' || name === 'warehouse-outsourcing'">
      <title>委外加工</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M2 21V11h3V7h3v6l4-3v11Zm14-8h6v8h-6Z"/></g>
      <path d="M6 17h2m11-1v2"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M8 3h11v6m-3-3 3 3 3-3"/></g>
    </g>

    <g v-else-if="name === 'material-issues'">
      <title>生产领料</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M3 13V3h4v10m2 0V5h4v8M2 13h12v8H2Z"/></g>
      <path d="M5 16v2m4-2v2"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M16 16h6m-3-3 3 3-3 3"/></g>
    </g>

    <g v-else-if="name === 'wage-schemes'">
      <title>工价方案</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><rect x="4" y="2" width="16" height="20" rx="1.8"/></g>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><rect x="7" y="5" width="10" height="4" rx=".6"/></g>
      <path d="M7.5 13h.1m4.4 0h.1m4.4 0h.1M7.5 18h.1m4.4 0h.1m4.4 0h.1" stroke-width="2.7"/>
    </g>

    <g v-else-if="name === 'work-report-days'">
      <title>报工记录</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><rect x="3" y="4" width="18" height="17" rx="1.5"/></g>
      <path d="M7 2v4m10-4v4M3 9h18m-15 4h2m-2 4h2"/>
      <g style="fill:var(--icon-muted,#e7e9e4)"><circle cx="16.5" cy="16.5" r="5.5"/></g>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M16.5 13v3.5l2.5 1.5"/></g>
    </g>

    <g v-else-if="name === 'workshop-configuration'">
      <title>生产配置</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M3 13V4h9v7H6m1 0v3h3v-3M2 18h12v3H2Z"/></g>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M8.5 14v2"/></g>
      <path d="M17 3v4m0 4v10m4-18v10m0 4v4"/>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M15.5 7h3v4h-3Zm4 6h3v4h-3Z"/></g>
    </g>

    <g v-else-if="name === 'finished-goods-inventory'">
      <title>成品库存</title>
      <path d="M3 2v20m18-20v20M3 12h18M3 21h18"/>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M6 5h5v7H6Zm8 0h4v7h-4ZM6 15h12v6H6Z"/></g>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M8.5 5v3m7.5-3v3m-4 7v3"/></g>
    </g>

    <g v-else-if="name === 'material-inventory'">
      <title>材料库存</title>
      <path d="M3 2v20m18-20v20M3 11h18M3 21h18"/>
      <g style="fill:var(--icon-muted,#e7e9e4)"><circle cx="7.5" cy="17" r="3"/><circle cx="16.5" cy="17" r="3"/></g>
      <path d="M7 17h1m8 0h1"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M6 5h12M6 8h12"/></g>
    </g>

    <g v-else-if="name === 'defective-inventory'">
      <title>不良品库存</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="m3 7 9-4 9 4v13l-9 3-9-3Z"/></g>
      <path d="m3 7 9 4 9-4"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="m13 11-3 4 3 2-3 4"/></g>
    </g>

    <g v-else-if="name === 'inventory-warning'">
      <title>库存预警</title>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M2 5v12c0 3.5 13 3.5 13 0V5"/><ellipse cx="8.5" cy="5" rx="6.5" ry="3"/></g>
      <path d="M2 10c0 3.5 13 3.5 13 0m-13 5c0 2 4 3 8 2.5"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="m17 10 6 11H11Z" style="fill:var(--icon-muted,#e7e9e4)"/><path d="M17 14.5V17"/><circle cx="17" cy="19" r=".4" style="fill:var(--icon-accent,#c84e28);stroke:none"/></g>
    </g>

    <g v-else-if="name === 'production-line-board'">
      <title>产线大屏</title>
      <rect x="2" y="3" width="20" height="15" rx="1.5"/><path d="M12 18v3m-4 0h8"/>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M5 7h4v5H5Zm10 0h4v5h-4Z"/></g>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M5 14h14"/><circle cx="6" cy="14" r="1"/><circle cx="18" cy="14" r="1"/></g>
    </g>

    <g v-else-if="name === 'warehouse-board'">
      <title>仓库大屏</title>
      <rect x="2" y="3" width="20" height="15" rx="1.5"/><path d="M12 18v3m-4 0h8"/>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M5 14V8l7-3 7 3v6h-4v-4H9v4Z"/></g>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M10 11h4m-4 3h4"/></g>
    </g>

    <g v-else-if="name === 'production-progress-board'">
      <title>生产进度看板</title>
      <rect x="2" y="3" width="20" height="15" rx="1.5"/><path d="M12 18v3m-4 0h8"/>
      <path d="M6 7h12M6 11h12M6 15h12" style="stroke:var(--icon-muted,#e7e9e4)"/>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28)"><path d="M6 7h8m-8 4h4m-4 4h10"/></g>
    </g>

    <g v-else-if="name === 'production-board'">
      <title>生产大屏</title>
      <rect x="2" y="3" width="20" height="15" rx="1.5"/><path d="M12 18v3m-4 0h8"/>
      <g style="fill:var(--icon-muted,#e7e9e4)"><path d="M5 15v-4h3v4m8 0V6h3v9"/></g>
      <g class="accent part" style="stroke:var(--icon-accent,#c84e28);fill:var(--icon-accent,#c84e28)"><path d="M10.5 15V8h3v7Z"/></g>
    </g>
  </svg>
</template>

<style scoped>
.confirmed-secondary-sidebar-icon {
  display: block;
  width: 100%;
  height: 100%;
  flex: none;
}
:global(.app-sidebar__flyout-link.is-active .finance-bank-roof) { fill: var(--erp-menu-accent); }
:global(.app-sidebar__flyout-link.is-active .finance-statement-body) { fill: var(--erp-menu-accent) !important; }
:global(.app-sidebar__flyout-link.is-active .finance-statement-lines) { stroke: var(--erp-menu-icon-selected-muted) !important; }
:global(.app-sidebar__flyout-link.is-active .finance-receipt-body) { fill: var(--erp-menu-accent) !important; }
:global(.app-sidebar__flyout-link.is-active .finance-receipt-lines) { stroke: var(--erp-menu-icon-selected-muted) !important; }
</style>
