<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { AxiosError } from 'axios'
import { fetchInquiryHandlingSettings, saveInquiryHandlingSettings, type InquiryHandlingSettings } from '@/api/inquiryHandlingSettings'
import { useAuthStore } from '@/stores/auth'
import { handlingStageLabel, handlingTargetLabel } from '@/views/inquiries/inquiryWorktime'

const router=useRouter(), auth=useAuthStore()
const loading=ref(false), saving=ref(false), error=ref(''), etag=ref('')
const settings=ref<InquiryHandlingSettings | null>(null)
const canEdit=computed(()=>auth.hasPermission('workflow.manage_sla_policy'))
const stages=['ASSIGNMENT','FIRST_RESPONSE','REQUIREMENT_CONFIRMATION','QUOTE_CREATION','QUOTE_DELIVERY','CUSTOMER_FOLLOW_UP','POST_ACCEPTANCE','SAMPLE_FOLLOW_UP']
const notes=['提交后未分配时开始，与首次回复同时计时','提交询盘后开始，转交不重置','首次回复完成后开始','确认需求后开始','创建报价后开始，正式发送后结束','每次实际跟进完成后开始下一轮','接受报价后，提交样品申请或创建订单','提交样品后持续跟进，移交订单后结束']
const times=reactive({morningStart:'',morningEnd:'',afternoonStart:'',afternoonEnd:''})
function timeText(value:number) { return `${String(Math.floor(value/60)).padStart(2,'0')}:${String(value%60).padStart(2,'0')}` }
function minutes(value:string) { if(!/^\d{2}:\d{2}$/.test(value))return NaN;const [h,m]=value.split(':').map(Number);return h!*60+m! }
function errorText(value:unknown) {
  if(value instanceof AxiosError){
    if(value.response?.status===412)return '规则已被其他人修改，请重新加载后再保存。'
    if(value.response?.status===403)return '当前账号没有查看或修改询盘时限规则的权限。'
    const data=value.response?.data;return data?.error?.message || data?.detail || '操作失败，请检查输入或稍后重试。'
  }
  return value instanceof Error?value.message:'操作失败，请稍后重试。'
}
async function load() {
  loading.value=true;error.value=''
  try{
    const result=await fetchInquiryHandlingSettings();settings.value=result.data;etag.value=result.etag
    const [morning,afternoon]=result.data.work_calendar.periods
    if(!morning||!afternoon)throw new Error('工作日历不完整，请联系管理员。')
    Object.assign(times,{morningStart:timeText(morning[0]),morningEnd:timeText(morning[1]),afternoonStart:timeText(afternoon[0]),afternoonEnd:timeText(afternoon[1])})
  }catch(value){settings.value=null;error.value=errorText(value)}finally{loading.value=false}
}
async function save() {
  if(!settings.value||!canEdit.value||saving.value)return
  error.value=''
  const periods:[[number,number],[number,number]]=[[minutes(times.morningStart),minutes(times.morningEnd)],[minutes(times.afternoonStart),minutes(times.afternoonEnd)]]
  if(periods.some(([start,end])=>!Number.isFinite(start)||!Number.isFinite(end)||start>=end)||periods[0][1]>periods[1][0]){error.value='请填写完整且不重叠的上午、下午工作时段。';return}
  if(stages.some(stage=>!Number.isInteger(settings.value!.stage_minutes[stage])||settings.value!.stage_minutes[stage]!<1)){error.value='八个环节的时长均须填写正整数分钟。';return}
  if(settings.value.stage_minutes.ASSIGNMENT!>settings.value.stage_minutes.FIRST_RESPONSE!){error.value='分配负责人时限不能超过首次回复时限。';return}
  const anchor=Date.parse(`${settings.value.work_calendar.rest_saturday}T00:00:00+08:00`)
  if(!Number.isFinite(anchor)||new Date(anchor+8*3600000).getUTCDay()!==6){error.value='请选择一个实际休息的星期六作为大小周基准。';return}
  saving.value=true
  try{
    const payload={...settings.value,work_calendar:{...settings.value.work_calendar,periods}}
    const result=await saveInquiryHandlingSettings(payload,etag.value);settings.value=result.data;etag.value=result.etag
    ElMessage.success('规则已保存，之后新开始的环节使用新规则。')
  }catch(value){error.value=errorText(value)}finally{saving.value=false}
}
onMounted(load)
</script>

