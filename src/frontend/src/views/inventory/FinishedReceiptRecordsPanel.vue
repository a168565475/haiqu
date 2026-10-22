<script setup lang="ts">
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onMounted,ref } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessageBox } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { vHorizontalOverflow } from '@/directives/horizontalOverflow'
import { confirmAssemblyReceiptRecord, deleteAssemblyReceiptRecord, fetchFinishedRecords,fetchFinishedRecord } from '@/api/finishedReceipts'
import { fetchFinishedGoodsFilterOptions } from '@/api/inventory'
import { useAuthStore } from '@/stores/auth'
import type { FinishedRecord } from '@/types/finishedReceipts'
import type { MaterialReceivingOptions } from '@/types/inventory'
const route=useRoute(),router=useRouter(),auth=useAuthStore(),q=ref(''),warehouse=ref(''),zone=ref(''),source=ref(''),page=ref(1),pageSize=ref(50),total=ref(0)
const rows=ref<FinishedRecord[]>([]),options=ref<MaterialReceivingOptions>({warehouses:[],zones:[]}),loading=ref(false),error=ref(''),detail=ref<FinishedRecord>(),visible=ref(false),detailLoading=ref(false),detailError=ref('')
const confirming=ref<string|null>(null), canConfirm=computed(()=>auth.user?.is_superuser===true||auth.hasPermission('inventory.confirm_finishedgoodsreceipt'))
const deleting=ref<string|null>(null)
const planFilter=ref(String(route.query.schedule_product_id||''));let sequence=0,detailSequence=0
const msg=(e:unknown,fallback='记录读取失败，请重试。')=>e instanceof AxiosError?e.response?.data?.error?.message||fallback:fallback
async function load(){const current=++sequence;loading.value=true;error.value='';try{const result=await fetchFinishedRecords({q:q.value,warehouse_id:warehouse.value||undefined,zone_id:zone.value||undefined,source:source.value,exclude_sample:true,page:page.value,page_size:pageSize.value,schedule_product_id:planFilter.value||undefined,product_line_id:route.query.product_line_id||undefined});if(current!==sequence)return;rows.value=result.items;total.value=result.total}catch(e){if(current===sequence){error.value=msg(e);rows.value=[]}}finally{if(current===sequence)loading.value=false}}
function search(){page.value=1;void load()}
async function show(id:string){const current=++detailSequence;visible.value=true;detail.value=undefined;detailError.value='';detailLoading.value=true;try{const value=await fetchFinishedRecord(id);if(current===detailSequence)detail.value=value}catch(e){if(current===detailSequence)detailError.value=msg(e)}finally{if(current===detailSequence)detailLoading.value=false}}
function clearPlan(){planFilter.value='';void router.replace({query:{tab:'records'}});search()}
async function confirm(row: FinishedRecord) {
 if (confirming.value || deleting.value || row.status !== 'PENDING' || !canConfirm.value) return
 confirming.value=row.id; error.value=''
 try { await confirmAssemblyReceiptRecord(row.id); await load() }
 catch(e) { error.value=msg(e) }
 finally { confirming.value=null }
}
async function remove(row: FinishedRecord) {
 if (confirming.value || deleting.value || row.status !== 'PENDING' || !row.can_delete) return
 deleting.value=row.id
 try {
  await ElMessageBox.confirm(`确定删除待入库单“${row.receipt_number}”？删除后可重新提交入库。`, '删除待入库记录', { type:'warning',confirmButtonText:'删除',cancelButtonText:'取消' })
  if (!row.etag) { await load(); error.value='记录版本缺失，请刷新后重试。'; return }
  await deleteAssemblyReceiptRecord(row.id,row.etag)
  if (detail.value?.id===row.id) { detailSequence++;visible.value=false;detail.value=undefined }
  if (rows.value.length===1 && page.value>1) page.value--
  await load()
 } catch(e) {
  if (e==='cancel' || e==='close') return
  const failure=msg(e,'删除失败，请重试。')
  if (e instanceof AxiosError && [404,409,412,428].includes(e.response?.status||0)) {
   if (detail.value?.id===row.id) { detailSequence++;visible.value=false;detail.value=undefined }
   await load();error.value=error.value?`${failure} ${error.value}`:failure
  } else error.value=failure
 } finally { deleting.value=null }
}
onMounted(()=>{void load();void fetchFinishedGoodsFilterOptions().then(value=>options.value=value).catch(e=>error.value=msg(e))})
</script>
<template>
 <section class="fg-records-panel erp-glass-list">
 <section v-glass-spotlight class="erp-list-filter">
 <slot name="heading"/>
 <div class="fg-filters erp-list-filters"><ElInput v-model="q" clearable placeholder="搜索入库单号、生产单号、品号或品名" @keyup.enter="search" @clear="search"/><ElSelect v-model="warehouse" clearable placeholder="全部仓库" @change="zone='';search()"><ElOption v-for="w in options.warehouses" :key="w.id" :value="w.id" :label="w.warehouse_name"/></ElSelect><ElSelect v-model="zone" clearable placeholder="全部库区" @change="search"><ElOption v-for="z in options.zones.filter(v=>!warehouse||v.warehouse===warehouse)" :key="z.id" :value="z.id" :label="z.zone_name"/></ElSelect><ElSelect v-model="source" clearable placeholder="全部来源" @change="search"><ElOption label="装配入库" value="ASSEMBLY"/><ElOption label="生产入库" value="PRODUCTION_ORDER"/></ElSelect><div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="q=''; warehouse=''; zone=''; source=''; search()">重置</ElButton><ElButton class="erp-button-motion" type="primary" @click="search">应用筛选</ElButton></div><slot name="actions"/></div>
 </section>
 <section class="erp-list-data">
 <div class="fg-toolbar erp-list-toolbar"><slot/><ElButton v-if="planFilter" link @click="clearPlan">查看全部</ElButton></div><ElAlert v-if="error" :title="error" type="error" :closable="false"/>
