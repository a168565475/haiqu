<script setup>
import {computed,ref} from 'vue'
import {ArrowLeft,Document,Refresh} from '@element-plus/icons-vue'
const quantity=ref('200'),date=ref('2026-09-29'),warehouse=ref('finished'),location=ref(['A','A-01-01']),perBox=ref('4'),remark=ref(''),message=ref('')
const locations=[{value:'A',label:'A区',children:[{value:'A-01-01',label:'A-01-01',slots:100},{value:'A-01-02',label:'A-01-02',slots:20},{value:'A-02-01',label:'A-02-01',slots:80}]},{value:'B',label:'B区',children:[{value:'B-01-01',label:'B-01-01',slots:60},{value:'B-01-02',label:'B-01-02',slots:120}]}]
const selectedLocation=computed(()=>locations.flatMap(z=>z.children).find(l=>l.value===location.value?.[1]))
const q=computed(()=>Number(quantity.value)),pack=computed(()=>Number(perBox.value)),validQty=computed(()=>Number.isSafeInteger(q.value)&&q.value>0&&q.value<=300)
const validPack=computed(()=>perBox.value!==''&&Number.isSafeInteger(pack.value)&&pack.value>0)
const boxes=computed(()=>validQty.value&&validPack.value?Math.floor(q.value/pack.value):null),tail=computed(()=>validQty.value&&validPack.value?q.value%pack.value:null),slots=computed(()=>validQty.value&&validPack.value?Math.ceil(q.value/pack.value):null)
const error=computed(()=>quantity.value&&!validQty.value?'本次入库须为1至300之间的整数。':perBox.value&&!validPack.value?'每箱数量须为正整数。':slots.value!==null&&selectedLocation.value&&slots.value>selectedLocation.value.slots?'所选库位剩余箱位不足，请更换库位或调整本次数量。':'')
const after=computed(()=>validQty.value?600+q.value:600),remaining=computed(()=>validQty.value?300-q.value:300)
function previewConfirm(){message.value='设计演示：已核对本次填写内容，未保存单据或改变库存。'}
</script>
<template>
 <header class="page-heading"><div class="title-row"><h1>成品入库</h1><span class="source-tag">装配来源</span></div><ElButton :icon="Document" @click="message='入库记录入口示意，本设计图不连接业务数据。'">入库记录</ElButton></header>
 <section class="order-strip" aria-label="订单信息和入库额度">
  <div class="order-identities info-grid"><div class="info-cell"><span>生产单号</span><b title="SC20260929001">SC20260929001</b></div><div class="info-cell"><span>订单号</span><b title="DD20260921001">DD20260921001</b></div><div class="info-cell"><span>装配计划</span><b title="PC20260929001">PC20260929001</b></div><div class="info-cell"><span>品号</span><b>CP000128</b></div><div class="info-cell"><span>入库人</span><b>当前仓管</b></div></div>
  <div class="product-line info-grid"><div class="info-cell"><span>产品名称</span><b title="组合杯托折叠椅">组合杯托折叠椅</b></div><div class="info-cell"><span>规格</span><b title="53 × 53 × 90 cm">53 × 53 × 90 cm</b></div><div class="info-cell"><span>订单颜色</span><b title="颜色跟随订单，无需选择">黑色</b></div><div class="info-cell"><span>货号</span><b>HT-806</b></div><div class="info-cell"><span>入库额度</span><ElTooltip content="订单含2%允许偏差的上限为1,020把，与装配全部工序最低累计报工900把取较小值，再扣已入库600把。出库不恢复入库额度。" placement="bottom" popper-class="receipt-design-popper"><span class="quota-rule info-value" tabindex="0">额度说明</span></ElTooltip></div></div>
  <div class="quota-strip info-grid"><div class="info-cell"><span>订单量</span><span class="info-value"><b>1,000</b> 把</span></div><div class="info-cell"><span>装配最低报工</span><span class="info-value"><b>900</b> 把</span></div><div class="info-cell"><span>累计上限</span><span class="info-value"><b>900</b> 把</span></div><div class="info-cell"><span>已入库</span><span class="info-value"><b>600</b> 把</span></div><div class="info-cell quota-emphasis"><span>剩余可入</span><span class="info-value"><b>300</b> 把</span></div></div>
 </section>
 <section class="receipt-workspace">
  <div class="workspace-heading"><h2>本次入库</h2><span>按仓库实际收到的数量填写</span></div>
  <ElForm label-position="top" class="receipt-form">
   <div class="receipt-fields">
    <ElFormItem label="入库数量" required class="quantity-field"><ElInput v-model="quantity" aria-label="入库数量" inputmode="numeric" placeholder="填写本次实收数量"><template #suffix><span class="unit-suffix">把</span></template></ElInput><div class="field-help">本次最多可入 <b>300</b> 把</div></ElFormItem>
    <ElFormItem label="收货日期" required><ElDatePicker v-model="date" aria-label="收货日期" type="date" format="YYYY-MM-DD" value-format="YYYY-MM-DD" :clearable="false" popper-class="receipt-design-popper" placeholder="选择日期" /></ElFormItem>
    <ElFormItem label="成品仓" required><ElSelect v-model="warehouse" aria-label="成品仓" placeholder="选择成品仓" popper-class="receipt-design-popper"><ElOption label="CK007 · 成品仓" value="finished" /></ElSelect></ElFormItem>
    <ElFormItem label="库区 / 库位" required><ElCascader v-model="location" aria-label="库区 / 库位" :options="locations" :props="{expandTrigger:'hover'}" filterable clearable popper-class="receipt-design-popper" placeholder="选择库区，再选择库位"><template #default="{node,data}"><span>{{data.label}}</span><span v-if="node.isLeaf" class="location-capacity">剩余 {{data.slots}} 箱位</span></template></ElCascader><div class="field-help">先选库区，再选库位<span v-if="selectedLocation"> · 当前剩余 {{selectedLocation.slots}} 箱位</span></div></ElFormItem>
   </div>
   <div class="receipt-result"><span>本次入库 <b>{{validQty?q:'—'}}</b> 把</span><i></i><span>入库后累计 <b>{{after}}</b> 把</span><i></i><span>入库后剩余额度 <b>{{remaining}}</b> 把</span></div>
   <section class="packing-section"><div class="subheading"><h3>包装信息</h3><span>选填，填写后自动计算箱数与占用箱位</span></div><div class="packing-fields"><ElFormItem label="每箱数量"><ElInput v-model="perBox" inputmode="numeric" aria-label="每箱数量" placeholder="选填"><template #suffix>把 / 箱</template></ElInput></ElFormItem><div class="packing-stat"><span>整箱数</span><b>{{boxes===null?'未计算':boxes+' 箱'}}</b></div><div class="packing-stat"><span>尾数</span><b>{{tail===null?'未计算':tail+' 把'}}</b></div><div class="packing-stat"><span>本次占用箱位</span><b>{{slots===null?'未计算':slots+' 箱位'}}</b></div><div class="packing-stat"><span>入库后剩余箱位</span><b>{{slots===null||!selectedLocation?'未计算':Math.max(0,selectedLocation.slots-slots)+' 箱位'}}</b></div></div><p class="field-help">有尾数时另占1个箱位；每箱数量留空时不计算箱位。</p></section>
   <section class="remark-section"><div class="subheading"><h3>入库备注</h3><span>选填</span></div><ElInput v-model="remark" type="textarea" :rows="3" maxlength="3000" show-word-limit aria-label="入库备注" placeholder="填写本次收货、包装或存放说明" /></section>
  </ElForm>
  <ElAlert v-if="error" :title="error" type="error" :closable="false" show-icon />
  <ElAlert v-else-if="message" :title="message" type="info" :closable="true" @close="message=''" />
 </section>
 <footer class="receipt-footer"><div><span>本次入库 <strong>{{validQty?q:'—'}}</strong> 把</span><small>确认后增加成品库存，已领半成品不重复扣减。</small></div><ElButton :icon="ArrowLeft" @click="message='返回订单选择入口示意。'">返回</ElButton><ElButton :icon="Refresh" @click="quantity='';remark='';message=''">重填</ElButton><ElButton type="primary" :disabled="!!error||!validQty||!date||!selectedLocation" @click="previewConfirm">确认入库</ElButton></footer>
</template>
