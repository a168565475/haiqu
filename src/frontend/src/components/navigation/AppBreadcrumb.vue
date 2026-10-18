<script setup lang="ts">
import type { AppBreadcrumbItem } from '@/types/router'

withDefaults(defineProps<{
  items: AppBreadcrumbItem[]
  currentClickable?: boolean
}>(), {
  currentClickable: false,
})

const emit = defineEmits<{
  currentClick: []
}>()
</script>

<template>
  <nav class="app-breadcrumb" aria-label="面包屑" data-breadcrumb>
    <ol>
      <li v-for="(item, index) in items" :key="`${item.label}-${index}`">
        <RouterLink v-if="item.to && index < items.length - 1" :to="item.to">
          {{ item.label }}
        </RouterLink>
        <button
          v-else-if="currentClickable && index === items.length - 1"
          type="button"
          class="app-breadcrumb__current-button"
          aria-current="page"
          aria-label="展开左侧菜单"
          data-sidebar-expand
          @click="emit('currentClick')"
        >
          {{ item.label }}
        </button>
        <span v-else :aria-current="index === items.length - 1 ? 'page' : undefined">
          {{ item.label }}
        </span>
        <span v-if="index < items.length - 1" class="app-breadcrumb__separator" aria-hidden="true">
          /
        </span>
      </li>
    </ol>
  </nav>
</template>

<style lang="scss" scoped>
.app-breadcrumb {
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
  padding: 4px;
  overflow-x: auto;
  overflow-y: hidden;
}

.app-breadcrumb ol {
  display: flex;
  flex-wrap: nowrap;
  width: max-content;
  min-width: 100%;
  align-items: center;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
  color: var(--erp-color-text-regular);
  font-size: 13px;
  line-height: 20px;
  white-space: nowrap;
}

.app-breadcrumb li {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  min-height: 32px;
  gap: 6px;
}

.app-breadcrumb a {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  color: var(--erp-color-text-regular);
  text-decoration: none;
}

.app-breadcrumb a:hover {
  color: var(--erp-color-brand);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.app-breadcrumb a:active {
  color: var(--erp-color-brand-pressed);
}

.app-breadcrumb a:focus-visible,
.app-breadcrumb__current-button:focus-visible {
  border-radius: 2px;
  outline: 2px solid var(--erp-color-focus);
  outline-offset: 2px;
}

.app-breadcrumb [aria-current='page'] {
  color: var(--erp-color-text-primary);
  font-weight: 500;
}

.app-breadcrumb__current-button {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  margin: 0;
  padding: 0;
  border: 0;
  color: inherit;
  background: transparent;
  font: inherit;
  cursor: pointer;
}

.app-breadcrumb__current-button:hover {
  color: var(--erp-color-brand);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.app-breadcrumb__current-button:active {
  color: var(--erp-color-brand-pressed);
}

.app-breadcrumb__separator {
  color: var(--erp-color-text-muted);
}
</style>
