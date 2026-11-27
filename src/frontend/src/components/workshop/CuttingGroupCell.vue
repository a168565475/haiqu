<script setup lang="ts">
import type { CuttingGroupComponent } from '@/types/workshopReporting'

withDefaults(defineProps<{
  components?: CuttingGroupComponent[]
  label: string
}>(), { components: () => [] })
</script>

<template>
  <ElTooltip v-if="components.length" placement="top-start" effect="light" :show-after="180">
    <template #content>
      <ul class="cutting-group-cell__parts">
        <li v-for="part in components" :key="part.component_identity">
          {{ part.name }} {{ part.quantity_per_group }}{{ part.unit }}
        </li>
      </ul>
      <p class="cutting-group-cell__note">所列裁片全部做齐才算 1 套。</p>
    </template>
    <span class="cutting-group-cell" tabindex="0">
      <span class="cutting-group-cell__name">{{ components[0]?.name || label }}</span>
      <ElTag v-if="components.length > 1" class="cutting-group-cell__count" type="info" size="small" effect="plain">+{{ components.length - 1 }}</ElTag>
    </span>
  </ElTooltip>
  <span v-else>{{ label }}</span>
</template>

<style scoped>
.cutting-group-cell { display: inline-flex; min-width: 0; max-width: 100%; align-items: center; gap: 6px; vertical-align: middle; }
.cutting-group-cell__name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cutting-group-cell__count { flex: none; }
.cutting-group-cell__parts {
  max-width: 75vw;
  max-height: 50vh;
  margin: 0;
  padding: 0;
  overflow: auto;
  list-style: none;
}
.cutting-group-cell__parts li { line-height: 22px; white-space: nowrap; }
.cutting-group-cell__note { margin: 6px 0 0; color: var(--erp-color-text-secondary); }
</style>
