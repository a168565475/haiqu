<script setup lang="ts">
import type { OutsourcingPrintDocumentData } from '@/types/outsourcingPrint'

defineProps<{ document: OutsourcingPrintDocumentData }>()
</script>

<template>
  <article class="outsourcing-print-document" :class="`outsourcing-print-document--${document.kind}`" :aria-label="document.kind === 'spray' ? '管材喷塑打印文档' : '加工单打印文档'">
    <h1>{{ document.title }}</h1>

    <template v-if="document.kind === 'processing'">
      <div class="print-meta">
        <div class="print-meta-full"><span>提交人：</span>{{ document.submittedBy }}</div>
        <div><span>提交时间：</span>{{ document.submittedAt }}</div>
        <div><span>更新时间：</span>{{ document.updatedAt }}</div>
      </div>
      <table data-section="basic" aria-label="委外加工单基本信息" class="print-basic-table">
        <colgroup><col style="width: 45.5%"><col style="width: 54.5%"></colgroup>
        <tbody>
          <tr><th scope="col">委外加工单编号</th><th scope="col">委外工艺</th></tr>
          <tr><td>{{ document.orderNumber }}</td><td>{{ document.craftName }}</td></tr>
          <tr><th scope="col">委外加工厂</th><th scope="col">制单人</th></tr>
          <tr><td>{{ document.factoryNames }}</td><td>{{ document.preparedBy }}</td></tr>
          <tr><th scope="col">承包人</th><th scope="col">制单日期</th></tr>
          <tr><td></td><td>{{ document.preparedDate }}</td></tr>
          <tr><th colspan="2" scope="col">交货日期</th></tr>
          <tr><td colspan="2">{{ document.deliveryDate }}</td></tr>
        </tbody>
      </table>

      <table data-section="plans" aria-label="主计划明细" class="print-plan-table print-section-table">
        <colgroup><col v-for="index in 6" :key="index" style="width: 15.15%"><col style="width: 9.1%"></colgroup>
        <thead>
          <tr><th colspan="7" class="print-section-title">主计划明细</th></tr>
          <tr><th scope="col">外发是否完成</th><th scope="col">订单号</th><th scope="col">货号</th><th scope="col">产品名称</th><th scope="col">排产数量</th><th scope="col">颜色</th><th scope="col">规格</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in document.plans" :key="row.id" :data-row-id="row.id">
            <td>{{ row.completed }}</td><td>{{ row.orderNumber }}</td><td>{{ row.itemNumber }}</td><td>{{ row.productName }}</td><td>{{ row.plannedQuantity }}</td><td>{{ row.color }}</td><td>{{ row.specification }}</td>
          </tr>
          <tr v-if="!document.plans.length"><td colspan="7" class="print-empty">暂无明细</td></tr>
        </tbody>
      </table>

      <table data-section="materials" aria-label="材料明细" class="print-material-table print-section-table">
        <colgroup><col v-for="index in 6" :key="index" style="width: 15.15%"><col style="width: 9.1%"></colgroup>
        <thead>
          <tr><th colspan="7" class="print-section-title">材料明细</th></tr>
          <tr><th scope="col">订单号</th><th scope="col">品名</th><th scope="col">单个用量</th><th scope="col">订单量</th><th scope="col">需外发数量</th><th scope="col">单位</th><th scope="col">规格</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in document.materials" :key="row.id" data-material-row :data-row-id="row.id">
            <td>{{ row.orderNumber }}</td><td>{{ row.name }}</td><td>{{ row.unitConsumption }}</td><td>{{ row.orderQuantity }}</td><td>{{ row.issueQuantity }}</td><td>{{ row.unit }}</td><td>{{ row.specification }}</td>
          </tr>
          <tr v-if="!document.materials.length"><td colspan="7" class="print-empty">暂无明细</td></tr>
          <tr v-if="document.materials.length" class="print-attribute-heading">
            <th scope="col">颜色</th><th scope="col">材质</th><td v-for="index in 5" :key="index" :rowspan="document.materials.length + 1"></td>
          </tr>
          <tr v-for="row in document.materials" :key="`attributes-${row.id}`" data-material-attributes :data-row-id="row.id">
            <td>{{ row.color }}</td><td>{{ row.material }}</td>
          </tr>
        </tbody>
      </table>
    </template>

    <template v-else>
      <div class="print-meta print-spray-meta">
        <div><span>产品名称：</span>{{ document.productName }}</div>
        <div><span>回厂时间：</span>{{ document.deliveryDate }}</div>
        <div class="print-meta-full"><span>来厂拉货时间：</span>{{ document.dispatchDate }}</div>
      </div>
      <table data-section="spray" aria-label="管材喷塑计划明细" class="print-spray-table">
        <colgroup><col style="width: 13.3%"><col style="width: 15.2%"><col style="width: 12.4%"><col style="width: 10.5%"><col style="width: 10.8%"><col style="width: 11.5%"><col style="width: 12.8%"><col style="width: 13.5%"></colgroup>
        <thead><tr><th scope="col">加工厂</th><th scope="col">部件名称</th><th colspan="2" scope="colgroup">材料规格</th><th scope="col">单耗量</th><th scope="col">订单数量</th><th scope="col">总支数</th><th scope="col">喷塑颜色</th></tr></thead>
        <tbody>
          <tr v-for="row in document.sprayRows" :key="row.id" data-spray-row :data-row-id="row.id">
            <td>{{ row.factoryName }}</td><td>{{ row.partName }}</td><td>{{ row.specification }}</td><td>{{ row.cuttingLength }}</td><td>{{ row.unitConsumption }}</td><td>{{ row.orderQuantity }}</td><td>{{ row.totalQuantity }}</td><td>{{ row.sprayColor }}</td>
          </tr>
          <tr v-if="!document.sprayRows.length"><td colspan="8" class="print-empty">暂无明细</td></tr>
          <tr class="print-spray-footer"><td>制表人：</td><td>{{ document.preparedBy }}</td><td>日期：</td><td colspan="2">{{ document.submittedAt }}</td><td colspan="3" data-warehouse-note>喷塑回来请注明单号，否则一律拒收。仓库电话：15284640047张</td></tr>
        </tbody>
      </table>
      <p class="print-remark" data-field="remark">备注：<span>{{ document.remark }}</span></p>
    </template>
  </article>
