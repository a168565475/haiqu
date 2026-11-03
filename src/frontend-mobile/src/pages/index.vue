<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog } from 'vant'
import { isCancel } from 'axios'
import WorkPage from '@/components/WorkPage.vue'
import ProductionPlanList from '@/components/ProductionPlanList.vue'
import { useAuthStore } from '@/stores/auth'
import { fetchMobileContext, fetchMobilePlans } from '@/api/mobilePlans'
import type { MobilePlan } from '@/types/mobilePlan'
import { planQuery } from '@/utils/planDisplay'
import { errorMessage } from '@/utils/errors'

const auth = useAuthStore()
const router = useRouter()
const search = ref('')
const planCategories = [
  { value: 'METAL', label: '金工' },
  { value: 'CUTTING', label: '裁剪' },
  { value: 'SEWING', label: '车缝' },
  { value: 'ASSEMBLY', label: '装配' },
]
const canSwitchCategories = ref(false)
const selectedCategory = ref('')
const viewMode = ref<'list' | 'summary'>('list')
const plans = ref<MobilePlan[]>([])
const page = ref(1)
const total = ref(0)
const loading = ref(false)
const refreshing = ref(false)
const finished = ref(false)
const message = ref('')
let controller: AbortController | undefined
let contextLoaded = false
const subtitle = computed(() => `${auth.user?.display_name || '工作账号'} · 车间工作台`)

async function load(reset = false) {
  if (!reset && (finished.value || controller)) return
  if (reset) {
    controller?.abort()
    page.value = 1
    plans.value = []
    finished.value = false
  }
  const current = new AbortController()
  controller = current
  loading.value = true
  message.value = ''
  try {
    if (reset || !contextLoaded) {
      const context = await fetchMobileContext(current.signal)
      if (controller !== current) return
      const filter = context.workshop_filter
      canSwitchCategories.value = filter.enabled
      selectedCategory.value = filter.enabled ? selectedCategory.value || 'METAL' : ''
      contextLoaded = true
    }
    const response = await fetchMobilePlans({
      page: page.value, page_size: 12, search: search.value.trim() || undefined,
      ...(selectedCategory.value ? { plan_category: selectedCategory.value } : {}),
    }, current.signal)
    if (controller !== current) return
    plans.value.push(...response.data)
    total.value = response.meta.total
    finished.value = response.meta.page >= response.meta.total_pages || response.data.length === 0
    page.value += 1
  } catch (error) {
    if (controller === current && !isCancel(error)) message.value = errorMessage(error, '任务加载失败，请重试')
  } finally {
    if (controller === current) { controller = undefined; loading.value = false; refreshing.value = false }
  }
}
function selectCategory(value: string) { selectedCategory.value = value; void load(true) }
function open(plan: MobilePlan, action?: 'issue' | 'report' | 'finished-receipt' | 'semi-receipt') {
  const query = planQuery(plan)
  if (action === 'finished-receipt') {
    if (plan.plan_category === 'ASSEMBLY' && plan.can_receive_finished) void router.push({ path: '/finished-receipt', query: { schedule_product_id: plan.schedule_product_id } })
  }
  else if (action === 'semi-receipt') {
    if (['METAL', 'SEWING'].includes(plan.plan_category) && plan.can_receive_semi) void router.push({ path: '/semi-receipt', query: { schedule_product_id: plan.schedule_product_id, plan_category: plan.plan_category } })
  }
  else if (action === 'issue') void router.push({ path: '/issue', query })
  else if (action === 'report' && plan.reporting_crafts.length === 1) void router.push({ path: '/report', query: { ...query, craft_id: plan.reporting_crafts[0]!.id } })
  else void router.push({ path: '/plan', query: { ...query, ...(action ? { action } : {}) } })
}
async function logout() {
  try { await showConfirmDialog({ title: '退出当前账号？', message: '再次使用时需要重新登录。', confirmButtonText: '退出账号', cancelButtonText: '继续工作' }) }
  catch { return }
  try { await auth.logout(); await router.replace('/login') }
  catch (error) { message.value = errorMessage(error, '退出未完成，请重试') }
}
onMounted(() => load(true))
onUnmounted(() => controller?.abort())
</script>

