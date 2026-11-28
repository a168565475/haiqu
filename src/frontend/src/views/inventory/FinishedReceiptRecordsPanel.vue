<script setup lang="ts">
import { compactDecimal } from '@/utils/compactDecimal'
import { vGlassSpotlight } from '@/directives/glassSpotlight'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessageBox } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { vHorizontalOverflow } from '@/directives/horizontalOverflow'
import { confirmAssemblyReceiptRecord, deleteAssemblyReceiptRecord, fetchFinishedRecords,fetchFinishedRecord } from '@/api/finishedReceipts'
import { fetchFinishedGoodsFilterOptions, fetchInventoryOptions } from '@/api/inventory'
import { useAuthStore } from '@/stores/auth'
import type { FinishedRecord } from '@/types/finishedReceipts'
import type { InventoryOptions, MaterialReceivingOptions } from '@/types/inventory'
import '@/styles/finishedReceipts.scss'

const props = defineProps<{ readOnly?: boolean; warehouseStatus?: 'CONFIRMED' | 'PENDING' }>()
const route=useRoute(),router=useRouter(),auth=useAuthStore(),q=ref(String(route.query.q || '')),warehouse=ref(String(route.query.warehouse_id || '')),zone=ref(String(route.query.zone_id || '')),source=ref(''),page=ref(1),pageSize=ref(50),total=ref(0)
const rows=ref<FinishedRecord[]>([]),options=ref<MaterialReceivingOptions>({warehouses:[],zones:[]}),loading=ref(false),error=ref(''),detail=ref<FinishedRecord>(),visible=ref(false),detailLoading=ref(false),detailError=ref('')
const detailSourceNumber = computed(() => detail.value?.source_type === 'SAMPLE_INVENTORY'
  ? detail.value.source_document_number : detail.value?.task_number_snapshot)
const isReadOnly = computed(() => props.readOnly || props.warehouseStatus === 'CONFIRMED')
const confirming=ref<string|null>(null), canConfirm=computed(()=>!isReadOnly.value && (auth.user?.is_superuser===true||auth.hasPermission('inventory.confirm_finishedgoodsreceipt')))
const placementVisible = ref(false)
const placementTarget = ref<FinishedRecord>()
const placementOptions = ref<InventoryOptions>()
const placementLoading = ref(false), placementError = ref('')
const placement = reactive({ warehouseId: '', zoneId: '', locationId: '', perBox: '' })
const warehousesForPlacement = computed(() => placementOptions.value?.warehouses.filter(item =>
 item.warehouse_type === 'FINISHED' && item.status === 'ACTIVE') || [])
const zonesForPlacement = computed(() => placementOptions.value?.zones.filter(item =>
 item.status === 'ACTIVE' && item.warehouse === placement.warehouseId) || [])
const locationsForPlacement = computed(() => placementOptions.value?.locations.filter(item =>
 item.status === 'ACTIVE' && item.warehouse_id === placement.warehouseId && item.zone === placement.zoneId) || [])
