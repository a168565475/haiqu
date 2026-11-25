<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Button as VanButton, Empty as VanEmpty, Loading as VanLoading, Search as VanSearch } from 'vant'
import 'vant/es/button/style'
import 'vant/es/empty/style'
import 'vant/es/loading/style'
import 'vant/es/search/style'
import WorkPage from '@/components/WorkPage.vue'
import WageSchemeForm from '@/components/WageSchemeForm.vue'
import { fetchWageScheme, fetchWageSubmissions, fetchWageTargets } from '@/api/wageSchemes'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'
import { displayQuantity } from '@/utils/planDisplay'
import { canEnterWageSchemes } from '@/utils/wageSchemes'
import type { SavedWageScheme, WageSubmission, WageTarget, WageTargetResponse } from '@/types/wageSchemes'

type WageView = 'pending' | 'submitted'
type LinkedWageTarget = Pick<WageTarget, 'schedule_product_id' | 'craft_id'>

const route = useRoute()
const auth = useAuthStore()
const allowed = computed(() => canEnterWageSchemes(auth.hasPermission))
const view = ref<WageView>('pending')
const keyword = ref('')
const searched = ref('')
const targets = ref<WageTarget[]>([])
const submissions = ref<WageSubmission[]>([])
const submissionDetail = ref<{ id: string; scheme?: SavedWageScheme; error?: string }>()
const nextPage = ref<number | null>(null)
const selected = ref<WageTarget | null>(null)
const loading = ref(false)
const failure = ref('')
const notice = ref('')
let request: AbortController | undefined
let detailRequest: AbortController | undefined

const hasRows = computed(() => Boolean(view.value === 'submitted' ? submissions.value.length : targets.value.length))
const emptyMessage = computed(() => view.value === 'submitted'
  ? (searched.value ? '未找到该任务的已提交方案' : '暂无已提交的工价方案')
  : (searched.value ? `未找到可操作的任务 ${searched.value}` : '暂无待填工价的生产任务'))

const taskGroups = computed(() => {
  const groups = new Map<string, WageTarget[]>()
  for (const target of targets.value) {
    const group = groups.get(target.task_number)
    if (group) group.push(target)
    else groups.set(target.task_number, [target])
  }
  return [...groups].map(([taskNumber, cards]) => ({ taskNumber, cards }))
})

async function loadList(taskNumber = '', page = 1, linkedTarget?: LinkedWageTarget) {
  if (!allowed.value) return
  request?.abort()
  const current = new AbortController()
  request = current
  loading.value = true
  failure.value = ''
  if (page === 1) {
    detailRequest?.abort()
    submissionDetail.value = undefined
    notice.value = ''
    searched.value = taskNumber
    targets.value = []
    submissions.value = []
    nextPage.value = null
  }
  try {
    let meta: WageTargetResponse['meta']
    if (view.value === 'submitted') {
      const result = await fetchWageSubmissions(taskNumber, page, current.signal)
      if (current.signal.aborted) return
      submissions.value = [...submissions.value, ...result.data]
      meta = result.meta
    } else {
      const result = await fetchWageTargets(taskNumber, page, current.signal)
      if (current.signal.aborted) return
      targets.value = [...targets.value, ...result.data]
      const target = linkedTarget && result.data.find(item => item.schedule_product_id === linkedTarget.schedule_product_id
        && item.craft_id === linkedTarget.craft_id)
      if (target) openTarget(target)
      meta = result.meta
    }
    nextPage.value = meta && meta.page < meta.total_pages ? meta.page + 1 : null
  } catch (error) {
    if (!current.signal.aborted) failure.value = errorMessage(error, '工价任务查询失败，请重试')
  } finally {
    if (request === current) loading.value = false
  }
}

function search() {
  if (keyword.value.trim()) void loadList(keyword.value.trim())
}

function switchView(next: WageView) {
  if (view.value === next) return
  view.value = next
  void loadList(keyword.value.trim())
}

function cardAction(target: WageTarget) {
  const scheme = target.scheme
  if (!scheme) return '新建工价'
  if (scheme.can_change) return '变更工价'
  if (scheme.can_edit) return scheme.is_change ? '继续变更' : '继续填写'
  return ''
}

function openTarget(target: WageTarget) {
  if (cardAction(target)) selected.value = target
}

function closeForm(refresh: boolean) {
  selected.value = null
  if (refresh) void loadList(searched.value)
}

