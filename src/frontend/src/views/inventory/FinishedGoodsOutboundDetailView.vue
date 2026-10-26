<script setup lang="ts">
import { compactDecimal } from '@/utils/compactDecimal'
import { ref, watch } from 'vue'
import { AxiosError } from 'axios'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { fetchFinishedGoodsOutbound } from '@/api/inventory'
import type { FinishedGoodsOutboundDetail } from '@/types/inventory'
const route = useRoute(); const router = useRouter(); const detail = ref<FinishedGoodsOutboundDetail | null>(null); const loading = ref(false); const errorMessage = ref('')
const message = (error: unknown) => error instanceof AxiosError ? (error.response?.data as { error?: { message?: string } })?.error?.message || '出货单读取失败，请重试。' : '出货单读取失败，请重试。'
const money = (value: string | number | null | undefined) => compactDecimal(Number(value || 0).toFixed(2))
const time = (value: string) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const quantity = (value: string | number | null | undefined, unit?: string) => value == null ? '—' : `${compactDecimal(value)}${unit ? ` ${unit}` : ''}`
let sequence = 0
async function load() { const current = ++sequence; loading.value = true; errorMessage.value = ''; detail.value = null; try { const result = await fetchFinishedGoodsOutbound(String(route.params.outboundId || '')); if (current === sequence) detail.value = result } catch (error) { if (current === sequence) errorMessage.value = message(error) } finally { if (current === sequence) loading.value = false } }
watch(() => route.params.outboundId, () => { void load() }, { immediate: true })
</script>

<template>
  <section class="outbound-detail-page erp-glass-detail" :aria-busy="loading">
    <header class="detail-heading">
      <h1>出货单详情</h1>
      <div class="heading-actions">
        <button type="button" class="detail-button erp-list-button erp-button-motion" @click="load">刷新</button>
        <button type="button" class="detail-button erp-list-button erp-list-button--primary erp-button-motion" @click="router.push({ name: 'finished-goods-outbounds' })"><ArrowLeft aria-hidden="true" />返回出库记录</button>
      </div>
    </header>
    <div v-if="loading" class="detail-state" role="status">正在加载出货单详情…</div>
    <div v-else-if="errorMessage" class="detail-state error-state" role="alert"><p>{{ errorMessage }}</p><button type="button" class="detail-button erp-list-button erp-button-motion" @click="load">重新加载</button></div>
    <template v-else-if="detail">
      <dl class="info-card">
        <div><dt>出货单号</dt><dd>{{ detail.outbound_number }}</dd></div>
        <div><dt>出货日期</dt><dd>{{ detail.shipment_date || '—' }}</dd></div>
        <div><dt>出库负责人</dt><dd>{{ detail.responsible_employee_name || detail.responsible_name_snapshot || '—' }}</dd></div>
        <div><dt>制单人</dt><dd>{{ detail.outbound_by_name || '—' }}</dd></div>
        <div><dt>生成时间</dt><dd>{{ time(detail.outbound_at) }}</dd></div>
        <div><dt>装卸费用</dt><dd>{{ money(detail.loading_fee) }}</dd></div>
        <div><dt>其他费用</dt><dd>{{ money(detail.other_fee) }}</dd></div>
        <div class="remark"><dt>备注</dt><dd>{{ detail.remark || '—' }}</dd></div>
      </dl>
      <section class="lines-card">
        <h2>出库明细</h2>
        <div class="table-wrap" tabindex="0" aria-label="出库明细表格">
          <table class="detail-table">
            <colgroup><col style="width:154px" /><col style="width:136px" /><col style="width:128px" /><col style="width:100px" /><col style="width:80px" /><col style="width:140px" /><col style="width:94px" /><col style="width:110px" /><col style="width:110px" /><col style="width:110px" /><col style="width:180px" /><col style="width:114px" /><col style="width:128px" /></colgroup>
            <thead><tr><th scope="col">生产任务单号</th><th scope="col">产品编码</th><th scope="col">产品名称</th><th scope="col">货号</th><th scope="col">材质</th><th scope="col">规格</th><th scope="col">颜色</th><th scope="col" class="numeric">订单数量</th><th scope="col" class="numeric">入库数量</th><th scope="col" class="numeric">出库数量</th><th scope="col">仓库 / 库位</th><th scope="col" class="numeric">每箱数量</th><th scope="col" class="numeric">箱数 / 尾数</th></tr></thead>
            <tbody>
              <tr v-for="line in detail.lines" :key="line.id">
                <td>{{ line.task_number_snapshot || '—' }}</td><td>{{ line.product_code_snapshot || '—' }}</td><td>{{ line.product_name_snapshot || '—' }}</td><td>{{ line.item_number_snapshot || '—' }}</td><td>{{ line.material_snapshot || '—' }}</td><td>{{ line.specification_snapshot || '—' }}</td><td>{{ line.actual_color || '—' }}</td>
                <td class="numeric">{{ quantity(line.order_quantity, line.unit_name) }}</td><td class="numeric">{{ quantity(line.received_quantity, line.unit_name) }}</td><td class="numeric">{{ quantity(line.outbound_quantity, line.unit_name) }}</td>
                <td>{{ line.warehouse_name || '—' }} / {{ line.location_number || '—' }}</td><td class="numeric">{{ compactDecimal(line.quantity_per_box) }}</td><td class="numeric">{{ line.box_count }} / {{ compactDecimal(line.tail_quantity) }}</td>
              </tr>
              <tr v-if="!detail.lines.length"><td colspan="13" class="empty-record">暂无出库明细</td></tr>
            </tbody>
          </table>
        </div>
      </section>
      <section v-if="detail.loading_images?.length" class="images-card">
        <h2>装卸图片</h2>
        <div class="images"><a v-for="image in detail.loading_images" :key="image.id || image.url" :href="image.url" target="_blank" rel="noreferrer"><img :src="image.url" :alt="image.name || '装卸图片'" /></a></div>
      </section>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/theme/detail' as detail;
