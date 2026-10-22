<script setup lang="ts">
import { computed } from 'vue'
import { scheduleProductImageUrl } from '@/api/productionScheduling'
import productImagePlaceholder from '@/assets/productionScheduling/product-image-placeholder.png'
import type { ProductionSchedule } from '@/types/productionScheduling'
import type { ScheduleProgressStatus, ScheduleStageKey } from '@/types/workshopReporting'
import { scheduleOutsourcingIndicator, scheduleRiskColors, scheduleRiskRank, scheduleStageRisk } from '@/utils/scheduleListDisplay'

const props = defineProps<{ schedule: ProductionSchedule; progress?: ScheduleProgressStatus; failed: boolean }>()
const stages: Array<{ key: ScheduleStageKey | 'OUTBOUND'; label: string }> = [
  { key: 'METAL', label: '金工完成' }, { key: 'CUTTING', label: '裁剪完成' },
  { key: 'SEWING', label: '车缝完成' }, { key: 'ASSEMBLY', label: '装配入库' },
  { key: 'OUTBOUND', label: '出库' },
]
const plannedDateKeys = { METAL: 'metal_return_date', CUTTING: 'sewing_return_date', SEWING: 'sewing_return_date', ASSEMBLY: 'finished_inbound_date' } as const
const stageItems = computed(() => stages.map(stage => {
  const data = stage.key === 'OUTBOUND' ? props.progress?.outbound_progress : props.progress?.stage_progress?.[stage.key]
  const products = props.schedule.products.map(product => {
    const metric = data?.products.find(item => item.schedule_product_id === product.id) ?? {
      schedule_product_id: product.id, status: 'NOT_CONFIGURED' as const, percentage: null, planned_date: stage.key === 'OUTBOUND' ? null : product[plannedDateKeys[stage.key]],
    }
    const risk = stage.key === 'OUTBOUND' && metric.status === 'READY' && metric.percentage !== null
      ? { level: 'normal' as const, description: '累计出库数量 ÷ 订单数量' }
      : scheduleStageRisk(metric, props.progress?.as_of_date)
    return { product, metric, risk }
  })
  let worst = products.reduce((risk, item) => scheduleRiskRank[item.risk.level] > scheduleRiskRank[risk.level] ? item.risk : risk,
    { level: 'unknown' as keyof typeof scheduleRiskColors, description: props.failed ? '进度加载失败，请刷新重试' : '进度数据暂不可用' })
  if (data?.percentage == null && worst.level === 'normal') worst = { level: 'unknown', description: '部分产品进度暂不可用' }
  const outsourcing = stage.key === 'METAL' || stage.key === 'SEWING'
    ? scheduleOutsourcingIndicator(props.progress?.outsourcing_status?.[stage.key]) : null
  return { ...stage, percentage: data?.percentage ?? null, products, risk: worst, color: scheduleRiskColors[worst.level], outsourcing }
}))
function percentageText(value: number | null | undefined) { return value == null ? '—' : `${value}%` }
function imageFallback(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (image.dataset.fallbackApplied === 'true') return
  image.dataset.fallbackApplied = 'true'
  image.src = productImagePlaceholder
}
</script>