const selectedPlacement = computed(() => locationsForPlacement.value.find(item => item.id === placement.locationId))
const deleting=ref<string|null>(null)
const planFilter=ref(String(route.query.schedule_product_id||''));let sequence=0,detailSequence=0
const msg=(e:unknown,fallback='记录读取失败，请重试。')=>e instanceof AxiosError?e.response?.data?.error?.message||fallback:fallback
async function load(){const current=++sequence;loading.value=true;error.value='';try{const result=await fetchFinishedRecords({
  q:q.value, warehouse_id:warehouse.value||undefined, zone_id:zone.value||undefined,
  source:props.readOnly?'ASSEMBLY':source.value, exclude_sample:true,
  status:props.warehouseStatus, warehouse_history:props.warehouseStatus==='CONFIRMED'||undefined,
  page:page.value, page_size:pageSize.value, schedule_product_id:planFilter.value||undefined,
  product_line_id:route.query.product_line_id||undefined, production_task_id:route.query.production_task_id||undefined,
});if(current!==sequence)return;rows.value=result.items;total.value=result.total}catch(e){if(current===sequence){error.value=msg(e);rows.value=[]}}finally{if(current===sequence)loading.value=false}}
function search(){page.value=1;void load()}
async function show(id:string){const current=++detailSequence;visible.value=true;detail.value=undefined;detailError.value='';detailLoading.value=true;try{const value=await fetchFinishedRecord(id);if(current===detailSequence)detail.value=value}catch(e){if(current===detailSequence)detailError.value=msg(e)}finally{if(current===detailSequence)detailLoading.value=false}}
async function clearPlan(){planFilter.value='';await router.replace({query:props.warehouseStatus==='PENDING'?{tab:'pending'}:{}});search()}
async function openPlacement(row: FinishedRecord) {
 if (confirming.value || deleting.value || row.status !== 'PENDING' || row.source_type !== 'ASSEMBLY' || !canConfirm.value) return
 placementTarget.value = row
 placementOptions.value = undefined
 placementError.value = ''
 placementVisible.value = true
 placementLoading.value = true
 Object.assign(placement, { warehouseId: row.warehouse_id || '', zoneId: row.zone_id || '',
  locationId: row.location_id || '', perBox: row.quantity_per_box == null ? '' : String(row.quantity_per_box) })
 try {
  const choices = await fetchInventoryOptions()
  if (placementTarget.value === row) placementOptions.value = choices
 } catch (e) { if (placementTarget.value === row) placementError.value = msg(e, '成品库位读取失败。') }
 finally { if (placementTarget.value === row) placementLoading.value = false }
}
async function confirmPlacement() {
 const row = placementTarget.value
 if (!row || confirming.value || !canConfirm.value || !selectedPlacement.value) return
 if (!row.etag) { placementError.value = '记录版本缺失，请刷新后重试。'; return }
 const boxQuantity = placement.perBox === '' ? null : Number(placement.perBox)
 if (boxQuantity !== null && (!/^\d+$/.test(placement.perBox) || !Number.isSafeInteger(boxQuantity) || boxQuantity <= 0)) {
  placementError.value = '每箱数量必须为正整数，或留空。'; return
 }
 confirming.value = row.id; placementError.value = ''
 try {
  await confirmAssemblyReceiptRecord(row.id, { location_id: placement.locationId, quantity_per_box: boxQuantity }, row.etag)
  placementVisible.value = false
  await load()
 } catch (e) { placementError.value = msg(e, '确认入库失败，请重试。') }
 finally { confirming.value=null }
}
async function remove(row: FinishedRecord) {
 if (isReadOnly.value || confirming.value || deleting.value || row.status !== 'PENDING' || !row.can_delete) return
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
onMounted(()=>{
 void load()
 if (!props.readOnly) void fetchFinishedGoodsFilterOptions().then(value=>options.value=value).catch(e=>error.value=msg(e))
})
defineExpose({ load })
</script>
<template>
 <section class="fg-records-panel erp-glass-list">
 <section v-glass-spotlight class="erp-list-filter">
 <slot name="heading"><header class="fg-heading erp-list-heading"><h1>成品入库记录</h1></header></slot>
 <div class="fg-filters erp-list-filters">
  <ElInput v-model="q" clearable placeholder="搜索入库单号、生产单号、品号或品名" @keyup.enter="search" @clear="search"/>
  <template v-if="!readOnly">
   <ElSelect v-model="warehouse" clearable placeholder="全部仓库" @change="zone='';search()"><ElOption v-for="w in options.warehouses" :key="w.id" :value="w.id" :label="w.warehouse_name"/></ElSelect>
   <ElSelect v-model="zone" clearable placeholder="全部库区" @change="search"><ElOption v-for="z in options.zones.filter(v=>!warehouse||v.warehouse===warehouse)" :key="z.id" :value="z.id" :label="z.zone_name"/></ElSelect>
   <ElSelect v-model="source" clearable placeholder="全部来源" @change="search"><ElOption label="装配入库" value="ASSEMBLY"/><ElOption label="生产入库" value="PRODUCTION_ORDER"/></ElSelect>
  </template>
  <div class="erp-list-filter-actions"><ElButton class="erp-button-motion" @click="q=''; warehouse=''; zone=''; source=''; search()">重置</ElButton><ElButton class="erp-button-motion" type="primary" @click="search">应用筛选</ElButton></div><slot name="actions"/>
 </div>
 </section>
 <section class="erp-list-data">
 <div v-if="$slots.default || planFilter" class="fg-toolbar erp-list-toolbar"><slot/><ElButton v-if="planFilter" link @click="clearPlan">查看全部</ElButton></div><ElAlert v-if="error" :title="error" type="error" :closable="false"/>
<div class="fg-records-table" v-loading="loading"><div class="erp-list-table-frame"><div v-horizontal-overflow class="fg-table-scroll erp-list-table-scroll scroll-actions-container"><table class="fg-table erp-list-native-table erp-list-native-table--nowrap"><colgroup><col v-for="(width,i) in [150,155,105,105,120,150,160,80,90,60,90,65,90,105,90,160]" :key="i" :style="{width:width+'px'}"></colgroup><thead><tr><th :class="{ 'scroll-actions-cell': name === '操作' }" v-for="name in ['生产任务单号','入库单号','入库来源','货号','产品编码','品名','规格','颜色','入库数量','单位','仓库','库区','库位','入库日期','状态','操作']" :key="name">{{name}}</th></tr></thead><tbody><tr v-for="r in rows" :key="r.id"><td :title="r.task_number_snapshot"><strong>{{r.task_number_snapshot||'—'}}</strong></td><td :title="r.receipt_number">{{r.receipt_number}}</td><td><span :class="['erp-list-tag',r.source_type==='SAMPLE_INVENTORY'?'erp-list-tag--info':'erp-list-tag--brand']">{{r.source_type_display}}</span></td><td :title="r.item_number_snapshot">{{r.item_number_snapshot||'—'}}</td><td :title="r.product_code_snapshot">{{r.product_code_snapshot||'—'}}</td><td :title="r.product_name_snapshot">{{r.product_name_snapshot}}</td><td :title="r.specification_snapshot">{{r.specification_snapshot||'—'}}</td><td>{{r.actual_color||'—'}}</td><td class="num">{{ compactDecimal(r.received_quantity) }}</td><td>{{r.unit_name}}</td><td>{{r.warehouse_name}}</td><td>{{r.zone_name}}</td><td>{{ r.location_number || (r.status === 'PENDING' ? '待分配' : '—') }}</td><td>{{r.receipt_date}}</td><td><span :class="['erp-list-tag',r.status==='PENDING'?'erp-list-tag--warning':'erp-list-tag--success']">{{r.status==='PENDING'?'待入库':'已入库'}}</span></td><td class="scroll-actions-cell"><ElButton link type="primary" @click="show(r.id)">查看</ElButton><ElButton v-if="r.status==='PENDING'&&r.source_type==='ASSEMBLY'&&canConfirm" link type="success" :loading="confirming===r.id" :disabled="Boolean(confirming || deleting)" data-testid="confirm-finished-receipt" @click="openPlacement(r)">确认入库</ElButton><ElButton v-if="!isReadOnly&&r.status==='PENDING'&&r.can_delete" link type="danger" :loading="deleting===r.id" :disabled="Boolean(confirming || deleting)" data-testid="delete-finished-receipt" @click="remove(r)">删除</ElButton></td></tr></tbody></table><div class="fg-empty" v-if="!loading&&!rows.length">暂无符合条件的入库记录</div></div></div><footer class="fg-pager erp-list-footer"><span>共 {{total}} 条</span><ElPagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20,50,100]" layout="sizes, prev, pager, next" @current-change="load" @size-change="search"/></footer></div>
 </section>
 <AppWindowDialog v-model="visible" title="成品入库 · 来源详情" :width="1180" :height="660" class="fg-window" destroy-on-close><div v-loading="detailLoading"><ElAlert v-if="detailError" :title="detailError" type="error" :closable="false"/><template v-if="detail"><div class="fg-detail-title"><b>{{detailSourceNumber || detail.receipt_number}}</b><span class="fg-tag">{{detail.source_type_display}}</span><span :class="['fg-tag', detail.status==='PENDING'?'warning':'success']">{{detail.status==='PENDING'?'待入库':'已入库'}}</span></div><dl class="fg-detail-fields"><div v-for="([k,v]) in [[detailSourceNumber ? '入库单号' : '生产任务单号',detailSourceNumber ? detail.receipt_number : ''],['订单号',detail.order_number_snapshot],[detail.source_type==='SAMPLE_INVENTORY'?'样品来源单':'装配计划',detail.source_type==='SAMPLE_INVENTORY'?detail.source_document_number:detail.schedule_number],['收货日期',detail.receipt_date],['成品仓 / 库区',[detail.warehouse_name, detail.zone_name].filter(Boolean).join(' / ')],['库位',detail.location_number || (detail.status === 'PENDING' ? '待分配' : '')],['入库人',detail.received_by_name],['供应商',detail.supplier_name],['备注',detail.remark]]" :key="String(k)"><dt>{{k}}</dt><dd>{{v||'—'}}</dd></div></dl><h2 class="fg-detail-heading">成品明细</h2><div class="fg-table-card"><table class="fg-table compact"><thead><tr><th v-for="h in ['货号','产品编码','品名','规格','颜色','数量','单位']" :key="h">{{h}}</th></tr></thead><tbody><tr><td>{{detail.item_number_snapshot||'—'}}</td><td>{{detail.product_code_snapshot||'—'}}</td><td>{{detail.product_name_snapshot}}</td><td :title="detail.specification_snapshot">{{detail.specification_snapshot}}</td><td>{{detail.actual_color}}</td><td>{{ compactDecimal(detail.received_quantity) }}</td><td>{{detail.unit_name}}</td></tr></tbody></table></div><div class="fg-detail-summary"><span>每箱数量：{{detail.quantity_per_box==null?'未计算':`${detail.quantity_per_box} ${detail.unit_name}/箱`}}</span><span>整箱数：{{detail.box_count==null?'未计算':`${detail.box_count} 箱`}}</span><span>尾数：{{detail.tail_quantity==null?'未计算':`${detail.tail_quantity} ${detail.unit_name}`}}</span><span>占用箱位：{{detail.occupied_box_slots==null?'未计算':`${detail.occupied_box_slots} 箱位`}}</span></div><p v-if="detail.received_after!=null" class="fg-helper">本单入库前 {{detail.received_before}} {{detail.unit_name}}，本次 {{ compactDecimal(detail.received_quantity) }} {{detail.unit_name}}，入库后累计 {{detail.received_after}} {{detail.unit_name}}；该订单产品上限 {{detail.maximum_receivable}} {{detail.unit_name}}。</p></template></div><template #footer><ElButton @click="visible=false">关闭</ElButton></template></AppWindowDialog>
 <AppWindowDialog v-model="placementVisible" title="确认成品入库" :width="680" :height="450" destroy-on-close
   :close-on-click-modal="!confirming" :close-on-press-escape="!confirming">
   <div v-if="placementTarget" v-loading="placementLoading" class="fg-placement">
     <dl class="fg-placement-facts">
       <div><dt>生产任务单号</dt><dd>{{ placementTarget.task_number_snapshot }}</dd></div>
       <div><dt>产品</dt><dd>{{ placementTarget.product_name_snapshot }}</dd></div>
       <div><dt>本次数量</dt><dd>{{ compactDecimal(placementTarget.received_quantity) }} {{ placementTarget.unit_name }}</dd></div>
       <div><dt>日期</dt><dd>{{ placementTarget.receipt_date }}</dd></div>
     </dl>
     <ElAlert v-if="placementError" :title="placementError" type="error" :closable="false" />
     <ElForm label-position="top" :disabled="Boolean(confirming)">
       <div class="fg-placement-controls">
         <ElFormItem label="成品仓" required>
           <ElSelect v-model="placement.warehouseId" aria-label="成品仓" placeholder="选择成品仓" @change="placement.zoneId = ''; placement.locationId = ''">
             <ElOption v-for="item in warehousesForPlacement" :key="item.id" :label="item.warehouse_name" :value="item.id" />
           </ElSelect>
         </ElFormItem>
         <ElFormItem label="库区" required>
           <ElSelect v-model="placement.zoneId" aria-label="库区" placeholder="选择库区" :disabled="!placement.warehouseId" @change="placement.locationId = ''">
             <ElOption v-for="item in zonesForPlacement" :key="item.id" :label="item.zone_name" :value="item.id" />
           </ElSelect>
         </ElFormItem>
         <ElFormItem label="库位" required>
           <ElSelect v-model="placement.locationId" aria-label="库位" placeholder="选择库位" :disabled="!placement.zoneId" filterable>
             <ElOption v-for="item in locationsForPlacement" :key="item.id" :label="item.location_number" :value="item.id" />
           </ElSelect>
         </ElFormItem>
         <ElFormItem label="每箱数量（选填）">
           <ElInput v-model="placement.perBox" aria-label="每箱数量" inputmode="numeric" />
         </ElFormItem>
       </div>
       <p v-if="selectedPlacement?.remaining_box_slots != null" class="fg-helper">该库位剩余 {{ selectedPlacement.remaining_box_slots }} 箱位。</p>
     </ElForm>
   </div>
   <template #footer>
     <ElButton :disabled="Boolean(confirming)" @click="placementVisible = false">取消</ElButton>
     <ElButton type="primary" :loading="Boolean(confirming)" :disabled="!selectedPlacement || placementLoading" @click="confirmPlacement">确认入库</ElButton>
   </template>
 </AppWindowDialog>
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
.fg-table .scroll-actions-cell { padding: 0 10px; }
.fg-table .scroll-actions-cell :deep(.el-button.is-link) { padding: 0; font-size: 12px; }
.fg-table .scroll-actions-cell :deep(.el-button + .el-button) { margin-left: 8px; }
.fg-records-table { display: flex; flex: 1; flex-direction: column; min-height: 0; }
.fg-placement { padding: 16px; }
.fg-placement-facts, .fg-placement-controls { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 20px; }
.fg-placement-facts { margin: 0 0 18px; }
.fg-placement-facts dt { color: var(--erp-color-text-secondary); }
.fg-placement-facts dd { margin: 4px 0 0; overflow-wrap: anywhere; font-weight: 600; }
.fg-placement .el-alert { margin-bottom: 12px; }
</style>
