<script setup lang="ts">
import { ref, watch } from 'vue'
import { Button as VanButton, Collapse as VanCollapse, CollapseItem as VanCollapseItem, Icon as VanIcon, Progress as VanProgress, Tag as VanTag } from 'vant'
import 'vant/es/button/style'
import 'vant/es/collapse/style'
import 'vant/es/collapse-item/style'
import 'vant/es/icon/style'
import 'vant/es/progress/style'
import 'vant/es/tag/style'
import ProductImage from '@/components/ProductImage.vue'
import type { MobilePlan } from '@/types/mobilePlan'
import { displayQuantity, progressLabel } from '@/utils/planDisplay'

const props = defineProps<{ plans: MobilePlan[]; mode: 'list' | 'summary' }>()
const emit = defineEmits<{ open: [plan: MobilePlan]; issue: [plan: MobilePlan]; report: [plan: MobilePlan]; receiveFinished: [plan: MobilePlan]; receiveSemi: [plan: MobilePlan] }>()
const expandedKey = ref('')

watch(() => props.plans.map(plan => plan.key), (keys, previousKeys) => {
  if (!keys.length) {
    expandedKey.value = ''
    return
  }
  if (expandedKey.value && keys.includes(expandedKey.value)) return
  const appending = previousKeys?.length && keys.length >= previousKeys.length
    && previousKeys.every((key, index) => keys[index] === key)
  if (!expandedKey.value && appending) return
  expandedKey.value = keys[0]!
}, { immediate: true })

function handleSummaryKey(event: KeyboardEvent, key: string) {
  if (!(event.target instanceof HTMLElement) || !event.target.classList.contains('van-collapse-item__title')) return
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  expandedKey.value = expandedKey.value === key ? '' : key
}
</script>

