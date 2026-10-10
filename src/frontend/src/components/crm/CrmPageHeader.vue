<script setup lang="ts">
defineProps<{
  title: string
  count?: number | null
  countLabel?: string
}>()
</script>

<template>
  <header class="crm-page-header">
    <div class="crm-page-header__heading">
      <div class="crm-page-header__title-row">
        <h1>{{ title }}</h1>
        <span v-if="count !== null && count !== undefined" class="crm-page-header__count">
          {{ count.toLocaleString() }} {{ countLabel || '项' }}
        </span>
      </div>
      <div v-if="$slots.meta" class="crm-page-header__meta">
        <slot name="meta" />
      </div>
    </div>
    <div class="crm-page-header__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.crm-page-header {
  display: flex;
  height: 46px;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
}

.crm-page-header__heading {
  min-width: 0;
}

.crm-page-header__title-row,
.crm-page-header__actions {
  display: flex;
  align-items: center;
}

.crm-page-header__title-row {
  gap: 26px;
}

h1 {
  margin: 0;
  color: token.$crm-text-primary;
  font-family: token.$crm-font-display;
  font-size: 34px;
  font-weight: 700;
  line-height: 46px;
  letter-spacing: -0.03em;
}

.crm-page-header__count {
  padding-top: 15px;
  color: token.$crm-text-secondary;
  font-size: 13px;
  line-height: 20px;
  white-space: nowrap;
}

.crm-page-header__meta {
  margin-top: token.$crm-space-1;
  color: token.$crm-text-secondary;
  font-size: 12px;
  line-height: 18px;
}

.crm-page-header__actions {
  flex: none;
  align-self: flex-start;
  gap: 12px;
  padding-top: 6px;
}

.crm-page-header__actions :deep(.el-button) {
  height: token.$crm-control-height;
  margin: 0;
  border-radius: token.$crm-radius-2;
  padding: 0 16px;
  font-size: 13px;
  font-weight: 500;
}

@media (max-width: 760px) {
  .crm-page-header {
    align-items: stretch;
    flex-direction: column;
    gap: token.$crm-space-3;
  }

  .crm-page-header__actions {
    flex-wrap: wrap;
  }
}
</style>