<template>
  <div class="schedule-stage-flow" data-testid="schedule-stage-flow">
    <template v-for="stage in stageItems" :key="stage.key">
    <div class="schedule-stage" :style="{ '--stage-color': stage.color }">
      <ElPopover trigger="hover" placement="bottom" :width="440" :show-after="120" :hide-after="120" :persistent="false" popper-class="schedule-stage-popover">
        <template #reference>
          <button type="button" class="schedule-stage-trigger" :aria-label="`${stage.label} ${percentageText(stage.percentage)}，${stage.risk.description}`">
            <span class="schedule-stage-ring">
              <svg viewBox="0 0 44 44" aria-hidden="true" :class="{ 'is-unknown': stage.percentage === null }">
                <circle cx="22" cy="22" r="19" class="stage-track" />
                <circle v-if="stage.percentage !== null" cx="22" cy="22" r="19" class="stage-fill" pathLength="100"
                  :stroke-dasharray="stage.percentage === 0 ? '100 0' : `${stage.percentage} 100`" />
              </svg>
              <span>{{ percentageText(stage.percentage) }}</span>
            </span>
            <span class="schedule-stage-label">{{ stage.label }}</span>
          </button>
        </template>
        <div class="stage-popover-content" :style="{ '--stage-color': stage.color }">
          <header><i />{{ stage.label }}<strong>{{ percentageText(stage.percentage) }}</strong></header>
          <div class="stage-product-list">
            <div v-for="item in stage.products" :key="item.product.id" class="stage-product" :style="{ '--product-risk-color': scheduleRiskColors[item.risk.level] }">
              <img :src="item.product.image_file_id ? scheduleProductImageUrl(schedule.production_task_id, item.product.image_file_id) : productImagePlaceholder" :alt="`${item.product.product.product_name || '产品'}图片`" @error="imageFallback" />
              <strong>{{ item.product.product.product_name || '未命名产品' }} · {{ item.product.product.color_name || '—' }}</strong>
              <div v-if="stage.key === 'OUTBOUND'" class="stage-product-date"><span>订单 {{ item.metric.order_quantity ?? '—' }} {{ item.product.unit_name }}</span><span>出库 {{ item.metric.outbound_quantity ?? '—' }} {{ item.product.unit_name }}</span></div>
              <div v-else class="stage-product-date"><span>计划日期</span><time>{{ item.metric.planned_date || '—' }}</time></div>
              <div class="stage-product-value" :title="item.risk.description"><b>{{ percentageText(item.metric.percentage) }}</b><ElProgress v-if="item.metric.percentage !== null" :percentage="item.metric.percentage" :color="scheduleRiskColors[item.risk.level]" :stroke-width="5" :show-text="false" /></div>
            </div>
            <p v-if="!stage.products.length" class="stage-empty">暂无可查看的产品</p>
          </div>
          <p v-if="stage.products.length" class="stage-risk-note">{{ props.failed ? '进度加载失败，请刷新重试' : stage.risk.description }}</p>
          <footer v-if="stage.key === 'CUTTING'">计划日期沿用车缝回货日期</footer>
        </div>
      </ElPopover>
    </div>
    <div v-if="stage.outsourcing" class="schedule-stage is-outsourcing" :style="{ '--stage-color': stage.outsourcing.color }">
      <ElPopover trigger="hover" placement="bottom" :width="440" :show-after="120" :hide-after="120" :persistent="false" popper-class="schedule-stage-popover">
        <template #reference>
          <button type="button" class="schedule-stage-trigger schedule-outsourcing-trigger" :aria-label="`${stage.key === 'METAL' ? '金工' : '裁剪'}外发，${props.failed ? '外发信息加载失败，请刷新重试' : stage.outsourcing.description}`">
            <span class="schedule-stage-ring schedule-outsourcing-ring" :class="{ 'is-empty': stage.outsourcing.state === 'NONE' }">
              <svg viewBox="0 0 44 44" aria-hidden="true"><circle cx="22" cy="22" r="19" class="stage-fill" /></svg>
              <span>{{ stage.outsourcing.symbol }}</span>
            </span>
            <span class="schedule-stage-label">{{ stage.key === 'METAL' ? '金工' : '裁剪' }}外发</span>
          </button>
        </template>
        <div class="stage-popover-content" :style="{ '--stage-color': stage.outsourcing.color }">
          <header><i />{{ stage.key === 'METAL' ? '金工' : '裁剪' }}外发</header>
          <div v-if="stage.outsourcing.records.length" class="outsourcing-record-list">
            <article v-for="record in stage.outsourcing.records" :key="record.id" class="outsourcing-record" :style="{ '--record-color': scheduleRiskColors[record.risk === 'none' ? 'unknown' : record.risk] }">
              <div class="outsourcing-record-title"><strong>{{ record.order_number }}</strong><span>{{ record.craft_name }}</span></div>
              <div class="outsourcing-record-facts"><span>{{ record.factory_name || '加工厂未填写' }}</span><span>交期 {{ record.expected_return_date || '—' }}</span></div>
              <div class="outsourcing-record-facts"><b>{{ record.description }}</b><span>未回 {{ record.remaining_display }}</span></div>
            </article>
          </div>
          <p v-else class="stage-empty">{{ props.failed ? '外发信息加载失败，请刷新重试' : stage.outsourcing.description }}</p>
        </div>
      </ElPopover>
    </div>
    </template>
  </div>
</template>