function submitted(scheme: SavedWageScheme) {
  selected.value = null
  view.value = 'submitted'
  void loadList(searched.value)
  notice.value = scheme.status === 'PENDING_APPROVAL' ? '已提交厂长审批' : scheme.status_display
}

async function toggleSubmission(id: string) {
  detailRequest?.abort()
  if (submissionDetail.value?.id === id) {
    submissionDetail.value = undefined
    return
  }
  const current = new AbortController()
  detailRequest = current
  submissionDetail.value = { id }
  try {
    const { data } = await fetchWageScheme(id, current.signal)
    if (!current.signal.aborted) submissionDetail.value = { id, scheme: data }
  } catch (error) {
    if (!current.signal.aborted) submissionDetail.value = { id, error: errorMessage(error, '工价明细加载失败') }
  }
}

onMounted(() => {
  const { task_number, schedule_product_id, craft_id } = route.query
  keyword.value = typeof task_number === 'string' ? task_number.trim() : ''
  const linkedTarget = keyword.value && typeof schedule_product_id === 'string' && typeof craft_id === 'string'
    ? { schedule_product_id, craft_id } : undefined
  void loadList(keyword.value, 1, linkedTarget)
})
watch(keyword, value => {
  if (!value.trim() && searched.value) void loadList()
})
onBeforeUnmount(() => { request?.abort(); detailRequest?.abort() })
</script>

<template>
  <WageSchemeForm v-if="allowed && selected" :target="selected" @back="closeForm" @submitted="submitted" />
  <WorkPage v-else title="工价方案" home section="wages">
    <VanEmpty v-if="!allowed" description="当前账号没有填写并提交工价方案的权限" />
    <template v-else>
      <nav class="wage-tabs" aria-label="工价方案列表">
        <button type="button" :aria-pressed="view === 'pending'" @click="switchView('pending')">待填写</button>
        <button type="button" :aria-pressed="view === 'submitted'" @click="switchView('submitted')">已提交</button>
      </nav>
      <form class="wage-search" @submit.prevent="search">
        <VanSearch v-model="keyword" aria-label="生产任务单号" placeholder="输入完整的生产任务单号" maxlength="50" @search="search" />
        <VanButton class="wage-search-button" native-type="submit" type="primary" :loading="loading && !!searched" :disabled="!keyword.trim()">搜索</VanButton>
      </form>
      <p v-if="notice" class="wage-notice" role="status">{{ notice }}</p>
      <VanLoading v-if="loading && !hasRows" vertical class="wage-list-state">正在查询工价任务</VanLoading>
      <VanEmpty v-else-if="!hasRows && !failure" :description="emptyMessage" />
      <section v-if="view === 'pending' && targets.length" class="wage-targets" :aria-label="searched ? '查询结果' : '待填工价的生产任务'">
        <div v-for="group in taskGroups" :key="group.taskNumber" class="wage-task">
          <article v-for="target in group.cards" :key="`${target.schedule_product_id}:${target.craft_id}`"
            class="section-card wage-target" :class="{ 'wage-target-editable': cardAction(target) }" @click="openTarget(target)">
            <header class="wage-target-context">
              <h2><small>生产任务单号</small><strong class="wage-task-number">{{ target.task_number }}</strong></h2>
              <p class="muted">排产日期 <time :datetime="target.schedule_date">{{ target.schedule_date }}</time></p>
            </header>
            <h3>{{ target.product_name }}</h3>
            <p v-if="target.product_number || target.product_specification || target.product_color" class="muted">
              {{ [target.product_number, target.product_specification, target.product_color].filter(Boolean).join(' · ') }}
            </p>
            <p>{{ target.workshop_name }} · {{ target.craft_name }}</p>
            <div class="wage-target-action">
              <span v-if="target.scheme" class="wage-status" :data-status="target.scheme.status">
                {{ target.scheme.status === 'PENDING_APPROVAL' ? '待厂长审批' : target.scheme.status_display }}
                <small>{{ target.scheme.number }}</small>
              </span>
              <VanButton v-if="cardAction(target)" type="primary" size="small">
                {{ cardAction(target) }}
              </VanButton>
            </div>
          </article>
        </div>
      </section>
      <section v-if="view === 'submitted' && submissions.length" class="wage-targets" aria-label="我已提交的工价方案">
        <article v-for="record in submissions" :key="record.id" class="section-card wage-target wage-submission">
          <header class="wage-target-context">
            <h2><small>生产任务单号</small><strong class="wage-task-number">{{ record.production_task.task_number }}</strong></h2>
            <span class="wage-status" :data-status="record.status">{{ record.status === 'PENDING_APPROVAL' ? '待厂长审批' : record.status_display }}</span>
          </header>
          <h3>{{ record.product.name }}</h3>
          <p>{{ record.workshop.name }} · {{ record.scope_craft.name }}</p>
          <div class="wage-target-action">
            <span class="wage-status">{{ record.scheme_number }}</span>
            <div class="wage-submission-actions">
              <VanButton type="primary" size="small" plain :aria-expanded="submissionDetail?.id === record.id" @click="toggleSubmission(record.id)">
                {{ submissionDetail?.id === record.id ? '收起' : '查看明细' }}
              </VanButton>
              <VanButton v-if="record.change_target" type="primary" size="small" @click="openTarget(record.change_target)">变更工价</VanButton>
            </div>
          </div>
          <template v-if="submissionDetail?.id === record.id">
            <p v-if="submissionDetail.error" class="error-panel" role="alert">{{ submissionDetail.error }}</p>
            <VanLoading v-else-if="!submissionDetail.scheme" size="20">正在读取工价明细</VanLoading>
            <ul v-else class="wage-submission-lines">
              <li v-for="line in submissionDetail.scheme.lines" :key="line.work_item_id">
                <span>{{ line.display_name === line.operation_name ? line.display_name : `${line.display_name} · ${line.operation_name}` }}</span>
                <strong>{{ line.status === 'VOID' ? '已作废' : `${displayQuantity(line.declared_price)} 元/次` }}</strong>
              </li>
            </ul>
          </template>
        </article>
      </section>
      <VanButton v-if="nextPage && !failure" class="wage-more" block plain type="primary" :loading="loading" @click="loadList(searched, nextPage)">加载更多</VanButton>
      <section v-if="failure" class="error-panel wage-list-error" role="alert">
        <p>{{ failure }}</p>
        <VanButton plain size="small" @click="loadList(searched, nextPage ?? 1)">重试</VanButton>
      </section>
    </template>
  </WorkPage>
