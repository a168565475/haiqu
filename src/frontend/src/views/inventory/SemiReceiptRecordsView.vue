<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { AxiosError } from 'axios'
import { useRouter } from 'vue-router'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { fetchSemiReceiptRecord, fetchSemiReceiptRecords } from '@/api/internalReceipts'
import type { SemiReceiptRecord, ReceiptAttributes } from '@/types/internalReceipt'
import '@/styles/internalReceipt.scss'
const router = useRouter()
const rows = ref<SemiReceiptRecord[]>([]), total = ref(0), page = ref(1), source = ref(''), search = ref('')
const loading = ref(false), error = ref(''), detailLoading = ref(false), detailError = ref(''), visible = ref(false)
const detail = ref<SemiReceiptRecord | null>(null), dates = ref<string[] | null>([])
const number = (value:string) => Number(value).toLocaleString('zh-CN')
const specification = (value:ReceiptAttributes) => value.specification || `${value.tube_diameter} × ${value.cutting_length_mm}mm`
let sequence = 0, detailSequence = 0
function message(cause:unknown) { return cause instanceof AxiosError ? cause.response?.data?.error?.message || '请求失败，请重试。' : '请求失败，请重试。' }
async function load(reset=false) {
  if (reset) page.value=1
  const current=++sequence
  loading.value=true; error.value=''
  try {
    const result=await fetchSemiReceiptRecords({page:page.value,page_size:20,source:source.value,search:search.value.trim(),date_from:dates.value?.[0],date_to:dates.value?.[1]})
    if (current!==sequence) return
    rows.value=result.items; total.value=result.total
  } catch (cause) { if (current===sequence) { error.value=message(cause); rows.value=[] } }
  finally { if (current===sequence) loading.value=false }
}
async function open(row:SemiReceiptRecord) {
  const current=++detailSequence
  visible.value=true; detailLoading.value=true; detail.value=null; detailError.value=''
  try { const result=await fetchSemiReceiptRecord(row.id); if(current===detailSequence) detail.value=result }
  catch(cause) { if(current===detailSequence) detailError.value=message(cause) }
  finally { if(current===detailSequence) detailLoading.value=false }
}
onMounted(()=>void load())
</script>

