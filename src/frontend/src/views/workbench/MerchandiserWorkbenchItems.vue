<script setup lang="ts">
import { ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { getMerchandiserItems } from '@/api/merchandiserWorkbench'
import type { MerchandiserItems, MerchandiserSelection } from '@/types/merchandiserWorkbench'
import { workbenchErrorMessage } from '@/utils/workbench'

const props = defineProps<{ selection: MerchandiserSelection }>()
const emit = defineEmits<{ close: [] }>()
const page = ref(1), retry = ref(0)
const result = ref<MerchandiserItems | null>(null), error = ref('')
watch([() => props.selection, page, retry], async ([query, number], _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  result.value = null
  error.value = ''
  try {
    const data = await getMerchandiserItems(query, number, request.signal)
    if (!request.signal.aborted) result.value = data
  } catch (cause) {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载跟单明细')
  }
}, { immediate: true })
</script>

<template>
  <AppWindowDialog :model-value="true" :title="selection.title" :width="1120" :min-width="300" :minimizable="false" @update:model-value="open => { if (!open) emit('close') }">
    <p v-if="error" role="alert">{{ error }} <ElButton link type="primary" @click="retry++">重试</ElButton></p>
    <p v-else-if="!result" role="status">正在加载明细…</p>
    <p v-else-if="!result.data.rows.length">当前没有符合条件的记录。</p>
    <div v-else class="table-scroll">
      <table><thead><tr><th>生产任务单号</th><th v-for="c in result.data.columns" :key="c.key">{{ c.label }}</th></tr></thead>
        <tbody><tr v-for="(row, index) in result.data.rows" :key="index">
          <td><RouterLink :to="{ name: 'production-task-detail', params: { taskId: row.task_id } }">{{ row.task_number }}</RouterLink></td>
          <td v-for="c in result.data.columns" :key="c.key">{{ row.cells[c.key] || '—' }}</td>
        </tr></tbody>
      </table>
    </div>
    <footer v-if="result">共 {{ result.meta.total }} {{ selection.unit }}
      <ElPagination v-if="result.meta.total_pages > 1" v-model:current-page="page" :total="result.meta.total" :page-size="result.meta.page_size" layout="prev, pager, next" background />
    </footer>
  </AppWindowDialog>
</template>

<style scoped>
.table-scroll { max-height: 60vh; overflow: auto; }
table { width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }
th, td { padding: 11px 10px; border-bottom: 1px solid var(--erp-color-border-subtle); vertical-align: top; }
th { position: sticky; top: 0; background: var(--erp-table-header-background); white-space: nowrap; color: var(--erp-color-text-secondary); }
td a { color: var(--erp-menu-accent); font-weight: 650; text-decoration: none; white-space: nowrap; }
td a:hover { text-decoration: underline; }
footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 14px; font-size: 13px; color: var(--erp-color-text-secondary); }
</style>
