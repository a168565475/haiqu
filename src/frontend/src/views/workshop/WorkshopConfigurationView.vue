<script setup lang="ts">
import { computed } from 'vue'
import { Operation, SetUp, UserFilled } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import WorkshopConfigManager from '@/components/workshop/WorkshopConfigManager.vue'
import type { EditableResourceKind } from '@/types/workshopConfig'

const route = useRoute()
const router = useRouter()
const validKinds: EditableResourceKind[] = ['employees', 'crafts', 'operations']
const cardDefinitions = [
  {
    kind: 'employees' as const,
    title: '车间员工',
    description: '直接为生产部员工安排车间、岗位与主管。',
    source: '员工来源：行政生产部',
    icon: UserFilled,
    tone: 'green',
  },
  {
    kind: 'crafts' as const,
    title: '工艺信息',
    description: '维护厂内、厂外工艺及其车间归属，作为工序的上游配置。',
    source: '工作簿来源 11 条（厂内 6、厂外 5）',
    icon: SetUp,
    tone: 'orange',
  },
  {
    kind: 'operations' as const,
    title: '工序信息',
    description: '维护唯一编号、品名、工艺和工序名称，类型与车间自动带出。',
    source: '工作簿来源 947 条（正式导入尚有阻断项）',
    icon: Operation,
    tone: 'purple',
  },
]

const activeKind = computed<EditableResourceKind>(() => {
  const value = typeof route.query.panel === 'string' ? route.query.panel : ''
  return validKinds.includes(value as EditableResourceKind) ? value as EditableResourceKind : 'employees'
})
const dialogVisible = computed({
  get: () => typeof route.query.panel === 'string' && validKinds.includes(route.query.panel as EditableResourceKind),
  set: (visible: boolean) => { if (!visible) closeManager() },
})
const activeTitle = computed(() => cardDefinitions.find((item) => item.kind === activeKind.value)?.title || '车间员工')

function openManager(kind: EditableResourceKind): void {
  void router.push({ query: { ...route.query, panel: kind } })
}

function closeManager(): void {
  const query = { ...route.query }
  delete query.panel
  void router.replace({ query })
}
</script>

<template>
  <section class="workshop-page" data-testid="workshop-configuration-page">
    <header class="page-heading">
      <div>
        <h1>生产配置</h1>
        <p class="subtitle">车间固定为金工、车缝、装配和敲布孔；维护员工、工艺与工序资料</p>
      </div>
      <ElTag type="info" effect="plain">配置模块</ElTag>
    </header>

    <ElAlert
      title="车间为系统固定选项，不提供新增、编辑或停用；自动列出行政生产部员工，车间、岗位和主管在此设置。"
      type="info"
      :closable="false"
      show-icon
      class="scope-alert"
    />

    <div class="entry-grid" aria-label="生产车间配置入口">
      <button
        v-for="(card, index) in cardDefinitions"
        :key="card.kind"
        type="button"
        class="entry-card"
        :class="`entry-card--${card.tone}`"
        :data-testid="`workshop-entry-${card.kind}`"
        @click="openManager(card.kind)"
      >
        <span class="entry-card__order">0{{ index + 1 }}</span>
        <span class="entry-card__icon" aria-hidden="true"><component :is="card.icon" /></span>
        <span class="entry-card__title">{{ card.title }}</span>
        <span class="entry-card__description">{{ card.description }}</span>
        <span class="entry-card__source">{{ card.source }}</span>
        <span class="entry-card__action">进入管理 <span aria-hidden="true">→</span></span>
      </button>
    </div>

    <section class="dependency-note">
      <h2>配置顺序说明</h2>
      <p>员工和厂内工艺只能选择固定车间；先维护员工和工艺，再维护工序。工序的类型与车间只从所选工艺计算，不可单独修改。</p>
    </section>

    <AppWindowDialog
      v-model="dialogVisible"
      :title="`${activeTitle}管理`"
      :width="1600"
      :height="920"
      fullscreen
      destroy-on-close
      class="workshop-manager-dialog"
    >
      <template #title>
        <div class="fullscreen-title">
          <span>生产配置</span><i>/</i><strong>{{ activeTitle }}管理</strong>
        </div>
      </template>
      <WorkshopConfigManager :key="activeKind" :kind="activeKind" />
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.workshop-page {
  box-sizing: border-box;
  min-width: 0;
  min-height: 0;
  color: token.$crm-text-primary;
  background: transparent;
  font-family: token.$crm-font-body;
  --el-color-primary: #{token.$crm-primary};
  --el-border-color: #{token.$crm-border-default};
  --el-fill-color-blank: #{token.$crm-color-surface};
  --el-text-color-primary: #{token.$crm-text-primary};
  --el-text-color-regular: #{token.$crm-text-regular};
}