<template>
  <section class="inquiry-settings system-settings-theme" v-loading="loading">
    <header><div><el-button link @click="router.push({name:'reference-data-settings'})">返回系统设置</el-button><h1>询盘处理时限</h1><p>设置各环节工作时长及大小周日历</p></div><div><el-button :disabled="loading||saving" @click="load">重新加载</el-button><el-button type="primary" :disabled="!settings||!canEdit||loading" :loading="saving" @click="save">保存规则</el-button></div></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-alert title="新规则仅用于之后新开始的环节" description="正在计时和历史记录保留原规则、原截止时间；保存操作会记录修改前后内容。" type="info" :closable="false" show-icon />
    <div v-if="settings" class="settings-columns">
      <el-card shadow="never"><template #header><b>各环节处理时长</b><span class="unit-note">按工作分钟填写</span></template>
        <el-table :data="stages.map((stage,index)=>({stage,note:notes[index]}))">
          <el-table-column label="环节" width="162"><template #default="{row}">{{ handlingStageLabel(row.stage) }}</template></el-table-column>
          <el-table-column label="工作分钟" width="215"><template #default="{row}"><el-input-number v-model="settings.stage_minutes[row.stage]" :aria-label="handlingStageLabel(row.stage)" :min="1" :max="527040" :precision="0" :disabled="!canEdit||saving"/><small>{{ handlingTargetLabel(settings.stage_minutes[row.stage] || 0) }}</small></template></el-table-column>
          <el-table-column prop="note" label="计时规则" min-width="220" />
        </el-table>
      </el-card>
      <el-card shadow="never"><template #header><b>工作日历</b></template><el-form label-position="top" :disabled="!canEdit||saving">
        <p>北京时间 · 大小周交替 · 周日固定休息</p>
        <el-form-item label="上午工作时段"><div class="time-range"><input v-model="times.morningStart" type="time" aria-label="上午开始" :disabled="!canEdit||saving"/><span>至</span><input v-model="times.morningEnd" type="time" aria-label="上午结束" :disabled="!canEdit||saving"/></div></el-form-item>
        <el-form-item label="下午工作时段"><div class="time-range"><input v-model="times.afternoonStart" type="time" aria-label="下午开始" :disabled="!canEdit||saving"/><span>至</span><input v-model="times.afternoonEnd" type="time" aria-label="下午结束" :disabled="!canEdit||saving"/></div></el-form-item>
        <el-form-item label="休息周六基准"><el-date-picker v-model="settings.work_calendar.rest_saturday" type="date" value-format="YYYY-MM-DD" aria-label="休息周六基准" :clearable="false" /></el-form-item>
        <p>选择一个休息的周六，系统按隔周周六休息计算。两个工作时段之间为午休，下班及休息日不累计处理时间。</p>
        <p>报价后跟进、样品进度跟进按左侧分钟数逐轮计算。</p>
      </el-form></el-card>
    </div>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
.inquiry-settings { color:token.$crm-text-primary; header{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;} h1{margin:12px 0 6px;font-size:28px;} p{color:token.$crm-text-muted;line-height:1.7;} .el-alert{margin-bottom:16px;} .settings-columns{display:grid;grid-template-columns:minmax(690px,1.6fr) minmax(360px,1fr);gap:20px;} .unit-note{float:right;font-size:12px;color:token.$crm-text-muted;} small{display:block;font-size:12px;color:token.$crm-text-muted;margin-top:4px;} .time-range{display:flex;align-items:center;gap:12px;} input[type=time]{width:130px;padding:8px;border:1px solid token.$crm-border-default;border-radius:4px;color:inherit;background:token.$crm-color-surface;} }
</style>
