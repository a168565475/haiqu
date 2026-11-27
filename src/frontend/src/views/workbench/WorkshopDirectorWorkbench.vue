<script setup lang="ts">
import { ref, watch } from 'vue'
import { ArrowRight, Flag, InfoFilled, OfficeBuilding } from '@element-plus/icons-vue'
import { getDirectorOverview } from '@/api/workshopDirectorWorkbench'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { DirectorOverview, DirectorSelection, DirectorWorkshop } from '@/types/workshopDirectorWorkbench'
import { workbenchErrorMessage } from '@/utils/workbench'
import PurchaseWorkbenchMessages from './PurchaseWorkbenchMessages.vue'
import WorkshopDirectorActivity from './WorkshopDirectorActivity.vue'
import WorkshopDirectorCalendar from './WorkshopDirectorCalendar.vue'
import WorkshopDirectorJobCard from './WorkshopDirectorJobCard.vue'
import WorkshopDirectorDetails from './WorkshopDirectorDetails.vue'
import { deadlineLabel, workshopName } from './WorkshopDirectorDisplay'

const auth = useAuthStore()
const requested = ref<DirectorWorkshop>()
const overview = ref<DirectorOverview | null>(null)
const error = ref(''), retry = ref(0), showRule = ref(false)
const selection = ref<DirectorSelection | null>(null)
const follow = [
  { category: 'late', title: '排产已超期', color: 'late' },
  { category: 'today', title: '今天到期', color: 'today' },
  { category: 'planned', title: '已排产 · 待确认开工', color: 'planned' },
] as const
const formatDate = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long', timeZone: 'Asia/Shanghai' })
watch(() => auth.identityGeneration, () => { requested.value = undefined })
watch([() => auth.identityGeneration, requested, retry], async ([, workshop], _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  overview.value = null
  selection.value = null
  showRule.value = false
  error.value = ''
  try {
    const data = await getDirectorOverview(workshop, request.signal)
    if (!request.signal.aborted) overview.value = data
  } catch (cause) {
    if (!request.signal.aborted) error.value = workbenchErrorMessage(cause, '加载车间工作台')
  }
}, { immediate: true })
</script>

<template>
  <main class="workshop-director-workbench">
    <header class="director-mast">
      <div class="mast-title"><h1>车间主管工作台</h1>
        <template v-if="overview">
          <select v-if="overview.workshops.length > 1" aria-label="选择车间" :value="overview.workshop" @change="requested = ($event.target as HTMLSelectElement).value as DirectorWorkshop">
            <option v-for="workshop in overview.workshops" :key="workshop" :value="workshop">{{ workshopName[workshop] }}车间</option>
          </select>
          <span v-else class="current-workshop">{{ workshopName[overview.workshop] }}车间</span>
        </template>
      </div>
      <time v-if="overview" :datetime="overview.as_of">{{ formatDate.format(new Date(overview.as_of)) }}</time>
    </header>
    <p v-if="error" role="alert" class="glass state">{{ error }} <button class="action" @click="retry++">重新加载</button></p>
    <p v-else-if="!overview" role="status" class="glass state">正在加载车间排产…</p>
    <template v-else>
      <section aria-label="当前在制" class="jobs-section">
        <header class="lead"><div class="section-heading"><h2><OfficeBuilding />当前在制</h2><span v-if="overview.counts.working !== null" class="count-label">{{ overview.counts.working }} 项产品计划</span></div>
          <div class="lead-actions"><button v-if="overview.counts.working !== null && overview.counts.working > overview.jobs.length" class="action" @click="selection = { kind: 'items', category: 'working', title: '全部在制产品计划' }">查看全部在制 ›</button>
            <button class="sort-note" title="查看在制和期限口径" @click="showRule = true">按排产期限排序 <InfoFilled /></button></div>
        </header>
        <div v-if="overview.jobs.length" class="job-grid"><WorkshopDirectorJobCard v-for="job in overview.jobs" :key="job.id" :job="job" :workshop="overview.workshop" :today="overview.as_of" @click="selection = { kind: 'detail', id: job.id }" /></div>
        <p v-else class="glass empty-jobs">{{ overview.counts.working === null ? '当前账号无法查看本车间的在制进度。' : '当前没有在制的产品计划。' }}</p>
      </section>
      <div :key="overview.workshop" class="director-lower">
        <WorkshopDirectorCalendar :overview="overview" @select="selection = $event" />
        <WorkshopDirectorActivity :workshop="overview.workshop" @select="selection = $event" />
        <aside class="director-rail"><section class="glass sidepanel"><h2><Flag />需要跟进</h2>
          <button v-for="item in follow" :key="item.category" type="button" class="follow-row" :disabled="overview.counts[item.category] === null" @click="selection = { kind: 'items', category: item.category, title: item.title }">
            <span class="dot" :class="item.color" aria-hidden="true" />{{ item.title }}<span class="follow-value"><b>{{ overview.counts[item.category] ?? '—' }}</b> {{ overview.counts[item.category] === null ? '无查看权限' : '项' }}</span><ArrowRight />
          </button>
        </section><PurchaseWorkbenchMessages /></aside>
      </div>
      <WorkshopDirectorDetails v-if="selection" :selection="selection" :workshop="overview.workshop" @close="selection = null" />
      <AppWindowDialog v-if="showRule" v-model="showRule" title="在制和排产期限" :width="560" :min-width="300" :minimizable="false">
        <p>当前在制显示本车间已报工、仍未完成的产品计划。“排产已超期”和“今天到期”都按在制计划统计。已排产但还没有报工的计划列在“待确认开工”。</p>
        <p>完工期限取排产的{{ deadlineLabel[overview.workshop] }}。当天显示“今天到期”，超过期限按自然日计数。</p>
      </AppWindowDialog>
    </template>
  </main>
</template>

<style lang="scss" src="./WorkshopDirectorWorkbench.scss"></style>
