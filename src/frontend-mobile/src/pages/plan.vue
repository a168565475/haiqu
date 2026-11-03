<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
import { isCancel } from 'axios'
import { useRoute, useRouter } from 'vue-router'
import WorkPage from '@/components/WorkPage.vue'
import ProductImage from '@/components/ProductImage.vue'
import { fetchMobilePlan } from '@/api/mobilePlans'
import type { MobilePlan } from '@/types/mobilePlan'
import { displayQuantity, planQuery, progressLabel } from '@/utils/planDisplay'
import { errorMessage } from '@/utils/errors'

const route = useRoute()
const router = useRouter()
const plan = ref<MobilePlan | null>(null)
const busy = ref(false)
const message = ref('')
let controller: AbortController | undefined
async function load() {
  controller?.abort()
  const current = new AbortController()
  controller = current
  busy.value = false
  message.value = ''
  plan.value = null
  const id = String(route.query.schedule_product_id || '')
  const category = String(route.query.plan_category || '')
  const workshop = String(route.query.workshop_id || '')
  if (!id || !category || !workshop) { message.value = '任务信息不完整，请返回生产列表重新选择'; return }
  busy.value = true
  try {
    const result = await fetchMobilePlan(id, { plan_category: category, workshop_id: workshop }, current.signal)
    if (controller === current) plan.value = result
  }
  catch (error) { if (controller === current && !isCancel(error)) message.value = errorMessage(error, '计划信息加载失败') }
  finally { if (controller === current) busy.value = false }
}
function navigate(path: string, craftId?: string) {
  if (plan.value) void router.push({ path, query: { ...planQuery(plan.value), ...(craftId ? { craft_id: craftId } : {}) } })
}
watch(() => [route.query.schedule_product_id, route.query.plan_category, route.query.workshop_id], load, { immediate: true })
onUnmounted(() => { controller?.abort(); controller = undefined })
</script>

<template>
  <WorkPage :title="route.query.action === 'report' ? '选择报工工艺' : '生产计划详情'" :subtitle="plan?.task_number">
    <van-loading v-if="busy" vertical class="detail-loading">正在读取计划</van-loading>
    <div v-if="message" class="error-panel" role="alert"><p>{{ message }}</p><van-button class="detail-retry" size="small" @click="load">重新加载</van-button></div>
    <div v-if="plan" class="page-stack plan-details">
      <section class="section-card product-section">
        <div class="detail-product">
          <ProductImage :src="plan.product.image_url" :alt="plan.product.name" />
          <div class="product-identity"><h2>{{ plan.product.name }}</h2><p>{{ plan.product.number }}</p></div>
        </div>
        <dl class="summary-grid plan-summary">
          <div><dt>计划数量</dt><dd>{{ displayQuantity(plan.product.quantity) }} {{ plan.product.unit }}</dd></div>
          <div><dt>订单数量</dt><dd>{{ displayQuantity(plan.product.order_quantity) }} {{ plan.product.unit }}</dd></div>
          <div><dt>生产单号</dt><dd>{{ plan.task_number }}</dd></div>
          <div><dt>车间</dt><dd>{{ plan.workshop.name }}</dd></div>
          <div><dt>计划日期</dt><dd>{{ plan.plan_date || '未安排' }}</dd></div>
          <div><dt>报工进度</dt><dd>{{ progressLabel(plan) }}</dd></div>
        </dl>
        <dl class="product-attributes">
          <div><dt>规格</dt><dd>{{ plan.product.specification || '—' }}</dd></div>
          <div><dt>颜色</dt><dd>{{ plan.product.color || '—' }}</dd></div>
          <div><dt>材质</dt><dd>{{ plan.product.material || '—' }}</dd></div>
        </dl>
      </section>
      <section class="section-card issue-section">
        <h2 class="section-title">领料申请</h2>
        <p v-if="!plan.can_issue" class="permission-note">{{ plan.issue_reason }}</p>
        <van-button class="issue-button" type="primary" plain block :disabled="!plan.can_issue" @click="navigate('/issue')">申请领料</van-button>
        <button v-if="plan.can_view_issues" class="action-link record-link" @click="navigate('/issue-records')"><span>查看本产品领料记录</span><van-icon name="arrow" aria-hidden="true" /></button>
      </section>
      <section v-if="plan.plan_category === 'ASSEMBLY'" class="section-card receipt-section">
        <h2 class="section-title">成品入库</h2>
        <p class="permission-note">{{ plan.can_receive_finished ? '提交后由仓库确认入库。' : plan.finished_receipt_reason }}</p>
        <van-button class="issue-button" type="primary" plain block :disabled="!plan.can_receive_finished" @click="router.push({ path: '/finished-receipt', query: { schedule_product_id: plan.schedule_product_id } })">成品入库</van-button>
      </section>
      <section v-if="['METAL', 'SEWING'].includes(plan.plan_category)" class="section-card receipt-section">
        <h2 class="section-title">半成品入库</h2>
        <p class="permission-note">{{ plan.can_receive_semi ? '提交后由仓库确认入库。' : plan.semi_receipt_reason }}</p>
        <van-button class="issue-button" type="primary" plain block :disabled="!plan.can_receive_semi" @click="router.push({ path: '/semi-receipt', query: { schedule_product_id: plan.schedule_product_id, plan_category: plan.plan_category } })">半成品入库</van-button>
      </section>
      <section class="section-card report-section">
        <h2 class="section-title">选择报工工艺</h2>
        <p v-if="!plan.reporting_crafts.length" class="permission-note">{{ plan.report_reason || '暂无可查看的工艺' }}</p>
        <ul class="craft-list">
          <li v-for="craft in plan.reporting_crafts" :key="craft.id" class="craft-row">
            <div class="craft-information"><strong>{{ craft.name }}</strong><p v-if="!craft.can_report" class="permission-note">{{ craft.reason }}</p><p v-else-if="craft.progress?.percentage !== null && craft.progress?.percentage !== undefined" class="craft-progress">已报进度 {{ displayQuantity(craft.progress.percentage) }}%</p></div>
            <van-button class="report-button" type="primary" size="small" :disabled="!craft.can_open_report" @click="navigate('/report', craft.id)">报工</van-button>
          </li>
        </ul>
        <button v-if="plan.can_view_reports" class="action-link record-link" @click="navigate('/report-records')"><span>查看本计划报工记录</span><van-icon name="arrow" aria-hidden="true" /></button>
      </section>
    </div>
  </WorkPage>