<template>
  <div v-if="mode === 'list'" class="production-plan-list plan-list-mode">
    <article v-for="plan in plans" :key="plan.key" class="plan-list-row" :data-plan-key="plan.key">
      <div class="list-product-header">
        <button type="button" class="plan-open list-product" @click="emit('open', plan)">
          <ProductImage class="list-photo" :src="plan.product.image_url" :alt="plan.product.name" />
          <span class="product-copy">
            <span class="product-name">{{ plan.product.name }}</span>
            <span class="product-number">{{ plan.product.number || '未设置产品编号' }}</span>
          </span>
        </button>
        <div class="list-progress">
          <span>报工进度</span>
          <strong>{{ progressLabel(plan) }}</strong>
          <van-progress v-if="plan.progress?.percentage !== null && plan.progress?.percentage !== undefined" :percentage="Math.min(100, Math.max(0, plan.progress.percentage))" :show-pivot="false" stroke-width="6" />
        </div>
      </div>
      <div class="plan-order"><span>{{ plan.task_number }}</span><van-tag plain type="primary">{{ plan.task_status_display }}</van-tag></div>
      <p class="product-specification">{{ [plan.product.specification, plan.product.color].filter(Boolean).join(' · ') || '暂无规格' }}</p>
      <dl class="plan-context">
        <div><dt>所属车间</dt><dd>{{ plan.workshop.name }}</dd></div>
        <div><dt>计划类别</dt><dd>{{ plan.plan_category_label }}</dd></div>
      </dl>
      <dl class="plan-numbers">
        <div><dt>计划数量</dt><dd>{{ displayQuantity(plan.product.quantity) }} <span>{{ plan.product.unit }}</span></dd></div>
        <div><dt>计划日期</dt><dd class="plan-date">{{ plan.plan_date || '未安排' }}</dd></div>
      </dl>
      <div class="plan-actions" :class="{ 'has-receipt': ['METAL', 'SEWING', 'ASSEMBLY'].includes(plan.plan_category) }">
        <van-button plain type="primary" :disabled="!plan.can_issue" @click="emit('issue', plan)">申请领料</van-button>
        <van-button type="primary" :disabled="!plan.can_open_report" @click="emit('report', plan)">生产报工</van-button>
        <van-button v-if="plan.plan_category === 'ASSEMBLY'" plain type="primary" :disabled="!plan.can_receive_finished" @click="emit('receiveFinished', plan)">成品入库</van-button>
        <van-button v-if="['METAL', 'SEWING'].includes(plan.plan_category)" plain type="primary" :disabled="!plan.can_receive_semi" @click="emit('receiveSemi', plan)">半成品入库</van-button>
      </div>
      <p v-if="!plan.can_issue && plan.issue_reason" class="plan-unavailable">领料：{{ plan.issue_reason }}</p>
      <p v-if="!plan.can_report && plan.report_reason" class="plan-unavailable">报工：{{ plan.report_reason }}</p>
      <p v-if="plan.plan_category === 'ASSEMBLY' && !plan.can_receive_finished && plan.finished_receipt_reason" class="plan-unavailable">入库：{{ plan.finished_receipt_reason }}</p>
      <p v-if="['METAL', 'SEWING'].includes(plan.plan_category) && !plan.can_receive_semi && plan.semi_receipt_reason" class="plan-unavailable">入库：{{ plan.semi_receipt_reason }}</p>
    </article>
  </div>

  <van-collapse v-else v-model="expandedKey" accordion :border="false" class="production-plan-list plan-summary-mode">
    <van-collapse-item v-for="plan in plans" :key="plan.key" :name="plan.key" :border="false" :is-link="false" clickable class="plan-summary-item" :class="{ 'is-expanded': expandedKey === plan.key }" :data-plan-key="plan.key" @keydown="handleSummaryKey($event, plan.key)">
      <template #title>
        <div class="summary-heading">
          <div class="plan-order"><span>{{ plan.task_number }}</span><van-tag plain type="primary">{{ plan.task_status_display }}</van-tag></div>
          <span class="summary-disclosure">{{ expandedKey === plan.key ? '收起详情' : '展开详情' }}<van-icon :name="expandedKey === plan.key ? 'arrow-up' : 'arrow-down'" aria-hidden="true" /></span>
        </div>
        <div class="summary-product">
          <h2>{{ plan.product.name }}</h2>
          <dl><dt>计划数量</dt><dd>{{ displayQuantity(plan.product.quantity) }} <span>{{ plan.product.unit }}</span></dd></dl>
        </div>
        <div class="summary-progress">
          <span>报工进度</span>
          <van-progress v-if="plan.progress?.percentage !== null && plan.progress?.percentage !== undefined" :percentage="Math.min(100, Math.max(0, plan.progress.percentage))" :show-pivot="false" stroke-width="6" />
          <strong>{{ progressLabel(plan) }}</strong>
        </div>
      </template>
      <div class="summary-detail">
        <button type="button" class="plan-open summary-product-detail" @click="emit('open', plan)">
          <ProductImage :src="plan.product.image_url" :alt="plan.product.name" />
          <span class="product-copy">
            <span class="product-number">{{ plan.product.number || '未设置产品编号' }}</span>
            <span class="product-specification">{{ [plan.product.specification, plan.product.color].filter(Boolean).join(' · ') || '暂无规格' }}</span>
            <span class="plan-detail-link">查看生产计划<van-icon name="arrow" aria-hidden="true" /></span>
          </span>
        </button>
        <dl class="plan-context">
          <div><dt>所属车间</dt><dd>{{ plan.workshop.name }}</dd></div>
          <div><dt>计划类别</dt><dd>{{ plan.plan_category_label }}</dd></div>
        </dl>
        <dl class="summary-date"><dt>计划日期</dt><dd>{{ plan.plan_date || '未安排' }}</dd></dl>
        <div class="plan-actions" :class="{ 'has-receipt': ['METAL', 'SEWING', 'ASSEMBLY'].includes(plan.plan_category) }">
          <van-button plain type="primary" :disabled="!plan.can_issue" @click="emit('issue', plan)">申请领料</van-button>
          <van-button type="primary" :disabled="!plan.can_open_report" @click="emit('report', plan)">生产报工</van-button>
          <van-button v-if="plan.plan_category === 'ASSEMBLY'" plain type="primary" :disabled="!plan.can_receive_finished" @click="emit('receiveFinished', plan)">成品入库</van-button>
          <van-button v-if="['METAL', 'SEWING'].includes(plan.plan_category)" plain type="primary" :disabled="!plan.can_receive_semi" @click="emit('receiveSemi', plan)">半成品入库</van-button>
        </div>
        <p v-if="!plan.can_issue && plan.issue_reason" class="plan-unavailable">领料：{{ plan.issue_reason }}</p>
        <p v-if="!plan.can_report && plan.report_reason" class="plan-unavailable">报工：{{ plan.report_reason }}</p>
        <p v-if="plan.plan_category === 'ASSEMBLY' && !plan.can_receive_finished && plan.finished_receipt_reason" class="plan-unavailable">入库：{{ plan.finished_receipt_reason }}</p>
        <p v-if="['METAL', 'SEWING'].includes(plan.plan_category) && !plan.can_receive_semi && plan.semi_receipt_reason" class="plan-unavailable">入库：{{ plan.semi_receipt_reason }}</p>
      </div>
    </van-collapse-item>
  </van-collapse>
</template>

