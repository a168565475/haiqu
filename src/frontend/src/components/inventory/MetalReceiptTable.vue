<script setup lang="ts" generic="T extends object">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  columns: { key: string; label: string; width: number; num?: boolean }[]
  rows: T[]
  empty?: string
  rowKey?: string
}>(), { empty: '暂无符合条件的记录', rowKey: 'id' })
const minWidth = computed(() => props.columns.reduce((sum, column) => sum + column.width, 0))
function value(row: T, key: string): unknown { return (row as Record<string, unknown>)[key] }
function key(row: T, index: number): string | number { return String(value(row, props.rowKey) ?? index) }
</script>

<template>
  <div class="metal-receipt-table-wrap">
    <table class="metal-receipt-table" :style="{ minWidth: `${minWidth}px` }">
      <colgroup><col v-for="column in columns" :key="column.key" :style="{ width: `${column.width}px` }" /></colgroup>
      <thead><tr><th v-for="column in columns" :key="column.key" :class="{ num: column.num }" :title="column.label">{{ column.label }}</th></tr></thead>
      <tbody>
        <tr v-for="(row, index) in rows" :key="key(row, index)">
          <td v-for="column in columns" :key="column.key" :class="{ num: column.num }">
            <slot :name="`cell-${column.key}`" :row="row" :value="value(row, column.key)"><span class="cell-text" :title="String(value(row, column.key) ?? '')">{{ value(row, column.key) ?? '—' }}</span></slot>
          </td>
        </tr>
        <tr v-if="!rows.length"><td :colspan="columns.length" class="empty-cell">{{ empty }}</td></tr>
      </tbody>
    </table>
  </div>
</template>