</template>

<style scoped>
.detail-loading { padding: 44px 0; color: var(--mobile-muted); }
.detail-retry { min-height: 44px; }
.plan-details { color: var(--mobile-text); }
.plan-details .section-card { min-width: 0; border: 1px solid var(--mobile-border); }
.detail-product { display: flex; gap: 14px; align-items: center; padding-bottom: 18px; }
.product-identity { flex: 1; min-width: 0; }
.product-identity h2 { margin: 0; font-size: 20px; font-weight: 700; line-height: 1.5; overflow-wrap: anywhere; }
.product-identity p { margin: 5px 0 0; color: var(--mobile-muted); font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }
.plan-summary { margin: 0; padding-top: 18px; border-top: 1px solid var(--mobile-border); }
.plan-summary > div { min-width: 0; }
.plan-summary dt { font-size: 14px; }
.plan-summary dd { font-size: 16px; line-height: 1.5; }
.product-attributes { display: flex; flex-direction: column; gap: 8px; margin: 18px 0 0; padding-top: 16px; border-top: 1px solid var(--mobile-border); font-size: 14px; line-height: 1.6; }
.product-attributes > div { display: grid; grid-template-columns: 3em minmax(0, 1fr); gap: 8px; }
.product-attributes dt { color: var(--mobile-muted); }
.product-attributes dd { margin: 0; overflow-wrap: anywhere; }
.permission-note { margin: 0 0 14px; color: var(--mobile-muted); font-size: 14px; line-height: 1.6; overflow-wrap: anywhere; }
.issue-button { min-height: 48px; font-size: 16px; }
.record-link { display: flex; justify-content: space-between; align-items: center; gap: 12px; width: 100%; min-height: 48px; margin-top: 16px; padding: 14px 0 0; border-top: 1px solid var(--mobile-border); text-align: left; font-size: 15px; line-height: 1.5; }
.record-link span { min-width: 0; overflow-wrap: anywhere; }
.record-link .van-icon { flex-shrink: 0; font-size: 16px; }
.report-section .section-title { margin-bottom: 4px; }
.report-section > .permission-note { margin: 12px 0 0; }
.craft-list { margin: 0; padding: 0; list-style: none; }
.craft-row { display: flex; align-items: center; gap: 12px; justify-content: space-between; padding: 16px 0; }
.craft-row + .craft-row { border-top: 1px solid var(--mobile-border); }
.craft-row:last-child { padding-bottom: 0; }
.craft-information { flex: 1; min-width: 0; }
.craft-information strong { display: block; font-size: 16px; font-weight: 600; line-height: 1.5; overflow-wrap: anywhere; }
.craft-information p { margin: 6px 0 0; }
.craft-progress { color: var(--mobile-muted); font-size: 14px; line-height: 1.5; font-variant-numeric: tabular-nums; }
.report-button { flex-shrink: 0; min-width: 76px; min-height: 44px; font-size: 16px; }
@media (max-width: 359px) {
  .detail-product { gap: 12px; align-items: flex-start; }
  .product-identity h2 { font-size: 18px; }
  .plan-summary { gap: 14px 10px; }
}
</style>
