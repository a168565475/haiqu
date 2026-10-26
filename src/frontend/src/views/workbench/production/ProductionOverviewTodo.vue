<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { fetchSamples } from '@/api/samples'
import { fetchWageSchemes } from '@/api/workshopReporting'
import { useAuthStore } from '@/stores/auth'
import type { SampleListItem } from '@/types/sample'
import type { WageScheme } from '@/types/workshopReporting'

const props = defineProps<{ view: 'overview' | 'detail' | 'mini'; refreshKey: string }>()
const auth = useAuthStore()
type LoadState = 'loading' | 'ready' | 'forbidden' | 'error'
const sampleState = ref<LoadState>('loading')
const wageState = ref<LoadState>('loading')
const samples = ref<SampleListItem[]>([])
const wages = ref<WageScheme[]>([])
const sampleChecked = ref(0)
const sampleHasMore = ref(false)
const wageTotal = ref<number | null>(null)
let requestSequence = 0
let controller: AbortController | undefined

const canRead = (permission: string) => auth.user?.employee?.status === 'ACTIVE'
  && (auth.user.is_superuser || auth.hasPermission(permission))
const canReadSamples = computed(() => canRead('samples.view_samplerequest') && canRead('samples.review_sample_application'))
const canReadWages = computed(() => canRead('workshop_reporting.view_wagescheme'))
const loading = computed(() => sampleState.value === 'loading' || wageState.value === 'loading')
const sampleCount = computed(() => sampleState.value === 'ready' ? String(samples.value.length) : '—')
const wageCount = computed(() => wageState.value === 'ready' ? String(wageTotal.value) : '—')
const miniSummary = computed(() => {
  const shown = samples.value.length + wages.value.length
  return !loading.value && shown > 0 ? `已列 ${shown} 项` : '待查看'
})
const sampleNote = computed(() => sampleState.value === 'ready'
  ? `已核对前 ${sampleChecked.value} 条，仅列出你可确认的申请${sampleHasMore.value ? '；其余请到列表查看' : ''}。`
  : '')

function failureState(error: unknown): LoadState {
  const status = (error as { response?: { status?: number } })?.response?.status
  return status === 401 || status === 403 ? 'forbidden' : 'error'
}

async function loadSamples(sequence: number, signal: AbortSignal) {
  try {
    const result = await fetchSamples({ page: 1, page_size: 5, status: 'DIRECTOR_REVIEW', ordering: 'created_at' }, signal)
    if (sequence !== requestSequence || signal.aborted) return
    sampleChecked.value = result.data.length
    sampleHasMore.value = result.meta.total > result.data.length
    // 可见范围不等于审核范围，只展示服务端逐条确认可以审核的申请。
    samples.value = result.data.filter(row => row.status === 'DIRECTOR_REVIEW' && row.application_actions?.can_director_review === true)
    sampleState.value = 'ready'
  } catch (error) {
    if (sequence !== requestSequence || signal.aborted) return
    sampleState.value = failureState(error)
  }
}

async function loadWages(sequence: number, signal: AbortSignal) {
  try {
    const result = await fetchWageSchemes({ page: 1, page_size: 5, status: 'PENDING_APPROVAL', ordering: 'created_at' }, signal)
    if (sequence !== requestSequence || signal.aborted) return
    wages.value = result.data.filter(row => row.status === 'PENDING_APPROVAL')
    wageTotal.value = result.meta.total
    wageState.value = 'ready'
  } catch (error) {
    if (sequence !== requestSequence || signal.aborted) return
    wageState.value = failureState(error)
  }
}

function reload() {
  controller?.abort()
  const sequence = ++requestSequence
  samples.value = []
  wages.value = []
  sampleChecked.value = 0
  sampleHasMore.value = false
  wageTotal.value = null
  sampleState.value = canReadSamples.value ? 'loading' : 'forbidden'
  wageState.value = canReadWages.value ? 'loading' : 'forbidden'
  controller = new AbortController()
  if (canReadSamples.value) void loadSamples(sequence, controller.signal)
  if (canReadWages.value) void loadWages(sequence, controller.signal)
}

// 权限版本、员工状态或账号切换后立即清空旧数据，迟到响应不得恢复旧权限内容。
watch(() => [props.refreshKey, JSON.stringify(auth.user)], reload, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { ++requestSequence; controller?.abort() })
</script>