<template>
  <WorkPage title="生产任务" :subtitle="subtitle" home>
    <template #header-action><button class="action-link" @click="logout">退出</button></template>
    <section class="task-tools" :class="{ 'has-workshops': canSwitchCategories }" aria-label="查找生产计划">
      <div class="task-search"><van-search v-model="search" aria-label="搜索生产单号或产品" placeholder="搜索生产单号、产品" :clearable="true" @search="load(true)" @clear="load(true)" /><button class="action-link" @click="load(true)">搜索</button></div>
      <van-tabs v-if="canSwitchCategories" :active="selectedCategory" class="workshop-tabs" :ellipsis="false" @change="selectCategory(String($event))">
        <van-tab v-for="category in planCategories" :key="category.value" :name="category.value" :title="category.label" />
      </van-tabs>
    </section>
    <div class="list-heading">
      <h2>生产计划 <span>{{ total }} 项</span></h2>
      <div class="list-actions">
        <van-button class="view-switch" plain type="primary" size="small" :aria-label="viewMode === 'list' ? '切换为摘要式' : '切换为清单式'" :aria-pressed="viewMode === 'summary'" @click="viewMode = viewMode === 'list' ? 'summary' : 'list'">{{ viewMode === 'list' ? '切换摘要' : '切换清单' }}</van-button>
        <button class="action-link refresh-action" :disabled="loading" @click="load(true)"><van-icon name="replay" /> 刷新</button>
      </div>
    </div>
    <div v-if="message" class="error-panel" role="alert"><p>{{ message }}</p><van-button size="small" plain @click="load(plans.length === 0)">重新加载</van-button></div>
    <van-pull-refresh v-model="refreshing" @refresh="load(true)">
      <van-list v-model:loading="loading" :finished="finished" :immediate-check="false" :error="!!message" :finished-text="plans.length ? '已经到底了' : ''" @load="load()">
        <ProductionPlanList :plans="plans" :mode="viewMode" @open="open" @issue="open($event, 'issue')" @report="open($event, 'report')" @receive-finished="open($event, 'finished-receipt')" @receive-semi="open($event, 'semi-receipt')" />
      </van-list>
      <van-empty v-if="!loading && !plans.length && !message" class="task-empty" image-size="72">
        <template #image><div class="empty-symbol"><van-icon name="orders-o" size="36" /></div></template>
        <template #description><h3>{{ search ? '没有找到相关计划' : '暂无可查看的生产计划' }}</h3><p>{{ search ? '试试其他生产单号或产品。' : '有可查看的生产计划时，会显示在这里。' }}</p></template>
        <van-button plain type="primary" icon="replay" @click="load(true)">刷新列表</van-button>
        <p class="empty-help">若已有计划，请联系管理员确认车间授权。</p>
      </van-empty>
    </van-pull-refresh>
  </WorkPage>
</template>

<style scoped>
.task-tools { background: var(--mobile-surface); border-radius: 12px; overflow: hidden; }
.task-search { display: flex; align-items: center; padding: 12px; gap: 4px; }
.has-workshops .task-search { padding-bottom: 4px; }
.task-search :deep(.van-search) { flex: 1; min-width: 0; padding: 0; }
.task-search > button { flex-shrink: 0; }
.task-tools :deep(.van-search__content) { background: var(--mobile-canvas); border-radius: 8px; padding-left: 10px; }
.task-tools :deep(.van-search .van-field) { min-height: 44px; align-items: center; padding-block: 8px; }
.workshop-tabs :deep(.van-tabs__wrap) { height: 50px; }
.workshop-tabs :deep(.van-tab) { font-size: 15px; }
.workshop-tabs :deep(.van-tabs__line) { width: 24px; height: 3px; bottom: 15px; }
.list-heading { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 4px 8px; margin: 16px 0 8px; }
.list-heading h2 { margin: 0; font-size: 16px; font-weight: 600; }
.list-heading h2 span { color: var(--mobile-muted); font-size: 13px; font-weight: 400; margin-left: 6px; }
.list-actions { display: flex; align-items: center; gap: 4px; margin-left: auto; }
.view-switch { padding-inline: 10px; font-size: 13px; }
.refresh-action { display: inline-flex; align-items: center; gap: 5px; color: var(--mobile-muted); }
.task-empty { background: var(--mobile-surface); border-radius: 12px; padding: 40px 20px 28px; }
.empty-symbol { display: grid; place-items: center; width: 72px; height: 72px; background: var(--mobile-primary-soft); color: var(--mobile-primary); border-radius: 20px; }
.task-empty :deep(.van-empty__description) { margin-top: 20px; padding: 0; text-align: center; }
.task-empty h3 { margin: 0; color: var(--mobile-text); font-size: 18px; font-weight: 600; }
.task-empty :deep(.van-empty__description) p { margin: 8px 0 0; font-size: 14px; line-height: 1.7; }
.task-empty :deep(.van-empty__bottom) { display: flex; flex-direction: column; align-items: center; margin-top: 22px; }
.task-empty .van-button { min-width: 148px; }
.empty-help { margin: 22px 0 0; font-size: 12px; color: var(--mobile-muted); text-align: center; line-height: 1.7; }
</style>