<style scoped lang="scss">
.schedule-stage-flow { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); align-items: start; width: 100%; max-width: 420px; padding: 2px 0; }
.schedule-stage { position: relative; min-width: 0; }
.schedule-stage + .schedule-stage::before { content: ''; position: absolute; top: 17px; right: calc(50% + 20px); width: calc(100% - 40px); border-top: 1px solid var(--erp-table-grid, #dce5ee); }
.schedule-stage-trigger { position: relative; display: flex; flex-direction: column; align-items: center; gap: 2px; width: 100%; padding: 0; border: 0; background: transparent; color: var(--erp-table-text); font: inherit; cursor: pointer; }
.schedule-stage-trigger:focus-visible { outline: 2px solid var(--erp-color-brand); outline-offset: 2px; border-radius: 4px; }
.schedule-stage-ring { position: relative; display: grid; place-items: center; width: 34px; height: 34px; font-size: 10px; font-weight: 600; font-variant-numeric: tabular-nums; }
.schedule-stage-ring svg { position: absolute; inset: 0; width: 100%; height: 100%; transform: rotate(-90deg); fill: none; stroke-width: 3.5; }
.stage-track { stroke: color-mix(in srgb, var(--erp-color-text-secondary) 22%, transparent); }
.is-unknown .stage-track { stroke: var(--stage-color); }
.stage-fill { stroke: var(--stage-color); stroke-linecap: round; }
.schedule-stage-label { font-size: 11px; line-height: 16px; white-space: nowrap; }
.schedule-outsourcing-ring { color: var(--stage-color); font-size: 13px; }
.schedule-outsourcing-ring.is-empty svg { fill: color-mix(in srgb, var(--stage-color) 9%, transparent); stroke-width: 2; }
.outsourcing-record-list { display: grid; gap: 8px; max-height: min(360px, 55vh); overflow-y: auto; }
.outsourcing-record { padding: 10px; border: 1px solid var(--erp-table-grid); border-radius: 5px; background: var(--erp-color-subtle); font-size: 12px; }
.outsourcing-record-title, .outsourcing-record-facts { display: flex; justify-content: space-between; align-items: start; gap: 10px; }
.outsourcing-record-title > span { color: var(--erp-color-text-secondary); }
.outsourcing-record-facts { margin-top: 6px; }
.outsourcing-record-facts > span:last-child { flex-shrink: 0; }
.outsourcing-record-facts b { color: var(--record-color); font-weight: 500; }
.stage-popover-content { color: var(--erp-color-text-primary); }
.stage-popover-content header { display: flex; align-items: center; gap: 8px; padding-bottom: 12px; font-size: 14px; font-weight: 600; }
.stage-popover-content header i { width: 9px; height: 9px; border-radius: 50%; background: var(--stage-color); }
.stage-popover-content header strong { margin-left: auto; color: var(--stage-color); }
.stage-product-list { display: grid; gap: 8px; max-height: min(360px, 55vh); overflow-y: auto; }
.stage-product { display: grid; grid-template-columns: 30px minmax(0, 1fr) 100px 42px; align-items: center; gap: 9px; padding: 8px 10px; border: 1px solid var(--erp-table-grid); border-radius: 5px; background: var(--erp-color-subtle); }
.stage-product > img { width: 30px; height: 36px; object-fit: contain; border-radius: 3px; }
.stage-product > strong { min-width: 0; overflow-wrap: anywhere; font-size: 12px; font-weight: 500; }
.stage-product-date { display: grid; gap: 3px; color: var(--erp-color-text-secondary); font-size: 12px; }
.stage-product-value { display: grid; gap: 5px; }
.stage-product-value b { color: var(--product-risk-color); font-size: 12px; font-weight: 500; text-align: right; }
.stage-risk-note { margin: 10px 0 0; padding: 8px 10px; border-radius: 4px; background: color-mix(in srgb, var(--stage-color) 9%, transparent); color: var(--stage-color); font-size: 12px; }
.stage-popover-content footer, .stage-empty { margin: 10px 0 0; color: var(--erp-color-text-secondary); font-size: 12px; }
:global(.el-popper.el-popover.schedule-stage-popover) { max-width: calc(100vw - 32px); box-sizing: border-box; padding: 16px; border: 1px solid var(--erp-table-grid); border-radius: 7px; background: var(--erp-color-surface); box-shadow: 0 8px 24px rgb(30 66 108 / 14%); }
</style>
