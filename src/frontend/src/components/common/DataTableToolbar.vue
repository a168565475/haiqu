<script setup lang="ts">
withDefaults(defineProps<{
  selectedCount?: number
}>(), {
  selectedCount: 0,
})
</script>

<template>
  <div class="data-table-toolbar">
    <div class="data-table-toolbar__selection">
      <span class="data-table-toolbar__count" :class="{ 'is-active': selectedCount > 0 }">
        已选择 {{ selectedCount }} 项
      </span>
      <slot name="selection" />
    </div>
    <div class="data-table-toolbar__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.data-table-toolbar,
.data-table-toolbar__selection,
.data-table-toolbar__actions {
  display: flex;
  align-items: center;
}

.data-table-toolbar {
  height: 36px;
  justify-content: space-between;
  gap: 16px;
}

.data-table-toolbar__selection,
.data-table-toolbar__actions {
  height: 36px;
  gap: 12px;
}

.data-table-toolbar__count {
  width: 76px;
  flex: none;
  color: token.$crm-text-secondary;
  font-size: 12px;
  line-height: 18px;
  white-space: nowrap;
}

.data-table-toolbar__count.is-active {
  color: token.$crm-primary-hover;
  font-weight: 600;
}

.data-table-toolbar :deep(.el-button) {
  height: token.$crm-control-height;
  margin: 0;
  border-radius: token.$crm-radius-2;
  padding: 0 16px;
  font-size: 13px;
  font-weight: 500;
}

.data-table-toolbar.is-compact,
.data-table-toolbar.is-compact .data-table-toolbar__selection,
.data-table-toolbar.is-compact .data-table-toolbar__actions {
  height: 32px;
}

.data-table-toolbar.is-compact :deep(.el-button) {
  height: 32px;
}

/* 样品申请列表含双行字段，沿用原工具栏36px，不套用列表紧凑规则。 */
.data-table-toolbar.is-default,
.data-table-toolbar.is-default .data-table-toolbar__selection,
.data-table-toolbar.is-default .data-table-toolbar__actions {
  height: 36px !important;
}

.data-table-toolbar.is-default :deep(.el-button) {
  height: 36px !important;
  min-height: 36px !important;
}

@media (max-width: 900px) {
  .data-table-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .data-table-toolbar__selection,
  .data-table-toolbar__actions {
    flex-wrap: wrap;
  }
}
</style>