.outbound-detail-page { box-sizing: border-box; min-width: 0; padding: 0; background: transparent; color: token.$crm-text-primary; font: 13px token.$crm-font-body; container-type: inline-size; }
.detail-heading { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 14px; min-height: 46px; margin-bottom: 14px; }
.detail-heading h1 { margin: 0; font: 700 36px/44px token.$crm-font-body; }
.heading-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; }
.detail-button { white-space: nowrap; }
.detail-button svg { width: 16px; height: 16px; }
.detail-button:focus-visible, .table-wrap:focus-visible, .images a:focus-visible { outline: 2px solid token.$crm-focus; outline-offset: 2px; }
.info-card { @include detail.surface; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 0 0 14px; padding: 16px; }
.info-card > div { min-width: 0; }
.info-card dt { color: token.$crm-text-secondary; font-size: 12px; line-height: 18px; }
.info-card dd { margin: 4px 0 0; overflow-wrap: anywhere; font-size: 13px; line-height: 20px; }
.remark { grid-column: 1 / -1; }
.remark dd { white-space: pre-wrap; }
.lines-card, .images-card { @include detail.surface; padding: 14px 16px 16px; }
.images-card { margin-top: 14px; }
h2 { margin: 0 0 14px; font-size: 15px; font-weight: 600; line-height: 24px; }
.table-wrap { max-width: 100%; overflow-x: auto; border: 1px solid var(--erp-table-grid); border-radius: var(--erp-radius-control); background: var(--erp-table-body-fill); }
.detail-table { width: 100%; min-width: 1584px; border-collapse: separate; border-spacing: 0; table-layout: fixed; }
.detail-table th, .detail-table td { box-sizing: border-box; padding: 0 16px; text-align: left; border-right: 1px solid var(--erp-table-grid); border-bottom: 1px solid var(--erp-table-grid); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.detail-table th:last-child, .detail-table td:last-child { border-right: 0; }
.detail-table thead tr, .detail-table th { height: 44px; }
.detail-table th { color: var(--erp-table-header-text); background: var(--erp-table-header-fill); font-size: 11px; font-weight: 500; line-height: 16px; }
.detail-table tbody tr, .detail-table td { height: 40px; }
.detail-table td { color: var(--erp-table-text); font-size: 12px; line-height: 18px; }
.detail-table .numeric { text-align: right; }
.detail-table tbody tr:hover { background: var(--erp-color-hover); }
.detail-table tbody tr:last-child td { border-bottom: 0; }
.detail-table .empty-record { text-align: center; color: token.$crm-text-secondary; }
.images { display: flex; flex-wrap: wrap; gap: 12px; }
.images img { display: block; width: 140px; height: 100px; object-fit: cover; border-radius: var(--erp-radius-control); border: 1px solid var(--erp-color-border); }
.detail-state { @include detail.surface; padding: 32px; text-align: center; color: token.$crm-text-secondary; }
.error-state { color: token.$crm-danger; }
@container (max-width: 650px) { .info-card { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@container (max-width: 420px) { .info-card { grid-template-columns: minmax(0, 1fr); } }
</style>
