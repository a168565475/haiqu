<script setup lang="ts">
import { computed,onMounted,ref } from 'vue'
import { useRouter } from 'vue-router'
import { AxiosError, isCancel } from 'axios'
import { useIdentityOwnedStorage } from '@/composables/useIdentityOwnedStorage'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { ElMessage } from 'element-plus'
import { fetchAssemblyPreview,submitAssemblyReceipt } from '@/api/finishedReceipts'
import type { AssemblyPayload,AssemblyPreview } from '@/types/finishedReceipts'
import '@/styles/finishedReceipts.scss'
const props = defineProps<{ scheduleProductId?: string | (string | null)[] | null; warehouseEntry?: boolean }>()
const emit = defineEmits<{ closed: []; submitted: [] }>()
const visible = ref(true)
const router = useRouter()
const planId = typeof props.scheduleProductId === 'string' ? props.scheduleProductId : ''
const sourceError=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(planId)?'':'入库来源参数无效，请从装配作业计划的产品行进入成品入库。'
const preview=ref<AssemblyPreview>(),loading=ref(false),saving=ref(false),error=ref('')
const quantity=ref(''),date=ref('')
const pending=ref<{payload:AssemblyPayload;etag:string}|null>(null),pendingKey='assembly-receipt:'+planId
const owned=useIdentityOwnedStorage({storage:'session',key:pendingKey,legacyKeys:[pendingKey]})
const storageBlocked=ref(false)
const pendingQuantity = computed(() => {
 const data = preview.value
 return data?.confirmed_received_total === undefined ? undefined : data.received_total - data.confirmed_received_total
})
function displayQuantity(value: number | undefined) {
 return value === undefined ? '—' : `${value.toLocaleString('zh-CN')} ${preview.value!.unit_name}`
}
function closeWhileIdle(done: () => void) { if (!saving.value) done() }
function viewRecords() {
 visible.value = false
 void router.push(props.warehouseEntry
  ? { name:'finished-goods-inventory', query:{ tab:'pending', schedule_product_id:planId } }
  : { name:'workshop-finished-receipt-records', query:{ schedule_product_id:planId } })
}
let pendingRaw:string|null=null
function checkStorage():boolean {
 if(!owned.isCurrent()){storageBlocked.value=true;error.value='身份尚未核验或已变化，请核验身份后重新打开弹窗。';return false}
 try{if(owned.legacyExists()){storageBlocked.value=true;error.value='发现历史无主待核对记录，已原样隔离保留并暂停新提交。请联系管理员人工核对，不能认领或删除后重试。';return false}return !storageBlocked.value}
 catch{storageBlocked.value=true;error.value='浏览器无法读取待核对记录，已暂停新提交，请联系管理员人工核对。';return false}
}
function consumePending():boolean {
 try{if(pendingRaw===null||!owned.removeIfUnchanged(pendingRaw))throw Error('pending changed');pending.value=null;pendingRaw=null;return true}
 catch{storageBlocked.value=true;error.value='待核对记录已变化或无法更新，已保留记录并暂停提交，请联系管理员人工核对。';return false}
}
const q=computed(()=>Number(quantity.value))
const validQuantity=computed(()=>/^\d+$/.test(quantity.value)&&Number.isSafeInteger(q.value)&&q.value>0)
function message(cause:unknown) { return cause instanceof AxiosError?cause.response?.data?.error?.message||'请求失败，请重试。':'页面操作失败，请重试。' }
async function load() {
 if(sourceError){error.value=sourceError;return}
 if(!checkStorage())return
 loading.value=true;error.value=''
 try {
  owned.assertCurrent()
  const data=await fetchAssemblyPreview(planId);owned.assertCurrent();preview.value=data
  date.value||=data.receipt_date
 }catch(cause){if(isCancel(cause)||!owned.isCurrent())return;preview.value=undefined;error.value=message(cause)}finally{if(owned.isCurrent())loading.value=false}
}
function validate() {
 if(!preview.value)return '请先读取订单额度。'
 if(!validQuantity.value)return '入库数量必须为正整数。'
 if(q.value>preview.value.remaining_receivable)return `剩余可入库${preview.value.remaining_receivable}${preview.value.unit_name}，不能超量。`
 if(!date.value)return '请选择日期。'
 return ''
}
async function submit() {
 if(!checkStorage()||sourceError||saving.value||loading.value||(!preview.value&&!pending.value))return
 error.value=''
 if(!pending.value){
  const validationMessage=validate()
  if(validationMessage){
   if(validQuantity.value&&preview.value&&q.value>preview.value.remaining_receivable){
    ElMessage.warning({message:validationMessage,duration:3000,grouping:true})
   }else error.value=validationMessage
   return
  }
  const value={etag:preview.value!.etag,payload:{request_id:crypto.randomUUID(),schedule_product_id:planId,receipt_date:date.value,received_quantity:q.value}}
  try{if(owned.read()!==null)throw Error('existing pending');const raw=JSON.stringify(value);owned.write(raw);pendingRaw=raw;pending.value=value}catch{storageBlocked.value=true;error.value='浏览器无法保存提交编号或已有待核对记录，请重新打开弹窗核对，暂勿提交。';return}
 }
 saving.value=true
 try{
  owned.assertCurrent()
  if(owned.read()!==pendingRaw){storageBlocked.value=true;error.value='待核对记录已变化，请重新打开弹窗并联系管理员人工核对。';return}
  const result=await submitAssemblyReceipt(pending.value.payload,pending.value.etag)
  owned.assertCurrent()
  if(!consumePending())return
  quantity.value=''
  ElMessage.success(`已提交待入库：${result.receipt_number}`)
  emit('submitted')
  visible.value = false
 }catch(cause){
  if(isCancel(cause)||!owned.isCurrent())return
  const status=cause instanceof AxiosError?cause.response?.status:undefined
  const code=cause instanceof AxiosError?cause.response?.data?.error?.code:undefined
  if(status&&([400,412,428].includes(status)||(status===409&&['CONFLICT','RECEIPT_REQUEST_DELETED','DATABASE_MIGRATION_REQUIRED'].includes(code??'')))){if(!consumePending())return;error.value=message(cause)}
  else error.value=code==='RECEIPT_REQUEST_CONFLICT'?message(cause):'提交结果尚未确认，请点击“核对本次提交”使用原编号核对，不要另建单据。'
 }finally{if(owned.isCurrent())saving.value=false}
}
onMounted(()=>{
 if(sourceError){error.value=sourceError;return}
 if(!checkStorage())return
 try{const raw=owned.read();if(raw!==null){pendingRaw=raw;const value=JSON.parse(raw);if(!value?.payload?.request_id||value.payload.schedule_product_id!==planId||!value.etag)throw Error();pending.value=value;date.value=value.payload.receipt_date;quantity.value=String(value.payload.received_quantity)}}
 catch{storageBlocked.value=true;error.value='原提交记录无法读取，已保留并暂停提交，请联系管理员人工核对，避免重复登记。';return}
 void load()
})
</script>
<template>
 <AppWindowDialog v-model="visible" title="成品入库" :width="1320" class="fg-window"
  :close-on-click-modal="false" :before-close="closeWhileIdle" destroy-on-close @closed="emit('closed')">
  <section class="assembly-receipt-content" v-loading="loading">
   <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon />
   <ElAlert v-if="pending" title="本次提交结果尚未确认，填写内容已锁定。请使用下方“核对本次提交”核对原请求，避免重复入库。" type="warning" :closable="false" show-icon />
   <template v-if="preview">
    <ElAlert v-if="!preview.reporting_basis_ready" title="装配工序或有效工价明细未完整设置，当前可入库为0，请先完善报工依据。" type="warning" :closable="false" show-icon />
    <ElForm :disabled="storageBlocked||!owned.isCurrent()||saving||!!pending" @submit.prevent="submit">
     <div class="fg-table-card">
      <div class="fg-table-scroll">
       <table class="fg-table compact assembly-receipt-table" aria-label="成品入库明细">
        <colgroup><col v-for="(width, index) in [118, 0, 95, 95, 110, 90, 85, 95, 100, 138, 145]"
          :key="index" :style="width ? { width: `${width}px` } : undefined" /></colgroup>
        <thead><tr>
         <th scope="col">生产任务单号</th><th scope="col">产品</th><th scope="col">品号</th><th scope="col">货号</th><th scope="col">规格</th>
         <th scope="col" class="num">订单数量</th><th scope="col" class="num">已入库</th><th scope="col" class="num">待仓库确认</th>
         <th scope="col" class="num">剩余可入库</th><th scope="col">本次入库数量</th><th scope="col">入库日期</th>
        </tr></thead>
        <tbody><tr>
         <td :title="preview.task_number">{{ preview.task_number }}</td>
         <td :title="preview.product_name">{{ preview.product_name }}</td>
         <td :title="preview.product_number">{{ preview.product_number || '—' }}</td>
         <td :title="preview.item_number">{{ preview.item_number || '—' }}</td>
         <td :title="preview.specification">{{ preview.specification || '—' }}</td>
         <td class="num">{{ displayQuantity(preview.order_quantity) }}</td>
         <td class="num">{{ displayQuantity(preview.confirmed_received_total) }}</td>
         <td class="num">{{ displayQuantity(pendingQuantity) }}</td>
         <td class="num">{{ displayQuantity(preview.remaining_receivable) }}</td>
         <td><ElInput v-model="quantity" aria-label="本次入库数量" inputmode="numeric" placeholder="填写数量"><template #suffix>{{ preview.unit_name }}</template></ElInput></td>
         <td><ElDatePicker v-model="date" aria-label="入库日期" type="date" format="YYYY-MM-DD" value-format="YYYY-MM-DD" :clearable="false" placeholder="选择日期" /></td>
        </tr></tbody>
       </table>
      </div>
     </div>
    </ElForm>
   </template>
  </section>
  <template #footer>
   <ElButton v-if="preview" class="assembly-receipt-records" :disabled="saving" @click="viewRecords">入库记录</ElButton>
   <ElButton :disabled="saving" @click="visible=false">关闭</ElButton>
   <ElButton :disabled="storageBlocked||!owned.isCurrent()||!!sourceError||saving||loading" @click="load">刷新</ElButton>
   <ElButton type="primary" :loading="saving" :disabled="storageBlocked||!owned.isCurrent()||!!sourceError||(!preview&&!pending)||loading" @click="submit">{{ pending ? '核对本次提交' : '提交' }}</ElButton>
  </template>
 </AppWindowDialog>
</template>

<style scoped lang="scss">
.assembly-receipt-content { display: grid; gap: 12px; min-height: 50px; }
.fg-table.assembly-receipt-table { min-width: 1180px; }
.assembly-receipt-table td { height: 48px; }
.assembly-receipt-table td :deep(.el-date-editor) { width: 100%; }
.assembly-receipt-records { margin-right: auto; }
</style>
