<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import WorkshopDailyTable from './WorkshopDailyTable.vue'

const auth = useAuthStore()
const tabs = [
  { key: 'metal', label: '金工日报', permission: 'material_issues.view_metalprocessingsource' },
  { key: 'sewing', label: '缝纫日报', permission: 'workshop_reporting.view_workreport' },
  { key: 'assembly', label: '装配日报', permission: 'workshop_reporting.view_workreport' },
] as const
type ReportTab = typeof tabs[number]
function canRead(tab: ReportTab) {
  return auth.user?.is_superuser === true || auth.hasPermission(tab.permission)
}
const active = ref<ReportTab['key']>(canRead(tabs[0]) ? 'metal' : 'sewing')
const date = ref(new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date()))
const search = ref('')
const taskNumber = ref('')

watch(search, (value, _, onCleanup) => {
  const timer = window.setTimeout(() => { taskNumber.value = value.trim() }, 220)
  onCleanup(() => window.clearTimeout(timer))
})

function changeDate(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.value) date.value = input.value
  else input.value = date.value
}

function select(tab: ReportTab) {
  active.value = tab.key
  taskNumber.value = search.value.trim()
}

function moveTab(event: KeyboardEvent) {
  const allowed = tabs.filter(canRead)
  const index = allowed.findIndex(tab => tab.key === active.value)
  const offset = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0
  const next = event.key === 'Home' ? allowed[0] : event.key === 'End' ? allowed.at(-1)
    : offset ? allowed[(index + offset + allowed.length) % allowed.length] : undefined
  if (!next) return
  event.preventDefault()
  select(next)
  const list = event.currentTarget as HTMLElement
  list.querySelector<HTMLElement>(`#workshop-daily-tab-${next.key}`)?.focus()
}
</script>

<template>
  <section class="erp-glass-list erp-glass-list--scroll workshop-daily">
    <section class="erp-list-filter workshop-daily__surface">
      <header class="erp-list-heading"><h1>车间日报</h1></header>
      <nav class="workshop-daily__tabs" role="tablist" aria-label="车间日报切换" @keydown="moveTab">
        <button v-for="tab in tabs" :id="`workshop-daily-tab-${tab.key}`" :key="tab.key" type="button" role="tab"
          aria-controls="workshop-daily-content" :aria-selected="active === tab.key" :tabindex="active === tab.key ? 0 : -1"
          :disabled="!canRead(tab)" @click="select(tab)">{{ tab.label }}</button>
      </nav>
      <form class="erp-list-filters workshop-daily__filters" @submit.prevent="taskNumber = search.trim()">
        <label>日报日期 <input class="erp-list-control" type="date" :value="date" @change="changeDate"></label>
        <label>生产任务单号
          <ElInput v-model="search" class="workshop-daily__search" aria-label="生产任务单号" maxlength="50"
            placeholder="输入任务单号" clearable />
        </label>
      </form>
      <div id="workshop-daily-content" role="tabpanel" :aria-labelledby="`workshop-daily-tab-${active}`">
        <WorkshopDailyTable v-if="active === 'metal'" report="metal" :date="date" :task-number="taskNumber" />
        <div v-else-if="active === 'sewing'" class="workshop-daily__sewing">
          <WorkshopDailyTable report="sewing-detail" :date="date" :task-number="taskNumber" />
          <WorkshopDailyTable report="sewing-orders" :date="date" :task-number="taskNumber" />
        </div>
        <WorkshopDailyTable v-else report="assembly" :date="date" :task-number="taskNumber" />
      </div>
    </section>
  </section>
</template>

<style scoped>
.workshop-daily__surface { container-type: inline-size; }
.workshop-daily__tabs { display: flex; align-items: center; gap: 24px; box-shadow: inset 0 -1px var(--erp-table-border); }
.workshop-daily__tabs button { height: 32px; border: 0; border-bottom: 3px solid transparent; padding: 0 4px; background: transparent; font: inherit; font-size: 13px; color: var(--erp-color-text-secondary); cursor: pointer; }
.workshop-daily__tabs button:hover:not(:disabled) { background: var(--erp-table-hover); }
.workshop-daily__tabs button:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
.workshop-daily__tabs button[aria-selected='true'] { color: var(--erp-color-brand); border-bottom-color: currentColor; font-weight: 600; }
.workshop-daily__tabs button:disabled { color: var(--erp-input-disabled-text); cursor: default; }
.workshop-daily__filters.erp-list-filters { gap: 12px 24px; margin: 19px 0; }
.workshop-daily__search { width: 182px; }
.workshop-daily__sewing { display: grid; gap: 24px; }
@container (min-width: 1270px) {
  .workshop-daily__sewing { grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 18px; }
  .workshop-daily__sewing :deep(:is(th, td)) { padding-inline: 9px; }
}
@container (max-width: 540px) {
  .workshop-daily__tabs { gap: 18px; }
  .workshop-daily__search { width: 145px; }
  .workshop-daily__sewing { gap: 18px; }
}
</style>