<template>
  <section class="internal-receipt-page">
    <header class="receipt-heading"><h1>半成品入库记录</h1><span class="muted">共 {{ total }} 条入库明细</span><ElButton @click="router.push({name:'material-inventory'})">材料库存</ElButton></header>
    <div class="receipt-filters"><ElInput v-model="search" clearable placeholder="搜索入库单号、生产订单、产品或部位" @keyup.enter="load(true)" @clear="load(true)" /><ElSelect v-model="source" placeholder="全部来源" aria-label="入库来源" @change="load(true)"><ElOption label="全部来源" value=""/><ElOption label="厂内入库" value="INTERNAL"/><ElOption label="外发入库" value="EXTERNAL"/></ElSelect><ElDatePicker v-model="dates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="入库开始日期" end-placeholder="入库结束日期" @change="load(true)"/><ElButton :loading="loading" @click="load(true)">查询</ElButton><ElButton @click="load()">刷新</ElButton></div>
    <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <div class="receipt-records-table receipt-table-scroll" v-loading="loading"><table class="receipt-table"><colgroup><col style="width:178px"><col style="width:96px"><col style="width:144px"><col style="width:128px"><col style="width:96px"><col style="width:80px"><col style="width:80px"><col style="width:128px"><col style="width:86px"><col style="width:76px"><col style="width:100px"><col style="width:82px"><col style="width:58px"><col style="width:106px"><col style="width:82px"><col style="width:62px"></colgroup><thead><tr><th>入库单号</th><th>入库来源</th><th>生产订单</th><th>产品</th><th>部位</th><th>品类</th><th>材质</th><th>规格</th><th>颜色</th><th>厚度</th><th>加工阶段</th><th class="number">数量</th><th>单位</th><th>入库日期</th><th>状态</th><th>操作</th></tr></thead><tbody>
      <tr v-for="row in rows" :key="row.id"><td :title="row.receipt_number" class="primary-text">{{ row.receipt_number }}</td><td><span class="receipt-tag" :class="{external:row.source==='EXTERNAL'}">{{ row.source_display }}</span></td><td :title="row.production_order">{{ row.production_order }}</td><td :title="row.product">{{ row.product }}</td><td :title="row.attributes.part_name" class="primary-text">{{ row.attributes.part_name }}</td><td>{{ row.attributes.category }}</td><td>{{ row.attributes.material }}</td><td :title="specification(row.attributes)">{{ specification(row.attributes) }}</td><td :title="row.attributes.color">{{ row.attributes.color }}</td><td>{{ row.attributes.tube_thickness || row.attributes.thickness || '—' }}</td><td>{{ row.stage }}</td><td class="number">{{ number(row.quantity) }}</td><td>{{ row.unit }}</td><td>{{ row.receipt_date }}</td><td><span class="receipt-tag success">已入库</span></td><td><button class="receipt-link" @click="open(row)">查看</button></td></tr>
      <tr v-if="!rows.length && !loading"><td colspan="16" class="empty">{{ error ? '加载失败，请重试' : '暂无入库记录' }}</td></tr>
    </tbody></table></div>
    <footer class="receipt-pagination"><span class="muted">按入库明细展示，实物库存合并累计</span><ElPagination v-model:current-page="page" :page-size="20" :total="total" layout="total, prev, pager, next" @current-change="load()" /></footer>
    <AppWindowDialog v-model="visible" :title="detail ? `${detail.source_display} · 来源详情` : '入库来源详情'" :width="1180" :height="660" :min-width="760" :min-height="440" class="semi-receipt-source-dialog" :close-on-click-modal="false">
      <div v-loading="detailLoading" class="receipt-detail-body"><ElAlert v-if="detailError" :title="detailError" type="error" :closable="false"/><template v-if="detail">
        <div class="receipt-detail-title"><h2>{{ detail.receipt_number }}</h2><span class="receipt-tag" :class="{external:detail.source==='EXTERNAL'}">{{ detail.source_display }}</span><span class="receipt-tag success">已入库</span></div>
        <div class="receipt-detail-grid"><label>生产订单<strong>{{ detail.production_order }}</strong></label><label>产品<strong>{{ detail.product }}</strong></label><label>{{ detail.source==='INTERNAL' ? '厂内工序' : '加工厂' }}<strong>{{ detail.source_detail?.workshop || detail.source_detail?.factory || '—' }}</strong></label><label v-if="detail.source === 'EXTERNAL'">原外发单<strong>{{ detail.source_detail?.source_number || '—' }}</strong></label><label>收货日期<strong>{{ detail.receipt_date }}</strong></label><label>材料仓 / 库区<strong>{{ detail.warehouse }} / {{ detail.zone }}</strong></label><label>入库人<strong>{{ detail.actor }}</strong></label></div>
        <template v-if="detail.source === 'EXTERNAL' && detail.source_detail?.source_type === 'TUBE_OUTSOURCING_RETURN'"><h3>管材外发回货</h3><div class="receipt-detail-grid receipt-detail-progress"><label>材料来源<strong>{{ detail.source_detail?.source_kind_label || '—' }}</strong></label><label>回货单号<strong>{{ detail.source_detail?.receipt_number || detail.receipt_number }}</strong></label><label>原料颜色<strong>{{ detail.source_detail?.raw_color || '—' }}</strong></label><label>喷塑颜色<strong>{{ detail.source_detail?.spray_color || detail.attributes.color || '—' }}</strong></label><label>实发支数<strong>{{ number(detail.source_detail?.dispatched_quantity || '0') }} 支</strong></label><label>实收支数<strong>{{ number(detail.source_detail?.received_quantity || detail.quantity) }} 支</strong></label><label>少回支数<strong>{{ number(detail.source_detail?.shortage_quantity || '0') }} 支</strong></label><label>少回原因<strong>{{ detail.source_detail?.shortage_reason || '—' }}</strong></label></div></template>
        <h3>入库明细</h3><div class="receipt-table-scroll"><table class="receipt-table"><thead><tr><th>部位</th><th>品类</th><th>材质</th><th>规格</th><th>颜色</th><th>厚度</th><th>加工阶段</th><th class="number">数量</th><th>单位</th></tr></thead><tbody><tr><td>{{ detail.attributes.part_name }}</td><td>{{ detail.attributes.category }}</td><td>{{ detail.attributes.material }}</td><td>{{ specification(detail.attributes) }}</td><td>{{ detail.attributes.color }}</td><td>{{ detail.attributes.tube_thickness || detail.attributes.thickness || '—' }}</td><td>{{ detail.stage }}</td><td class="number">{{ number(detail.quantity) }}</td><td>{{ detail.unit }}</td></tr></tbody></table></div>
        <template v-if="detail.source==='INTERNAL'"><h3>部位入库进度</h3><div class="receipt-detail-grid receipt-detail-progress"><label>应入库<strong>{{ number(detail.source_detail?.required || '0') }} {{ detail.unit }}</strong></label><label>本次之前已入<strong>{{ number(detail.source_detail?.received_before || '0') }} {{ detail.unit }}</strong></label><label>本次之后累计<strong>{{ number(detail.source_detail?.received_after || '0') }} {{ detail.unit }}</strong></label><label>本次对应原料投入<strong>{{ number(detail.source_detail?.input_quantity || '0') }} {{ detail.source_detail?.input_unit }}</strong></label></div></template>
        <p class="receipt-detail-remark">备注：{{ detail.source_detail?.remark || detail.remark || '—' }}</p>
      </template></div><template #footer><ElButton @click="visible=false">关闭</ElButton></template>
    </AppWindowDialog>
  </section>
</template>