.page-heading { display: flex; min-height: 62px; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 14px; }
.workshop-page > .page-heading h1 { margin: 0; color: var(--erp-color-text-primary); font-family: var(--erp-font-body); font-size: 36px !important; font-weight: 700; line-height: 44px; }
.subtitle { margin: 2px 0 0; color: token.$crm-text-secondary; font-size: 13px; line-height: 18px; }
.page-heading :deep(.el-tag) { height: 24px; margin-top: 4px; padding: 0 8px; border-color: transparent; border-radius: token.$crm-radius-pill; color: var(--erp-color-text-inverse); background: var(--erp-tag-neutral-background); font-size: 12px; line-height: 24px; }

.scope-alert { margin-bottom: 14px; border: 1px solid var(--erp-glass-border); border-radius: token.$crm-radius-2; background: var(--erp-glass-background); }
.scope-alert :deep(.el-alert__title) { color: token.$crm-text-regular; font-size: 12px; }
.scope-alert :deep(.el-alert__icon) { color: token.$crm-warning; }

.entry-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.entry-card { position: relative; min-width: 0; min-height: 248px; padding: 24px; overflow: hidden; border: 1px solid var(--erp-glass-border); border-radius: var(--erp-glass-radius); color: inherit; background: var(--erp-glass-background); font: inherit; text-align: left; cursor: pointer; transition: border-color 120ms ease, background-color 120ms ease; }
.entry-card:hover { border-color: var(--erp-color-border-strong); background: var(--erp-glass-inner-background); }
.entry-card:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 2px; }
.entry-card__order { position: absolute; top: 18px; right: 20px; color: token.$crm-text-disabled; font-size: 20px; font-weight: 600; }
.entry-card__icon { display: grid; width: 44px; height: 44px; margin-bottom: 18px; place-content: center; border-radius: token.$crm-radius-2; }
.entry-card__icon :deep(svg) { width: 22px; height: 22px; }
.entry-card__title { display: block; margin-bottom: 8px; font-size: 18px; font-weight: 600; line-height: 26px; }
.entry-card__description { display: block; min-height: 48px; color: token.$crm-text-regular; font-size: 13px; line-height: 24px; }
.entry-card__source { display: block; margin-top: 14px; padding-top: 12px; border-top: 1px solid token.$crm-border-subtle; color: token.$crm-text-muted; font-size: 11px; line-height: 18px; }
.entry-card__action { display: block; margin-top: 16px; color: token.$crm-primary; font-size: 13px; font-weight: 600; line-height: 20px; }
.entry-card--green .entry-card__icon { color: token.$crm-success; background: token.$crm-success-soft; }
.entry-card--orange .entry-card__icon { color: token.$crm-warning; background: token.$crm-warning-soft; }
.entry-card--purple .entry-card__icon { color: token.$crm-primary; background: token.$crm-primary-light-8; }

.dependency-note { margin-top: 14px; padding: 16px 20px; border: 1px solid var(--erp-glass-border); border-radius: var(--erp-glass-radius); background: var(--erp-glass-background); }
.scope-alert, .entry-card, .dependency-note { box-shadow: var(--erp-glass-shadow); -webkit-backdrop-filter: var(--erp-glass-backdrop); backdrop-filter: var(--erp-glass-backdrop); }
.dependency-note h2 { margin: 0 0 6px; font-size: 15px; line-height: 22px; }
.dependency-note p { margin: 0; color: token.$crm-text-secondary; font-size: 12px; line-height: 20px; }
.fullscreen-title { display: flex; min-width: 0; align-items: center; gap: 8px; }
.fullscreen-title span { color: token.$crm-text-secondary; font-family: token.$crm-font-body; font-size: 13px; font-weight: 400; }
.fullscreen-title i { color: token.$crm-text-muted; font-style: normal; }
.fullscreen-title strong { overflow: hidden; font-size: 16px; text-overflow: ellipsis; white-space: nowrap; }

:global(.workshop-manager-dialog .app-window-dialog__body) { padding: 0; overflow: hidden; }

@supports not (backdrop-filter: blur(1px)) {
  .scope-alert, .entry-card, .dependency-note { background: var(--erp-color-surface); }
}

@media (max-width: 1000px) {
  .entry-grid { grid-template-columns: 1fr; }
  .entry-card { min-height: 220px; }
}
</style>
