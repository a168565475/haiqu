<script setup lang="ts">
import { computed } from 'vue'
import DeliveryStatusTag from '@/components/common/DeliveryStatusTag.vue'
import type { DeliveryReminder } from '@/types/deliveryReminders'
import type { PurchasePlanAmount, PurchasePlanBatch } from '@/types/purchasePlans'
import { compactDecimal } from '@/utils/compactDecimal'

const props = defineProps<{ batches: PurchasePlanBatch[]; purchaseReminders: DeliveryReminder[] }>()
const rows = computed(() => props.batches.map(batch => {
  const movements = [
    ...batch.arrivals.map(movement => ({ kind: '到货', movement })),
    ...batch.returns.map(movement => ({ kind: '退货', movement })),
  ]
  return { batch, rows: movements.length ? movements : [{ kind: '', movement: null }] }
}))

function formatAmount(value: PurchasePlanAmount | null) {
  return value ? `${compactDecimal(value.quantity)} ${value.unit}` : ''
}
</script>

<template>
  <div v-if="purchaseReminders.length" class="purchase-plan-detail-scroll">
    <table class="purchase-plan-detail-table" aria-label="待下单明细">
      <thead><tr><th scope="col">采购事项</th><th scope="col">交期状态</th><th scope="col">截止日</th><th scope="col">还需采购</th></tr></thead>
      <tbody>
        <tr v-for="reminder in purchaseReminders" :key="reminder.reason">
          <td>{{ reminder.reason || reminder.action }}</td>
          <td><DeliveryStatusTag :reminder="reminder" /></td>
          <td>{{ reminder.due }}</td>
          <td v-if="reminder.quantity !== null">{{ compactDecimal(reminder.quantity) }} {{ reminder.unit }}</td>
          <td v-else>待核</td>
        </tr>
      </tbody>
    </table>
  </div>
  <p v-if="!rows.length" class="purchase-plan-empty">暂无采购批次</p>
  <div v-else class="purchase-plan-detail-scroll">
    <table class="purchase-plan-detail-table" aria-label="采购批次及回厂明细">
      <thead>
        <tr>
          <th scope="col">采购单号</th>
          <th scope="col">批次</th>
          <th scope="col">供应商</th>
          <th scope="col">下单日期</th>
          <th scope="col">约定回厂日期</th>
          <th scope="col">交期状态</th>
          <th scope="col">实购数量</th>
          <th scope="col">到货进度</th>
          <th scope="col">类型</th>
          <th scope="col">原单号</th>
          <th scope="col">实际回厂／质检日期</th>
          <th scope="col">本次数量</th>
          <th scope="col">实际用时</th>
          <th scope="col">来源 BOM</th>
          <th scope="col">采购表号</th>
          <th scope="col">共采产品</th>
        </tr>
      </thead>
      <tbody v-for="{ batch, rows: items } in rows" :key="batch.id">
        <tr v-for="({ kind, movement }, index) in items" :key="`${kind}-${movement?.id || batch.id}`">
          <template v-if="index === 0">
            <td :rowspan="items.length" class="purchase-plan-order-number">{{ batch.order_number }}</td>
            <td :rowspan="items.length">{{ batch.batch_number }}</td>
            <td :rowspan="items.length">{{ batch.supplier }}</td>
            <td :rowspan="items.length">{{ batch.ordered_on }}</td>
            <td :rowspan="items.length">{{ batch.expected_on }}</td>
            <td :rowspan="items.length"><DeliveryStatusTag :reminder="batch.reminder" /></td>
            <td :rowspan="items.length">
              {{ formatAmount(batch.ordered) }}
              <div v-if="batch.ordered_equivalents.length" class="purchase-plan-subtext">
                {{ batch.ordered_equivalents.map(formatAmount).join(' / ') }}
              </div>
              <div v-if="batch.unit_price" class="purchase-plan-subtext">
                {{ compactDecimal(batch.unit_price.quantity) }} {{ batch.currency }}/{{ batch.unit_price.unit }}
              </div>
            </td>
            <td :rowspan="items.length">
              {{ batch.progress }}
              <div v-if="batch.remaining && (batch.progress === '未到齐' || batch.progress === '待补收')" class="purchase-plan-subtext">
                还差 {{ formatAmount(batch.remaining) }}
              </div>
              <div v-if="batch.complete_on" class="purchase-plan-subtext">{{ batch.complete_on }} 首次到齐</div>
            </td>
          </template>
          <td>{{ kind }}<div v-if="movement?.status" class="purchase-plan-subtext">{{ movement.status }}</div></td>
          <td>{{ movement?.number }}</td>
          <td>{{ movement?.date }}</td>
          <td>
            {{ formatAmount(movement?.amount ?? null) }}
            <div v-if="movement?.equivalents.length" class="purchase-plan-subtext">
              {{ movement.equivalents.map(formatAmount).join(' / ') }}
            </div>
          </td>
          <td>{{ movement?.days != null ? `${movement.days} 天` : '' }}</td>
          <template v-if="index === 0">
            <td :rowspan="items.length">{{ batch.bom_numbers.join('、') }}</td>
            <td :rowspan="items.length">{{ batch.sheet_numbers.join('、') }}</td>
            <td :rowspan="items.length">{{ batch.shared ? batch.products.join('、') || '待分配' : '' }}</td>
          </template>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.purchase-plan-detail-scroll { overflow-x: auto; padding: 10px 14px; }
.purchase-plan-detail-table { width: 100%; border-collapse: collapse; text-align: left; }
.purchase-plan-detail-table th, .purchase-plan-detail-table td {
  padding: 6px 10px; border: 1px solid var(--el-table-border-color, var(--el-border-color-lighter)); vertical-align: top;
}
.purchase-plan-detail-table th { white-space: nowrap; background: var(--el-table-header-bg-color, var(--el-fill-color-light)); }
.purchase-plan-order-number { white-space: nowrap; }
.purchase-plan-subtext { color: var(--el-text-color-secondary); }
.purchase-plan-empty { padding: 8px 14px; margin: 0; }
</style>
