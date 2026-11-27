<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRight, Flag, Tickets } from '@element-plus/icons-vue'
import { getPurchaseWorkbench } from '@/api/purchaseWorkbench'
import { useAuthStore } from '@/stores/auth'
import { workbenchErrorMessage } from '@/utils/workbench'
import type { PurchaseFollowKey, PurchaseTodoKey, PurchaseWorkbenchCategory, PurchaseWorkbenchSummary } from '@/types/purchaseWorkbench'
import unstarted from '@/assets/purchase-workbench/unstarted.png'
import shortage from '@/assets/purchase-workbench/shortage.png'
import nearDue from '@/assets/purchase-workbench/near-due.png'
import dueToday from '@/assets/purchase-workbench/due-today.png'
import overdue from '@/assets/purchase-workbench/overdue.png'
import PurchaseWorkbenchItems from './PurchaseWorkbenchItems.vue'
import PurchaseWorkbenchMessages from './PurchaseWorkbenchMessages.vue'
import PurchaseWorkbenchSpend from './PurchaseWorkbenchSpend.vue'

const todos: { key: PurchaseTodoKey; title: string; unit: string; icon: string; tone: string }[] = [
  { key: 'unstarted', title: 'BOM 已确认未下单', unit: '张任务', icon: unstarted, tone: '#225f8e' },
  { key: 'shortage', title: '待采购物料', unit: '项', icon: shortage, tone: '#166e72' },
  { key: 'near_due', title: '临期未到齐', unit: '项', icon: nearDue, tone: '#497393' },
  { key: 'due_today', title: '今天应到', unit: '项', icon: dueToday, tone: '#9b6319' },
  { key: 'overdue', title: '逾期未到齐', unit: '项', icon: overdue, tone: '#ac4943' },
]
const follow: { key: PurchaseFollowKey; title: string }[] = [
  { key: 'late_for_use', title: '交期晚于用料日' }, { key: 'missing_due', title: '交期待补' }, { key: 'bom_changed', title: 'BOM 变更待核对' },
]
const auth = useAuthStore(), summary = ref<PurchaseWorkbenchSummary | null>(null)
const reload = ref(0), error = ref(''), selected = ref<{ key: PurchaseWorkbenchCategory; title: string } | null>(null)
watch([() => auth.identityGeneration, reload], (_, __, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  summary.value = null
  selected.value = null
  error.value = ''
  getPurchaseWorkbench(request.signal).then(data => {
    if (!request.signal.aborted) summary.value = data
  }).catch(cause => {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载采购工作台')
  })
}, { immediate: true })
const dateText = computed(() => summary.value && new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric', month: 'long', day: 'numeric', weekday: 'long', timeZone: 'Asia/Shanghai',
}).format(new Date(summary.value.as_of)))
</script>

<template>
  <main class="purchase-workbench">
    <header class="page-heading"><h1>采购工作台</h1><time v-if="summary" :datetime="summary.as_of">{{ dateText }}</time></header>
    <div v-if="error" class="glass load-state" role="alert">{{ error }} <ElButton @click="reload++">重新加载</ElButton></div>
    <p v-else-if="!summary" class="glass load-state" role="status">正在加载采购工作台…</p>
    <template v-else>
      <section class="glass todo-panel"><h2><Tickets />我的待办</h2>
        <div class="todos"><button v-for="t in todos" :key="t.key" type="button" class="todo" :disabled="summary.counts[t.key] === null" :title="summary.availability_reasons[t.key]" @click="selected = t">
          <img :src="t.icon" alt=""><span class="todo-body"><span>{{ t.title }}</span><b :style="{color:t.tone}">{{ summary.counts[t.key] ?? '—' }}</b><small>{{ t.unit }}</small></span><ArrowRight class="chevron" />
        </button></div>
        <small v-if="summary.availability_reasons.shortage" class="reason">{{ summary.availability_reasons.shortage }}</small>
      </section>
      <PurchaseWorkbenchSpend :as-of="summary.as_of">
        <section class="glass sidepanel"><h2><Flag />其他跟进</h2>
          <button v-for="f in follow" :key="f.key" type="button" class="follow-row" :disabled="summary.counts[f.key] === null" :title="summary.availability_reasons[f.key] || (f.key === 'late_for_use' ? '对照排产材料入库日' : undefined)" @click="selected = f">
            <span>{{ f.title }}</span><b>{{ summary.counts[f.key] ?? '—' }}</b><small>项</small><ArrowRight class="chevron" />
          </button>
          <small v-if="summary.availability_reasons.late_for_use || summary.missing_use_date_count" class="reason">{{ summary.availability_reasons.late_for_use || (summary.missing_use_date_count + ' 项缺少排产材料入库日') }}</small>
        </section>
        <PurchaseWorkbenchMessages />
      </PurchaseWorkbenchSpend>
      <PurchaseWorkbenchItems v-if="selected" :key="selected.key" :category="selected.key" :title="selected.title" @close="selected = null" />
    </template>
  </main>
