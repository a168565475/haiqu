<script setup lang="ts">
import { computed } from 'vue'
import ConfirmedSidebarIcon from '@/components/navigation/ConfirmedSidebarIcon.vue'

const props = defineProps<{ name: string }>()
const menuIcons: Record<string, string> = {
  '生产维护': 'production-management',
  '业务参数': 'settings',
  '权限管理': 'access-management',
  '界面主题': 'theme-settings',
}
const reusedIcon = computed(() => menuIcons[props.name] || '')
</script>

<template>
  <ConfirmedSidebarIcon v-if="reusedIcon" :name="reusedIcon" class="settings-card-svg" />
  <svg v-else class="settings-card-svg" viewBox="0 0 48 48" fill="none" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <g v-if="name === '邮件账户'">
      <rect class="fill-light" x="4" y="10" width="40" height="30" rx="3" />
      <path class="fill-accent" d="m5 12 19 15 19-15" />
      <path d="m5 38 13-13m25 13L30 25" />
    </g>
    <g v-else-if="name === '询盘处理时限'">
      <path class="accent" d="M19 3h10m-5 1v5m11 3 4-4" />
      <circle class="fill-light" cx="24" cy="27" r="17" />
      <path class="fill-muted no-stroke" d="M24 13a14 14 0 0 1 14 14H24Z" />
      <path d="M24 16v11l-7 5" />
      <circle class="fill-accent no-stroke" cx="24" cy="27" r="2.5" />
    </g>
    <g v-else-if="name === '基础资料中心'">
      <rect class="fill-muted" x="11" y="4" width="32" height="34" rx="2.5" />
      <path class="fill-light" d="M5 12h13l5 6h15v26H5Z" />
      <rect class="fill-accent no-stroke" x="12" y="26" width="7" height="7" rx="1" />
      <path d="M24 27h7m-7 6h7M12 38h19" />
    </g>
    <g v-else-if="name === '编号规则'">
      <path class="fill-light" d="M8 4h23l10 10v30H8Z" />
      <path class="fill-muted" d="M31 4v10h10" />
      <path class="accent" d="m21 19-3 16m11-16-3 16m-11-11h18m-19 7h18" />
      <path d="M15 40h18" />
    </g>
    <g v-else-if="name === '通知规则'">
      <path class="fill-light" d="M10 34V22c0-8 5-13 14-13s14 5 14 13v12l4 4H6Z" />
      <path class="accent" d="M24 4v5m-6 33c2 3 10 3 12 0" />
      <path class="fill-accent no-stroke" d="M24 14c6 0 9 3 9 9v10h-6V22c0-3-1-5-3-8Z" />
      <path class="accent" d="M3 15 6 9m36 0 3 6" />
    </g>
    <g v-else-if="name === '发送记录'">
      <path class="fill-light" d="M8 4h24l8 8v32H8Z" />
      <path class="fill-muted" d="M32 4v8h8" />
      <path d="M15 18h18M15 25h10M15 32h7" />
      <path class="accent" d="m27 35 4 4 10-11" />
    </g>
    <g v-else-if="name === '企业微信管理'">
      <path class="fill-muted" d="M27 17c10 0 17 5 17 13 0 4-2 7-5 9l1 6-7-4c-11 2-20-3-20-11 0-7 5-12 14-13Z" />
      <path class="fill-light" d="M21 4C11 4 4 10 4 18c0 5 3 9 7 11l-1 7 8-5c12 2 22-4 22-13C40 10 32 4 21 4Z" />
      <circle class="fill-accent no-stroke" cx="15" cy="17" r="2.6" />
      <circle class="fill-accent no-stroke" cx="28" cy="17" r="2.6" />
      <path class="accent" d="M18 24c2 2 5 2 7 0" />
    </g>
    <g v-else-if="name === '字典配置'">
      <path class="fill-muted" d="M9 5h30v38H9c-5 0-5-8 0-8h30" />
      <path class="fill-light" d="M9 5h30v30H9c-2 0-4 1-4 3V9c0-2 2-4 4-4Z" />
      <path class="accent" d="m15 26 6-13 6 13m-10-4h8" />
      <path d="M31 13h3m-3 6h3m-3 7h3M12 39h27" />
    </g>
  </svg>
</template>

<style scoped>
.settings-card-svg { display: block; width: 100%; height: 100%; stroke: var(--erp-menu-icon-ink); }
.fill-light { fill: var(--erp-menu-icon-fill); }
.fill-muted { fill: var(--erp-menu-icon-muted); }
.fill-accent { fill: var(--erp-menu-accent); }
.accent { stroke: var(--erp-menu-accent); }
.no-stroke { stroke: none; }
</style>
