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
  <main class="customer-detail-list-shell erp-glass-list" :aria-busy="loading">
    <section class="customer-detail-list-shell__metrics erp-list-surface" aria-label="客户业务统计">
      <article v-for="metric in metrics" :key="metric.key">
        <span>{{ metric.label }}</span>
        <strong :class="metric.tone && `is-${metric.tone}`">{{ metric.value }}</strong>
      </article>
      <slot name="metric-note" />
    </section>

    <section class="customer-detail-list-shell__filter-card erp-list-filter">
    <header class="customer-detail-list-shell__heading erp-list-heading">
      <div>
        <h2>{{ title }}</h2>
        <p>{{ description }}</p>
      </div>
      <ElButton
        v-if="primaryLabel && !primaryInToolbar"
        class="customer-detail-list-shell__primary erp-button-motion"
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
    </section>

    <section class="customer-detail-list-shell__surface erp-list-data">
    <section class="customer-detail-list-shell__toolbar erp-list-toolbar">
      <div class="customer-detail-list-shell__selection">
        <span>已选择 {{ selectedCount }} 条</span>
        <slot name="batch-actions" />
      </div>
      <div class="customer-detail-list-shell__tools">
        <ElButton
          v-if="primaryLabel && primaryInToolbar"
          class="customer-detail-list-shell__toolbar-primary erp-button-motion"
          type="primary"
          :disabled="primaryDisabled"
          :loading="primaryLoading"
          @click="emit('primary')"
        >
          {{ primaryLabel }}
        </ElButton>
        <slot name="saved-views" />
        <ElButton
          class="erp-button-motion"
          :disabled="!saveViewEnabled"
          :title="saveViewEnabled ? '' : saveViewDisabledTitle"
          @click="emit('saveView')"
        >
          保存视图
        </ElButton>
        <slot name="column-settings">
          <ElButton class="erp-button-motion" :icon="Setting" disabled>列设置</ElButton>
        </slot>
        <ElButton class="erp-button-motion" :icon="Refresh" :loading="loading" @click="emit('refresh')">刷新</ElButton>
      </div>
    </section>

      <ElAlert v-if="error" type="error" :title="error" show-icon :closable="false">
        <ElButton class="erp-button-motion" size="small" @click="emit('refresh')">重试</ElButton>
      </ElAlert>
      <div v-else v-loading="loading" class="customer-detail-list-shell__table erp-list-table-frame">
        <slot name="table" />
      </div>
      <footer class="customer-detail-list-shell__footer erp-list-footer">
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
.customer-detail-list-shell.erp-glass-list { height: auto; min-width: 0; min-height: 0; padding: 0; gap: 14px; font-size: 13px; line-height: 20px; }
.customer-detail-list-shell__metrics { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; padding: 16px; }
.customer-detail-list-shell__metrics article { min-width: 0; display: flex; flex-direction: column; justify-content: center; gap: 6px; }
.customer-detail-list-shell__metrics span,
.customer-detail-list-shell__heading p,
.customer-detail-list-shell__selection { color: var(--erp-color-text-secondary); font-size: 13px; }
.customer-detail-list-shell__metrics strong { font-size: 20px; line-height: 28px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.customer-detail-list-shell__metrics strong.is-warning { color: var(--erp-color-warning); }
.customer-detail-list-shell__metrics strong.is-danger { color: var(--erp-color-danger); }
.customer-detail-list-shell__metrics strong.is-success { color: var(--erp-color-success); }
.customer-detail-list-shell__heading { justify-content: space-between; flex-wrap: wrap; }
.customer-detail-list-shell__heading h2 { margin: 0; color: var(--erp-color-text-primary); font-family: var(--erp-font-body); font-size: 16px; font-weight: 700; line-height: 24px; }
.customer-detail-list-shell__heading p { margin: 4px 0 0; }
.customer-detail-list-shell__heading > div { min-width: 0; }
.customer-detail-list-shell__primary { flex: none; }
.customer-detail-list-shell__filters { min-width: 0; }
.customer-detail-list-shell__toolbar { justify-content: space-between; }
.customer-detail-list-shell__selection,
.customer-detail-list-shell__tools { display: flex; align-items: center; flex-wrap: wrap; min-width: 0; gap: 8px; }
.customer-detail-list-shell__tools { margin-left: auto; }
.customer-detail-list-shell__surface.erp-list-data,
.customer-detail-list-shell__table.erp-list-table-frame { flex: none; }
.customer-detail-list-shell.erp-glass-list .customer-detail-list-shell__table :deep(.el-table .cell),
.customer-detail-list-shell.erp-glass-list .customer-detail-list-shell__filters :deep(.el-input__inner),
.customer-detail-list-shell.erp-glass-list .customer-detail-list-shell__filters :deep(.el-select__placeholder) { font-size: 13px; line-height: 20px; }
@media (max-width: 900px) {
  .customer-detail-list-shell__metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .customer-detail-list-shell__tools { margin-left: 0; }
}
</style>
