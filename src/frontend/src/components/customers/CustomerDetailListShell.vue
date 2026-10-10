<script setup lang="ts">
import { Refresh, Setting } from '@element-plus/icons-vue'

export interface CustomerDetailMetric {
  key: string
  label: string
  value: string | number
  tone?: 'default' | 'warning' | 'danger' | 'success'
}

withDefaults(defineProps<{
  title: string
  description: string
  metrics: CustomerDetailMetric[]
  primaryLabel?: string
  primaryDisabled?: boolean
  primaryLoading?: boolean
  primaryInToolbar?: boolean
  loading?: boolean
  error?: string
  selectedCount?: number
  total: number
  page: number
  pageSize: number
  saveViewEnabled?: boolean
  saveViewDisabledTitle?: string
}>(), {
  primaryLabel: '',
  primaryDisabled: false,
  primaryLoading: false,
  primaryInToolbar: false,
  loading: false,
  error: '',
  selectedCount: 0,
  saveViewEnabled: true,
  saveViewDisabledTitle: '当前页面暂不支持保存视图',
})

const emit = defineEmits<{
  primary: []
  refresh: []
  saveView: []
  updatePage: [value: number]
  updatePageSize: [value: number]
}>()
</script>

<template>
  <main class="customer-detail-list-shell" :aria-busy="loading">
    <section class="customer-detail-list-shell__metrics" aria-label="客户业务统计">
      <article v-for="metric in metrics" :key="metric.key">
        <span>{{ metric.label }}</span>
        <strong :class="metric.tone && `is-${metric.tone}`">{{ metric.value }}</strong>
      </article>
      <slot name="metric-note" />
    </section>

    <header class="customer-detail-list-shell__heading">
      <div>
        <h2>{{ title }}</h2>
        <p>{{ description }}</p>
      </div>
      <ElButton
        v-if="primaryLabel && !primaryInToolbar"
        class="customer-detail-list-shell__primary"
        type="primary"
        :disabled="primaryDisabled"
        :loading="primaryLoading"
        @click="emit('primary')"
      >
        {{ primaryLabel }}
      </ElButton>
    </header>

    <section class="customer-detail-list-shell__filters">
      <slot name="filters" />
    </section>

    <section class="customer-detail-list-shell__toolbar">
      <div class="customer-detail-list-shell__selection">
        <span>已选择 {{ selectedCount }} 条</span>
        <slot name="batch-actions" />
      </div>
      <div class="customer-detail-list-shell__tools">
        <ElButton
          v-if="primaryLabel && primaryInToolbar"
          class="customer-detail-list-shell__toolbar-primary"
          type="primary"
          :disabled="primaryDisabled"
          :loading="primaryLoading"
          @click="emit('primary')"
        >
          {{ primaryLabel }}
        </ElButton>
        <slot name="saved-views" />
        <ElButton
          :disabled="!saveViewEnabled"
          :title="saveViewEnabled ? '' : saveViewDisabledTitle"
          @click="emit('saveView')"
        >
          保存视图
        </ElButton>
        <slot name="column-settings">
          <ElButton :icon="Setting" disabled>列设置</ElButton>
        </slot>
        <ElButton :icon="Refresh" :loading="loading" @click="emit('refresh')">刷新</ElButton>
      </div>
    </section>

    <section class="customer-detail-list-shell__surface">
      <ElAlert v-if="error" type="error" :title="error" show-icon :closable="false">
        <ElButton size="small" @click="emit('refresh')">重试</ElButton>
      </ElAlert>
      <div v-else v-loading="loading" class="customer-detail-list-shell__table">
        <slot name="table" />
      </div>
      <footer class="customer-detail-list-shell__footer">
        <span>共 {{ total }} 条</span>
        <ElPagination
          background
          layout="sizes, prev, pager, next"
          :total="total"
          :current-page="page"
          :page-size="pageSize"
          :page-sizes="[20, 50, 100]"
          @update:current-page="emit('updatePage', $event)"
          @update:page-size="emit('updatePageSize', $event)"
        />
      </footer>
    </section>
  </main>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.customer-detail-list-shell {
  min-width: 0;
  min-height: calc(100vh - 230px);
  padding: 18px 28px 24px;
  color: token.$crm-text-primary;
  background: token.$crm-color-page;
  font-family: token.$crm-font-body;
}

.customer-detail-list-shell__metrics {
  height: 72px;
  display: flex;
  align-items: stretch;
  overflow: hidden;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-3;
  background: token.$crm-color-surface;
}

.customer-detail-list-shell__metrics article {
  width: 180px;
  min-width: 140px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 5px;
  padding: 0 18px;
  border-right: 1px solid token.$crm-border-subtle;
}

