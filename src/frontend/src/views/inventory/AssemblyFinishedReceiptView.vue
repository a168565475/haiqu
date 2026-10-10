<script setup lang="ts">
import { computed,onMounted,ref } from 'vue'
import { useRoute,useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { fetchAssemblyPreview,submitAssemblyReceipt } from '@/api/finishedReceipts'
import { fetchInventoryOptions } from '@/api/inventory'
import type { AssemblyPayload,AssemblyPreview } from '@/types/finishedReceipts'
import type { InventoryOptions } from '@/types/inventory'
import '@/styles/finishedReceipts.scss'
import '@/styles/assemblyFinishedReceipt.scss'
const route=useRoute(),router=useRouter(),planId=String(route.query.schedule_product_id||'')
const preview=ref<AssemblyPreview>(),options=ref<InventoryOptions>(),loading=ref(false),saving=ref(false),error=ref('')
const quantity=ref(''),perBox=ref(''),date=ref(''),color=ref(''),warehouse=ref(''),zone=ref(''),location=ref(''),remark=ref('')
const pending=ref<{payload:AssemblyPayload;etag:string}|null>(null),pendingKey='assembly-receipt:'+planId
const warehouses=computed(()=>options.value?.warehouses.filter(w=>w.warehouse_type==='FINISHED'&&w.status==='ACTIVE')||[])
const zones=computed(()=>options.value?.zones.filter(z=>z.warehouse===warehouse.value&&z.status==='ACTIVE')||[])
const locations=computed(()=>options.value?.locations.filter(l=>l.zone===zone.value&&l.warehouse_id===warehouse.value&&l.status==='ACTIVE')||[])
const selectedLocation=computed(()=>locations.value.find(l=>l.id===location.value))
const locationOptions=computed(()=>zones.value.map(z=>{
 const children=(options.value?.locations||[]).filter(l=>l.zone===z.id&&l.warehouse_id===warehouse.value&&l.status==='ACTIVE').map(l=>({value:l.id,label:l.location_number,remaining:l.remaining_box_slots}))
 return {value:z.id,label:z.zone_name,disabled:!children.length,children}
}))
const locationPath=computed<string[]>({get:()=>zone.value&&location.value?[zone.value,location.value]:[],set:value=>{zone.value=value?.[0]||'';location.value=value?.[1]||''}})
const q=computed(()=>Number(quantity.value)),pack=computed(()=>Number(perBox.value)),validPack=computed(()=>perBox.value!==''&&Number.isSafeInteger(pack.value)&&pack.value>0)
const slots=computed(()=>validPack.value&&q.value>0?Math.ceil(q.value/pack.value):null)
const n=(value:number|null|undefined)=>value==null?'未计算':value.toLocaleString('zh-CN')
const after=computed(()=>(preview.value?.received_total||0)+(Number.isSafeInteger(q.value)&&q.value>0?q.value:0))
const capacityAfter=computed(()=>slots.value==null||selectedLocation.value?.remaining_box_slots==null?null:Math.max(0,selectedLocation.value.remaining_box_slots-slots.value))
const validQuantity=computed(()=>Number.isSafeInteger(q.value)&&q.value>0)
const remainingAfter=computed(()=>Math.max(0,(preview.value?.maximum_receivable||0)-after.value))
const quotaExplanation=computed(()=>preview.value?`订单允许偏差 ${preview.value.tolerance_percent}%，订单上限 ${n(preview.value.order_maximum)} ${preview.value.unit_name}；与全部装配工序最低累计报工 ${n(preview.value.reported_minimum)} ${preview.value.unit_name}取较小值。未报工按0计算，已出库不恢复入库额度。`:'')
function changeWarehouse(){zone.value='';location.value=''}
function resetEntry(){quantity.value='';perBox.value='';remark.value='';error.value=''}
function message(cause:unknown) { return cause instanceof AxiosError?cause.response?.data?.error?.message||'请求失败，请重试。':'页面操作失败，请重试。' }
async function load() {
 loading.value=true;error.value=''
 try {
  const [data,opts]=await Promise.all([fetchAssemblyPreview(planId),fetchInventoryOptions()]);preview.value=data;options.value=opts
  date.value||=data.receipt_date
  // 未确认的提交继续沿用原请求；新入库始终使用订单颜色。
  if(!pending.value)color.value=data.actual_color
  const pendingLocation=opts.locations.find(l=>l.id===location.value)
  warehouse.value||=pendingLocation?.warehouse_id||(warehouses.value.length===1?warehouses.value[0]!.id:'')
  zone.value||=pendingLocation?.zone||''
 }catch(cause){preview.value=undefined;error.value=message(cause)}finally{loading.value=false}
}
function validate() {
 if(!preview.value)return '请先读取订单额度。'
 if(!Number.isSafeInteger(q.value)||q.value<=0)return '入库数量必须为正整数。'
 if(q.value>preview.value.remaining_receivable)return `剩余可入库${preview.value.remaining_receivable}${preview.value.unit_name}，不能超量。`
 if(!date.value||!location.value||!selectedLocation.value||!zones.value.some(z=>z.id===zone.value)||!warehouses.value.some(w=>w.id===warehouse.value))return '请选择收货日期和有效的成品仓、库区／库位。'
 if(perBox.value!==''&&!validPack.value)return '每箱数量必须为正整数，或留空。'
 if(slots.value!=null&&selectedLocation.value.remaining_box_slots!=null&&slots.value>selectedLocation.value.remaining_box_slots)return `库位剩余${selectedLocation.value.remaining_box_slots}箱位，本次需要${slots.value}箱位。`
 return ''
}
async function submit() {
 if(saving.value||loading.value||(!preview.value&&!pending.value))return
 error.value=''
 if(!pending.value){
  const validationMessage=validate()
  if(validationMessage){
   if(validQuantity.value&&preview.value&&q.value>preview.value.remaining_receivable){
    ElMessage.warning({message:validationMessage,duration:3000,grouping:true})
   }else error.value=validationMessage
   return
  }
  const value={etag:preview.value!.etag,payload:{request_id:crypto.randomUUID(),schedule_product_id:planId,location_id:location.value,receipt_date:date.value,received_quantity:q.value,quantity_per_box:validPack.value?pack.value:null,actual_color:color.value.trim(),remark:remark.value.trim()}}
  try{sessionStorage.setItem(pendingKey,JSON.stringify(value));pending.value=value}catch{error.value='浏览器无法保存提交编号，请启用会话存储后再试。';return}
 }
 saving.value=true
 try{
  const result=await submitAssemblyReceipt(pending.value.payload,pending.value.etag)
  pending.value=null;sessionStorage.removeItem(pendingKey);quantity.value='';ElMessage.success(`入库成功：${result.receipt_number}`);await load()
 }catch(cause){
  const status=cause instanceof AxiosError?cause.response?.status:undefined
  const code=cause instanceof AxiosError?cause.response?.data?.error?.code:undefined
  if(status&&([400,412,428].includes(status)||(status===409&&code==='CONFLICT'))){pending.value=null;sessionStorage.removeItem(pendingKey);error.value=message(cause)}
  else error.value=code==='RECEIPT_REQUEST_CONFLICT'?message(cause):'提交结果尚未确认，请点击“核对本次提交”使用原编号核对，不要另建单据。'
 }finally{saving.value=false}
}
onMounted(()=>{
 try{const raw=sessionStorage.getItem(pendingKey);if(raw){const value=JSON.parse(raw);if(!value?.payload?.request_id||value.payload.schedule_product_id!==planId||!value.etag)throw Error();pending.value=value;const p=value.payload;location.value=p.location_id;date.value=p.receipt_date;color.value=p.actual_color;quantity.value=String(p.received_quantity);perBox.value=p.quantity_per_box==null?'':String(p.quantity_per_box);remark.value=p.remark}}
 catch{error.value='原提交记录无法读取，请先到入库记录核对，避免重复登记。';return}
 void load()
})
</script>
<template>
 <section class="finished-receipt-page assembly-receipt-page" v-loading="loading">
  <header class="fg-heading"><h1>成品入库</h1><span class="fg-tag">装配来源</span><ElButton @click="router.push({name:'finished-goods-inventory',query:{tab:'records',schedule_product_id:planId}})">入库记录</ElButton></header>
  <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon />
  <ElAlert v-if="pending" title="本次提交结果尚未确认，填写内容已锁定。请使用下方“核对本次提交”核对原请求，避免重复入库。" type="warning" :closable="false" show-icon />
  <template v-if="preview">
   <section class="ar-order-strip" aria-label="订单信息和入库额度">
    <div class="ar-info-grid ar-identities">
     <div class="ar-info-cell"><span>生产单号</span><b :title="preview.task_number">{{preview.task_number}}</b></div>
     <div class="ar-info-cell"><span>订单号</span><b :title="preview.order_number">{{preview.order_number}}</b></div>
     <div class="ar-info-cell"><span>装配计划</span><b :title="preview.schedule_number">{{preview.schedule_number}}</b></div>
     <div class="ar-info-cell"><span>品号</span><b :title="preview.product_number">{{preview.product_number}}</b></div>
     <div class="ar-info-cell"><span>入库人</span><b :title="preview.actor_name">{{preview.actor_name}}</b></div>
    </div>
    <div class="ar-info-grid ar-product">
     <div class="ar-info-cell"><span>产品名称</span><b :title="preview.product_name">{{preview.product_name}}</b></div>
     <div class="ar-info-cell"><span>规格</span><b :title="preview.specification">{{preview.specification||'—'}}</b></div>
     <div class="ar-info-cell"><span>订单颜色</span><b :title="color||'订单未填写颜色，可直接入库'">{{color||'未填写（可留空）'}}</b></div>
     <div class="ar-info-cell"><span>货号</span><b :title="preview.item_number">{{preview.item_number||'—'}}</b></div>
     <div class="ar-info-cell"><span>入库额度</span><ElTooltip :content="quotaExplanation" placement="bottom" popper-class="ar-popper"><span class="ar-info-value ar-quota-rule" tabindex="0">额度说明</span></ElTooltip></div>
    </div>
    <div class="ar-info-grid ar-quota">
     <div class="ar-info-cell"><span>订单量</span><span class="ar-info-value"><b>{{n(preview.order_quantity)}}</b> {{preview.unit_name}}</span></div>
     <div class="ar-info-cell"><span>装配最低报工</span><span class="ar-info-value"><b>{{n(preview.reported_minimum)}}</b> {{preview.unit_name}}</span></div>
     <div class="ar-info-cell"><span>累计上限</span><span class="ar-info-value"><b>{{n(preview.maximum_receivable)}}</b> {{preview.unit_name}}</span></div>
     <div class="ar-info-cell"><span>已入库</span><span class="ar-info-value"><b>{{n(preview.received_total)}}</b> {{preview.unit_name}}</span></div>
     <div class="ar-info-cell ar-emphasis"><span>剩余可入</span><span class="ar-info-value"><b>{{n(preview.remaining_receivable)}}</b> {{preview.unit_name}}</span></div>
    </div>
   </section>
   <section class="ar-workspace">
    <ElAlert v-if="!preview.reporting_basis_ready" title="装配工序或有效工价明细未完整设置，当前可入库为0，请先完善报工依据。" type="warning" :closable="false" show-icon />
    <div class="ar-workspace-heading"><h2>本次入库</h2><span>按仓库实际收到的数量填写</span></div>
    <ElForm label-position="top" :disabled="saving||!!pending" class="ar-form" @submit.prevent="submit">
     <div class="ar-fields">
      <ElFormItem label="入库数量" required><ElInput v-model="quantity" aria-label="本次入库数量" inputmode="numeric" placeholder="填写本次实收数量"><template #suffix>{{preview.unit_name}}</template></ElInput><p class="ar-help">本次最多可入 <b>{{n(preview.remaining_receivable)}}</b> {{preview.unit_name}}</p></ElFormItem>
      <ElFormItem label="收货日期" required><ElDatePicker v-model="date" aria-label="收货日期" type="date" format="YYYY-MM-DD" value-format="YYYY-MM-DD" :clearable="false" placeholder="选择日期" popper-class="ar-popper" /></ElFormItem>
      <ElFormItem label="成品仓" required><ElSelect v-model="warehouse" aria-label="成品仓" placeholder="选择成品仓" popper-class="ar-popper" @change="changeWarehouse"><ElOption v-for="w in warehouses" :key="w.id" :value="w.id" :label="`${w.warehouse_number} · ${w.warehouse_name}`" /></ElSelect></ElFormItem>
      <ElFormItem label="库区 / 库位" required><ElCascader v-model="locationPath" aria-label="库区 / 库位" :options="locationOptions" :props="{expandTrigger:'hover'}" :disabled="saving||!!pending||!warehouse" filterable clearable placeholder="选择库区，再选择库位" popper-class="ar-popper"><template #default="{node,data}"><span>{{data.label}}</span><span v-if="node.isLeaf" class="ar-location-capacity">{{data.remaining==null?'未设容量':'剩余 '+n(data.remaining)+' 箱位'}}</span></template></ElCascader><p class="ar-help">先选库区，再选库位<span v-if="selectedLocation"> · {{selectedLocation.remaining_box_slots==null?'未设容量':'当前剩余 '+n(selectedLocation.remaining_box_slots)+' 箱位'}}</span></p></ElFormItem>
     </div>
     <div class="ar-result"><span>本次入库 <b>{{validQuantity?n(q):'—'}}</b> {{preview.unit_name}}</span><i></i><span>入库后累计 <b>{{n(after)}}</b> {{preview.unit_name}}</span><i></i><span>入库后剩余额度 <b>{{n(remainingAfter)}}</b> {{preview.unit_name}}</span></div>
     <section class="ar-packing"><div class="ar-subheading"><h3>包装信息</h3><span>选填，填写后自动计算箱数与占用箱位</span></div><div class="ar-packing-fields">
      <ElFormItem label="每箱数量"><ElInput v-model="perBox" inputmode="numeric" aria-label="每箱数量" placeholder="选填"><template #suffix>{{preview.unit_name}} / 箱</template></ElInput></ElFormItem>
      <div class="ar-stat"><span>整箱数</span><b>{{validPack&&validQuantity?n(Math.floor(q/pack))+' 箱':'未计算'}}</b></div>
      <div class="ar-stat"><span>尾数</span><b>{{validPack&&validQuantity?n(q%pack)+' '+preview.unit_name:'未计算'}}</b></div>
      <div class="ar-stat"><span>本次占用箱位</span><b>{{slots==null?'未计算':n(slots)+' 箱位'}}</b></div>
      <div class="ar-stat"><span>入库后剩余箱位</span><b>{{capacityAfter==null?'未计算':n(capacityAfter)+' 箱位'}}</b></div>
     </div><p class="ar-help">有尾数时另占1个箱位；每箱数量留空时不计算箱位。</p></section>
     <section class="ar-remark"><div class="ar-subheading"><h3>入库备注</h3><span>选填</span></div><ElInput v-model="remark" type="textarea" :rows="3" maxlength="3000" show-word-limit aria-label="入库备注" placeholder="填写本次收货、包装或存放说明" /></section>
    </ElForm>
   </section>
  </template>
  <div v-else-if="!loading" class="fg-empty">未读取到订单入库信息，请刷新重试。</div>
  <footer class="fg-form-footer"><div>本次入库 <strong>{{validQuantity?n(q):'0'}}</strong> {{preview?.unit_name}}<p class="fg-muted">确认入库后增加成品库存，已领用的半成品不重复扣减。</p></div><ElButton @click="router.push({name:'workshop-assembly-plan'})">返回</ElButton><ElButton :disabled="saving||loading||!!pending" @click="resetEntry">重填</ElButton><ElButton :disabled="saving||loading" @click="load">刷新</ElButton><ElButton type="primary" :loading="saving" :disabled="(!preview&&!pending)||loading" @click="submit">{{pending?'核对本次提交':'确认入库'}}</ElButton></footer>
 </section>
</template>