<div class="fg-records-table" v-loading="loading"><div class="erp-list-table-frame"><div v-horizontal-overflow class="fg-table-scroll erp-list-table-scroll scroll-actions-container"><table class="fg-table erp-list-native-table erp-list-native-table--nowrap"><colgroup><col v-for="(width,i) in [155,105,150,105,120,150,160,80,90,60,90,65,90,105,90,200]" :key="i" :style="{width:width+'px'}"></colgroup><thead><tr><th :class="{ 'scroll-actions-cell': name === '操作' }" v-for="name in ['入库单号','入库来源','生产单号','货号','产品编码','品名','规格','颜色','入库数量','单位','仓库','库区','库位','入库日期','状态','操作']" :key="name">{{name}}</th></tr></thead><tbody><tr v-for="r in rows" :key="r.id"><td :title="r.receipt_number">{{r.receipt_number}}</td><td><span :class="['erp-list-tag',r.source_type==='SAMPLE_INVENTORY'?'erp-list-tag--info':'erp-list-tag--brand']">{{r.source_type_display}}</span></td><td :title="r.task_number_snapshot">{{r.task_number_snapshot||'—'}}</td><td :title="r.item_number_snapshot">{{r.item_number_snapshot||'—'}}</td><td :title="r.product_code_snapshot">{{r.product_code_snapshot||'—'}}</td><td :title="r.product_name_snapshot">{{r.product_name_snapshot}}</td><td :title="r.specification_snapshot">{{r.specification_snapshot||'—'}}</td><td>{{r.actual_color||'—'}}</td><td class="num">{{r.received_quantity}}</td><td>{{r.unit_name}}</td><td>{{r.warehouse_name}}</td><td>{{r.zone_name}}</td><td>{{r.location_number}}</td><td>{{r.receipt_date}}</td><td><span :class="['erp-list-tag',r.status==='PENDING'?'erp-list-tag--warning':'erp-list-tag--success']">{{r.status==='PENDING'?'待入库':'已入库'}}</span></td><td class="scroll-actions-cell"><ElButton link type="primary" @click="show(r.id)">查看</ElButton><ElButton v-if="r.status==='PENDING'&&canConfirm" link type="success" :loading="confirming===r.id" :disabled="Boolean(confirming || deleting)" data-testid="confirm-finished-receipt" @click="confirm(r)">确认入库</ElButton><ElButton v-if="r.status==='PENDING'&&r.can_delete" link type="danger" :loading="deleting===r.id" :disabled="Boolean(confirming || deleting)" data-testid="delete-finished-receipt" @click="remove(r)">删除</ElButton></td></tr></tbody></table><div class="fg-empty" v-if="!loading&&!rows.length">暂无符合条件的入库记录</div></div></div><footer class="fg-pager erp-list-footer"><span>共 {{total}} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20,50,100]" layout="sizes, prev, pager, next" @current-change="load" @size-change="search"/></footer></div>
 </section>
 <AppWindowDialog v-model="visible" title="成品入库 · 来源详情" :width="1180" :height="660" class="fg-window" destroy-on-close><div v-loading="detailLoading"><ElAlert v-if="detailError" :title="detailError" type="error" :closable="false"/><template v-if="detail"><div class="fg-detail-title"><b>{{detail.receipt_number}}</b><span class="fg-tag">{{detail.source_type_display}}</span><span :class="['fg-tag', detail.status==='PENDING'?'warning':'success']">{{detail.status==='PENDING'?'待入库':'已入库'}}</span></div><dl class="fg-detail-fields"><div v-for="([k,v]) in [['生产单号',detail.task_number_snapshot],['订单号',detail.order_number_snapshot],[detail.source_type==='SAMPLE_INVENTORY'?'样品来源单':'装配计划',detail.source_type==='SAMPLE_INVENTORY'?detail.source_document_number:detail.schedule_number],['收货日期',detail.receipt_date],['成品仓 / 库区',detail.warehouse_name+' / '+detail.zone_name],['库位',detail.location_number],['入库人',detail.received_by_name],['供应商',detail.supplier_name],['备注',detail.remark]]" :key="String(k)"><dt>{{k}}</dt><dd>{{v||'—'}}</dd></div></dl><h2 class="fg-detail-heading">成品明细</h2><div class="fg-table-card"><table class="fg-table compact"><thead><tr><th v-for="h in ['货号','产品编码','品名','规格','颜色','数量','单位']" :key="h">{{h}}</th></tr></thead><tbody><tr><td>{{detail.item_number_snapshot||'—'}}</td><td>{{detail.product_code_snapshot||'—'}}</td><td>{{detail.product_name_snapshot}}</td><td :title="detail.specification_snapshot">{{detail.specification_snapshot}}</td><td>{{detail.actual_color}}</td><td>{{detail.received_quantity}}</td><td>{{detail.unit_name}}</td></tr></tbody></table></div><div class="fg-detail-summary"><span>每箱数量：{{detail.quantity_per_box==null?'未计算':`${detail.quantity_per_box} ${detail.unit_name}/箱`}}</span><span>整箱数：{{detail.box_count==null?'未计算':`${detail.box_count} 箱`}}</span><span>尾数：{{detail.tail_quantity==null?'未计算':`${detail.tail_quantity} ${detail.unit_name}`}}</span><span>占用箱位：{{detail.occupied_box_slots==null?'未计算':`${detail.occupied_box_slots} 箱位`}}</span></div><p v-if="detail.received_after!=null" class="fg-helper">本单入库前 {{detail.received_before}} {{detail.unit_name}}，本次 {{detail.received_quantity}} {{detail.unit_name}}，入库后累计 {{detail.received_after}} {{detail.unit_name}}；该订单产品上限 {{detail.maximum_receivable}} {{detail.unit_name}}。</p></template></div><template #footer><ElButton @click="visible=false">关闭</ElButton></template></AppWindowDialog>
 </section>
</template>

<style scoped lang="scss">
.fg-filters > :deep(.el-input) { width: 180px; min-width: 180px; max-width: 410px; flex: 1 1 180px; }
.fg-filters > :deep(.el-select) { width: 160px; flex: 0 0 160px; }
.fg-filters .erp-list-filter-actions { margin-left: 0; }
@media (max-width: 1500px) {
  .fg-filters > :deep(.el-select) { width: 112px; flex-basis: 112px; }
}
.fg-table.erp-list-native-table { min-width: 1740px; }
.fg-records-table { display: flex; flex: 1; flex-direction: column; min-height: 0; }
</style>