.customer-detail-list-shell__metrics span,
.customer-detail-list-shell__heading p,
.customer-detail-list-shell__selection,
.customer-detail-list-shell__footer > span {
  color: token.$crm-text-secondary;
  font-size: 12px;
}

.customer-detail-list-shell__metrics strong {
  font-size: 20px;
  line-height: 24px;
}

.customer-detail-list-shell__metrics strong.is-warning { color: token.$crm-warning; }
.customer-detail-list-shell__metrics strong.is-danger { color: token.$crm-danger; }
.customer-detail-list-shell__metrics strong.is-success { color: token.$crm-success; }

.customer-detail-list-shell__heading {
  height: 66px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.customer-detail-list-shell__heading h2 {
  margin: 0;
  font-family: token.$crm-font-display;
  font-size: 22px;
  font-weight: 700;
  line-height: 30px;
}

.customer-detail-list-shell__heading p { margin: 2px 0 0; }

.customer-detail-list-shell__primary {
  width: 140px;
  height: 36px;
  margin: 0;
  border-radius: token.$crm-radius-2;
}

.customer-detail-list-shell__filters,
.customer-detail-list-shell__toolbar,
.customer-detail-list-shell__selection,
.customer-detail-list-shell__tools {
  display: flex;
  align-items: center;
}

.customer-detail-list-shell__filters { min-height: 52px; overflow-x: auto; }
.customer-detail-list-shell__filters :deep(> *) { width: 100%; }

.customer-detail-list-shell__toolbar {
  height: 52px;
  justify-content: space-between;
}

.customer-detail-list-shell__selection,
.customer-detail-list-shell__tools { gap: 10px; }

.customer-detail-list-shell__filters :deep(.el-input__wrapper),
.customer-detail-list-shell__filters :deep(.el-select__wrapper),
.customer-detail-list-shell__filters :deep(.el-date-editor),
.customer-detail-list-shell__tools :deep(.el-button),
.customer-detail-list-shell__selection :deep(.el-button) {
  min-height: 36px;
  border-radius: token.$crm-radius-2;
}

.customer-detail-list-shell__tools :deep(.el-button) {
  min-width: 92px;
  margin: 0;
}

.customer-detail-list-shell__tools :deep(.customer-detail-list-shell__toolbar-primary) {
  width: 140px;
  border-color: token.$crm-primary;
  color: token.$crm-text-inverse;
  background: token.$crm-primary;
}

.customer-detail-list-shell__surface {
  min-width: 0;
  overflow: hidden;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
}

.customer-detail-list-shell__table {
  min-width: 0;
  overflow-x: auto;
}

.customer-detail-list-shell__table :deep(.el-table) {
  min-width: 1460px;
  --el-table-border-color: #{token.$crm-border-subtle};
  --el-table-header-bg-color: #{token.$crm-color-subtle};
  --el-table-row-hover-bg-color: #{token.$crm-color-row-hover};
  color: token.$crm-text-primary;
}

.customer-detail-list-shell__table :deep(th.el-table__cell) {
  height: token.$crm-table-header-height;
  padding: 0;
  color: token.$crm-text-primary;
  font-size: 12px;
  font-weight: 600;
}

.customer-detail-list-shell__table :deep(td.el-table__cell) {
  height: token.$crm-table-row-compact;
  padding: 0;
  color: token.$crm-text-secondary;
  font-size: 12px;
}

.customer-detail-list-shell__table :deep(.cell) { padding: 0 12px; }

.customer-detail-list-shell__table :deep(.el-tag) {
  height: 24px;
  justify-content: center;
  border: 0;
  border-radius: token.$crm-radius-pill;
  font-size: 11px;
}

.customer-detail-list-shell__footer {
  height: token.$crm-table-footer-height;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 14px;
  border-top: 1px solid token.$crm-border-subtle;
}

.customer-detail-list-shell__footer :deep(.el-pagination) { margin: 0; }
.customer-detail-list-shell__footer :deep(.btn-prev),
.customer-detail-list-shell__footer :deep(.btn-next),
.customer-detail-list-shell__footer :deep(.el-pager li) {
  min-width: 36px;
  height: 36px;
  border-radius: token.$crm-radius-2;
}

.customer-detail-list-shell__footer :deep(.el-pager li.is-active) {
  color: token.$crm-primary;
  border: 1px solid token.$crm-primary;
  background: token.$crm-color-surface;
}

@media (max-width: 1599px) {
  .customer-detail-list-shell { padding-inline: 24px; }
  .customer-detail-list-shell__metrics article { width: 160px; }
}
</style>