</template>

<style scoped>
.purchase-workbench { display:flex; flex-direction:column; gap:17px; height:100%; min-height:0; overflow:auto; color:var(--erp-color-text-primary); font-family:var(--erp-font-body); font-variant-numeric:tabular-nums; }
.purchase-workbench > * { flex:none; }.page-heading { display:flex; align-items:baseline; justify-content:space-between; flex-wrap:wrap; gap:5px; }.page-heading h1 { margin:0; font-size:27px; font-weight:600; line-height:34px; }.page-heading time { color:var(--erp-color-text-secondary); font-size:13px; }
.purchase-workbench :deep(.glass) { min-width:0; background:var(--erp-glass-surface); border:1px solid var(--erp-glass-border); border-radius:14px; box-shadow:var(--erp-glass-shadow); }
.purchase-workbench :deep(h2) { display:flex; align-items:center; gap:9px; margin:0; font-size:18px; font-weight:650; line-height:1.4; }.purchase-workbench :deep(h2 svg) { width:20px; height:20px; flex:none; color:var(--erp-color-text-secondary); }
.purchase-workbench :deep(button:focus-visible) { outline:2px solid var(--erp-color-brand); outline-offset:1px; }
.todo-panel { padding:15px 22px 16px; }.todos { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); align-items:stretch; margin-top:12px; }
.todo,.follow-row { border:0; background:transparent; font:inherit; color:inherit; cursor:pointer; text-align:left; }.todo { display:grid; grid-template-columns:60px minmax(0,1fr) 10px; gap:13px; align-items:center; padding:6px 20px; border-right:1px solid var(--erp-color-border-subtle); }.todo:first-child { padding-left:0; }.todo:last-child { padding-right:0; border-right:none; }.todo img { width:60px; height:60px; object-fit:contain; }.todo-body>span { display:block; font-size:14px; }.todo b { font:600 32px/1.25 "Segoe UI",sans-serif; margin-right:7px; }.todo small,.follow-row small,.reason { font-size:12px; color:var(--erp-color-text-secondary); }.chevron { width:12px; color:var(--erp-color-text-muted); }
.todo:hover:not(:disabled),.follow-row:hover:not(:disabled) { background:var(--erp-glass-inner-background); }.todo:disabled,.follow-row:disabled { cursor:default; }
.purchase-workbench :deep(.sidepanel) { padding:16px 19px; }.purchase-workbench :deep(.sidepanel h2) { font-size:16px; }.follow-row { display:flex; align-items:center; gap:9px; width:100%; padding:10px 0; font-size:13px; }.follow-row:first-of-type { margin-top:6px; }.follow-row+.follow-row { border-top:1px solid var(--erp-color-border-subtle); }.follow-row b { margin-left:auto; font-size:15px; }.reason { display:block; margin-top:5px; }
.load-state { padding:24px; }.load-state button { margin-left:8px; }
@media(min-width:1700px) { .purchase-workbench { gap:20px; }.todo-panel { padding:18px 24px 21px; }.todos { margin-top:15px; } }
@media(max-width:1350px) { .todo { padding-inline:11px; grid-template-columns:43px minmax(0,1fr) 8px; gap:8px; }.todo img { width:43px; height:43px; } }
@media(max-width:930px) { .todo { grid-template-columns:1fr; gap:4px; }.todo img { width:38px; height:38px; }.todo .chevron { display:none; }.todo-body>span { font-size:13px; } }
@media(max-width:680px) { .todos { grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }.todo-panel { padding:12px; }.todo,.todo:first-child { padding:5px 8px; }.todo:nth-child(3) { border-right:0; }.todo img { width:34px; height:34px; }.todo b { font-size:24px; }.page-heading h1 { font-size:23px; } }
</style>