<style scoped>
.production-plan-list { min-width: 0; color: var(--mobile-text); }
.plan-list-mode { border-radius: 12px; background: var(--mobile-surface); }
.plan-list-row { padding: 18px 16px; }
.plan-list-row + .plan-list-row { border-top: 1px solid var(--mobile-border); }
.list-product-header { display: flex; align-items: flex-start; gap: 12px; }
.plan-open { min-width: 0; padding: 0; border: 0; background: none; color: inherit; text-align: left; cursor: pointer; }
.list-product { display: flex; align-items: center; flex: 1; gap: 12px; min-height: 60px; }
.list-product .list-photo { width: 60px; height: 60px; border-radius: 8px; }
.product-copy { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 4px; overflow-wrap: anywhere; }
.product-name { font-size: 18px; font-weight: 650; line-height: 1.5; }
.product-number { color: var(--mobile-muted); font-size: 14px; line-height: 1.5; }
.list-progress { flex: 0 0 76px; min-width: 0; padding-left: 12px; border-left: 1px solid var(--mobile-border); }
.list-progress > span { display: block; color: var(--mobile-muted); font-size: 13px; }
.list-progress strong { display: block; margin: 4px 0 8px; color: var(--mobile-primary); font-size: 18px; line-height: 1.4; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.plan-order { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 6px 8px; min-width: 0; margin: 12px 0 8px; color: var(--mobile-muted); font-size: 14px; line-height: 1.5; }
.plan-order > span:first-child { min-width: 0; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.plan-order :deep(.van-tag) { max-width: 100%; padding: 2px 6px; border-radius: 4px; font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.product-specification { margin: 0; color: var(--mobile-muted); font-size: 14px; line-height: 1.6; overflow-wrap: anywhere; }
.plan-context, .plan-numbers { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }
.plan-context { margin: 12px 0; }
.production-plan-list dt { color: var(--mobile-muted); font-size: 13px; line-height: 1.6; }
.production-plan-list dd { margin: 3px 0 0; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.plan-context dd { font-size: 15px; line-height: 1.5; }
.plan-numbers { margin: 14px 0; padding-top: 12px; border-top: 1px solid var(--mobile-border); }
.plan-numbers dd { font-size: 18px; font-weight: 600; line-height: 1.5; }
.plan-numbers dd > span, .summary-product dd > span { font-size: 14px; font-weight: 400; }
.plan-numbers .plan-date { font-size: 16px; line-height: 1.7; }
.plan-actions { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }
.plan-actions .van-button { min-height: 48px; padding-inline: 8px; font-size: 16px; }
.plan-actions.has-receipt { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.plan-actions.has-receipt .van-button { font-size: 15px; padding-inline: 4px; }
.plan-unavailable { margin: 10px 0 0; color: var(--mobile-muted); font-size: 13px; line-height: 1.65; overflow-wrap: anywhere; }
.plan-summary-item { margin-bottom: 12px; border: 1px solid transparent; border-radius: 12px; background: var(--mobile-surface); }
.plan-summary-item:last-child { margin-bottom: 0; }
.plan-summary-item.is-expanded { border-color: var(--mobile-border); background: var(--mobile-primary-soft); }
.plan-summary-item :deep(.van-collapse-item__title) { display: block; padding: 16px; border-radius: 12px; background: transparent; color: var(--mobile-text); }
.plan-summary-item :deep(.van-collapse-item__content) { padding: 0 16px 16px; background: transparent; color: var(--mobile-text); font-size: 16px; }
.plan-summary-item :deep(.van-collapse-item__title:focus-visible) { outline: 2px solid var(--mobile-primary); outline-offset: 2px; }
.summary-heading { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 8px 12px; }
.summary-heading .plan-order { flex: 1; margin: 0; color: var(--mobile-text); }
.summary-heading .plan-order > span:first-child { font-weight: 600; }
.summary-disclosure { display: inline-flex; align-items: center; gap: 6px; flex-shrink: 0; color: var(--mobile-primary); font-size: 13px; white-space: nowrap; }
.summary-product { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, .8fr); align-items: start; gap: 16px; margin: 14px 0; }
.summary-product h2 { margin: 0; font-size: 18px; line-height: 1.5; font-weight: 650; overflow-wrap: anywhere; }
.summary-product dl { margin: 0; }
.summary-product dd { font-size: 18px; font-weight: 600; line-height: 1.5; }
.summary-progress { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.summary-progress > span { color: var(--mobile-muted); font-size: 13px; }
.summary-progress > .van-progress { min-width: 40px; flex: 1; }
.summary-progress strong { margin-left: auto; color: var(--mobile-primary); font-size: 16px; font-weight: 600; line-height: 1.5; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.summary-detail { padding-top: 16px; border-top: 1px solid var(--mobile-border); }
.summary-product-detail { display: flex; align-items: center; gap: 14px; width: 100%; }
.summary-product-detail .product-number { color: var(--mobile-text); font-size: 16px; font-weight: 600; }
.plan-detail-link { display: inline-flex; align-items: center; gap: 6px; min-height: 32px; color: var(--mobile-primary); font-size: 14px; }
.summary-date { margin: 12px 0 16px; }
.summary-date dd { font-size: 16px; font-weight: 500; }
@media (max-width: 359px) {
  .plan-actions.has-receipt .van-button { font-size: 14px; }
  .plan-list-row { padding-inline: 12px; }
  .list-product-header { gap: 8px; }
  .list-product { gap: 8px; }
  .list-progress { flex-basis: 72px; padding-left: 8px; }
  .summary-heading .plan-order { flex-basis: 100%; }
  .summary-disclosure { margin-left: auto; }
  .plan-summary-item :deep(.van-collapse-item__title) { padding-inline: 12px; }
  .plan-summary-item :deep(.van-collapse-item__content) { padding-inline: 12px; }
}
</style>