</template>

<style scoped>
.wage-tabs { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; padding: 4px; margin-bottom: 12px; border-radius: 10px; background: var(--mobile-surface); }
.wage-tabs button { min-height: 44px; border: 0; border-radius: 7px; background: transparent; color: var(--mobile-muted); font-weight: 600; }
.wage-tabs button[aria-pressed='true'] { color: var(--mobile-primary); background: var(--mobile-primary-soft); }
.wage-search { --wage-search-height: var(--van-button-default-height); display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
.wage-search :deep(.van-search) { flex: 1; min-width: 0; padding: 0; background: transparent; }
.wage-search :deep(.van-search__content) {
  height: var(--wage-search-height); align-items: center;
  background: var(--mobile-surface); border: 1px solid var(--mobile-border); border-radius: 8px;
}
.wage-search-button { height: var(--wage-search-height); flex-shrink: 0; }
.wage-list-state { padding: 28px 0; }
.wage-list-error { margin-top: 12px; }
.wage-more { margin-top: 12px; }
.wage-targets, .wage-task { display: grid; gap: 12px; }
.wage-target { display: grid; gap: 5px; overflow-wrap: anywhere; }
.wage-target-editable { cursor: pointer; }
.wage-target-context { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 4px 12px; }
.wage-target-context h2 { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0 6px; min-width: 0; margin: 0; font-size: 18px; }
.wage-target-context small { color: var(--mobile-muted); font-size: 13px; font-weight: 400; }
.wage-target h3, .wage-target p { margin: 0; }
.wage-target h3 { font-size: 17px; }
.wage-target p { font-size: 14px; }
.wage-target-action { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-top: 6px; }
.wage-target-action :deep(.van-button) { margin-left: auto; min-height: 44px; }
.wage-status { color: var(--mobile-muted); font-size: 14px; }
.wage-status[data-status='PENDING_APPROVAL'] { color: #805100; }
.wage-status small { display: block; margin-top: 3px; }
.wage-notice { color: #176746; font-weight: 600; }
.wage-submission .wage-target-action { flex-wrap: wrap; }
.wage-submission-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin-left: auto; }
.wage-submission-lines { list-style: none; padding: 0; margin: 4px 0 0; font-size: 14px; }
.wage-submission-lines li { display: flex; gap: 8px; justify-content: space-between; padding: 8px 0; border-top: 1px solid var(--mobile-border); }
.wage-submission-lines strong { flex-shrink: 0; }
</style>