</template>

<style lang="scss">
@page outsourcing-document {
  size: A4 portrait;
  margin: 23mm 16mm 15mm;
}

.outsourcing-print-document {
  page: outsourcing-document;
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin: 0 auto;
  padding: 5mm;
  background: #fff;
  color: #000;
  font: 9pt/1.35 SimSun, '宋体', 'Noto Serif SC', serif;
  print-color-adjust: exact;
  -webkit-print-color-adjust: exact;

  h1 { margin: 0 0 3.5mm; color: #000; text-align: center; font: bold 18pt/1.4 SimSun, '宋体', 'Noto Serif SC', serif; overflow-wrap: anywhere; }
  .print-meta { display: grid; grid-template-columns: 45.5% 54.5%; }
  .print-meta > div { display: flex; align-items: baseline; min-height: 6.5mm; padding: 0 1mm; overflow-wrap: anywhere; }
  .print-meta span { flex: 0 0 27mm; }
  .print-meta-full { grid-column: 1 / -1; }
  table { width: 100%; table-layout: fixed; border-collapse: collapse; border-spacing: 0; color: #000; font: inherit; }
  thead { display: table-header-group; }
  tr { break-inside: avoid; page-break-inside: avoid; }
  th, td { box-sizing: border-box; height: 6.5mm; padding: .6mm 1mm; border: 1px solid #000; background: #fff; color: #000; text-align: left; vertical-align: middle; font: inherit; overflow-wrap: anywhere; }
  .print-section-table { margin-top: 2mm; }
  .print-section-title { text-align: center; }
  .print-plan-table tbody td { height: 15mm; }
  .print-material-table [data-material-row] td { height: 10.5mm; }
  .print-empty { text-align: center; }
  .print-spray-meta { grid-template-columns: 41% 59%; margin-bottom: 2mm; }
  .print-spray-table th, .print-spray-table td { text-align: center; }
  .print-spray-table .print-spray-footer td { height: 13mm; text-align: left; }
  .print-remark { display: flex; gap: 2mm; margin: 13mm 1mm 0; white-space: pre-wrap; overflow-wrap: anywhere; }

  &--spray h1 { margin-bottom: 9.5mm; }
}

@media print {
  .outsourcing-print-document { width: 100%; margin: 0; box-decoration-break: clone; -webkit-box-decoration-break: clone; }
}
</style>