<template>
  <div class="po-todo" :class="`po-todo--${view}`" :aria-busy="loading" data-testid="production-overview-todo">
    <p v-if="view === 'mini'" class="po-todo__mini" data-testid="todo-mini">{{ miniSummary }}</p>
    <template v-else>
      <section class="po-todo__group" aria-label="打样待确认" :data-state="sampleState" data-testid="todo-samples">
        <header class="po-todo__heading"><div><h3>打样待确认</h3><span>本页可确认</span></div><strong>{{ sampleCount }}<small v-if="sampleState === 'ready'"> 项</small></strong></header>
        <p v-if="sampleState === 'loading'" class="po-todo__state" role="status">正在核对待确认申请…</p>
        <p v-else-if="sampleState === 'forbidden'" class="po-todo__state">暂无查看或确认打样申请的权限</p>
        <p v-else-if="sampleState === 'error'" class="po-todo__state" role="alert">打样申请加载失败 <button v-if="view === 'detail'" type="button" @click="reload">重试</button><span v-else>，展开重试</span></p>
        <template v-else>
          <p v-if="!samples.length" class="po-todo__state">{{ sampleChecked || sampleHasMore ? '本页暂无你可确认的申请' : '暂无待确认打样申请' }}</p>
          <ul v-else-if="view === 'detail'" class="po-todo__list">
            <li v-for="row in samples" :key="row.id">
              <RouterLink :to="`/samples/${encodeURIComponent(row.id)}/director-review`"><strong>{{ row.request_number }}</strong><span>{{ row.item_summary.text || row.customer_name }}</span><small>期望完成 {{ row.sample_due_date || row.requested_due_at?.slice(0, 10) || '未填写' }}</small></RouterLink>
              <span class="po-todo__tag">待确认</span>
            </li>
          </ul>
          <p v-if="view === 'detail'" class="po-todo__note">{{ sampleNote }}</p>
        </template>
        <RouterLink v-if="view === 'detail' && canReadSamples && sampleState !== 'forbidden'" class="po-todo__more" to="/samples?status=DIRECTOR_REVIEW">查看待确认申请 →</RouterLink>
      </section>
      <section class="po-todo__group" aria-label="工价待审批" :data-state="wageState" data-testid="todo-wages">
        <header class="po-todo__heading"><div><h3>工价待审批</h3><span>可查看范围</span></div><strong>{{ wageCount }}<small v-if="wageState === 'ready'"> 份</small></strong></header>
        <p v-if="wageState === 'loading'" class="po-todo__state" role="status">正在读取待审批工价…</p>
        <p v-else-if="wageState === 'forbidden'" class="po-todo__state">暂无工价方案查看权限</p>
        <p v-else-if="wageState === 'error'" class="po-todo__state" role="alert">工价方案加载失败 <button v-if="view === 'detail'" type="button" @click="reload">重试</button><span v-else>，展开重试</span></p>
        <template v-else>
          <p v-if="!wages.length" class="po-todo__state">可查看范围内暂无待审批工价</p>
          <ul v-else-if="view === 'detail'" class="po-todo__list">
            <li v-for="row in wages" :key="row.id">
              <RouterLink :to="`/workshop/wage-schemes/${encodeURIComponent(row.id)}`"><strong>{{ row.scheme_number }}</strong><span>{{ row.product.name }} · {{ row.workshop.name }}</span><small>{{ row.production_task.task_number }}</small></RouterLink>
              <span class="po-todo__tag">待审批</span>
            </li>
          </ul>
          <p v-if="view === 'detail'" class="po-todo__note">{{ wages.length ? `展示前 ${wages.length} 份；` : '' }}审批权限以单据核验为准。</p>
        </template>
        <RouterLink v-if="view === 'detail' && canReadWages && wageState !== 'forbidden'" class="po-todo__more" to="/workshop/wage-schemes">查看工价方案 →</RouterLink>
      </section>
    </template>
  </div>
</template>

<style scoped lang="scss">
.po-todo { display: grid; gap: 18px; min-width: 0; padding: 16px 20px 20px; color: var(--erp-color-text-primary); }
.po-todo--mini { padding: 6px 12px 0; }
.po-todo__group { min-width: 0; }
.po-todo--overview { gap: 12px; }
.po-todo--overview .po-todo__group + .po-todo__group { padding-top: 12px; }
.po-todo__group + .po-todo__group { padding-top: 18px; border-top: 1px solid var(--erp-color-border-subtle); }
.po-todo__heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.po-todo__heading h3 { margin: 0 0 4px; font-size: 14px; font-weight: 600; }
.po-todo__heading span, .po-todo__heading small, .po-todo__note, .po-todo__state { color: var(--erp-color-text-muted); font-size: 12px; line-height: 1.65; }
.po-todo__heading > strong { color: var(--erp-color-brand); font-size: 26px; font-variant-numeric: tabular-nums; white-space: nowrap; }
.po-todo__heading small { font-weight: 400; }
.po-todo__state, .po-todo__note { margin: 8px 0 0; }
.po-todo__state[role='alert'] { color: var(--erp-color-danger); }
.po-todo__state button, .po-todo__more { padding: 0; border: 0; background: transparent; color: var(--erp-color-brand); font: inherit; text-decoration: none; cursor: pointer; }
.po-todo__state button { margin-left: 8px; }
.po-todo__more { display: inline-block; margin-top: 10px; font-size: 12px; }
.po-todo a:focus-visible, .po-todo button:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 3px; }
.po-todo__list { list-style: none; margin: 12px 0 0; padding: 0; }
.po-todo__list li { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 10px 0; }
.po-todo__list li + li { border-top: 1px solid var(--erp-color-border-subtle); }
.po-todo__list a { display: grid; gap: 4px; min-width: 0; color: inherit; text-decoration: none; }
.po-todo__list a:hover strong { color: var(--erp-color-brand); }
.po-todo__list strong { font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
.po-todo__list span { font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.po-todo__list small { color: var(--erp-color-text-muted); font-size: 11px; }
.po-todo__tag { flex-shrink: 0; padding: 2px 7px; border-radius: 5px; background: var(--erp-tag-warning-background); color: var(--erp-tag-warning-text); }
.po-todo__mini { margin: 0; color: var(--erp-color-text-secondary); font-size: 13px; }
</style>
