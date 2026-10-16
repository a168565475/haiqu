<script setup lang="ts">
import BoardShell from './components/BoardShell.vue'
import BoardPanel from './components/BoardPanel.vue'
import BoardChart from './components/BoardChart.vue'
import BoardMetrics from './components/BoardMetrics.vue'
import BoardTable from './components/BoardTable.vue'
import BoardProcessTable from './components/BoardProcessTable.vue'
import BoardEmployeeList from './components/BoardEmployeeList.vue'
import { defectDistributionOption, defectTrendOption, outputTrendOption } from './chartOptions'
import { demoOrders, employeeDisplayRows, productionMetrics, qualityRows, taskRows } from './demoData'

const qualityColumns = [
  { key: 'time', label: '时间', width: '18%' }, { key: 'worker', label: '报工人', width: '12%' },
  { key: 'process', label: '工序', width: '19%', tone: 'white' }, { key: 'product', label: '产品', width: '23%', tone: 'white' },
  { key: 'reported', label: '报工数', width: '14%', tone: 'green' }, { key: 'defective', label: '不良品数', width: '14%', tone: 'red' },
]
const taskColumns = [
  { key: 'order', label: '工单编号', width: '18%' }, { key: 'process', label: '工序', width: '13%', tone: 'white' },
  { key: 'worker', label: '生产人员', width: '21%' }, { key: 'planned', label: '任务数', width: '12%' },
  { key: 'good', label: '良品数', width: '12%', tone: 'green' }, { key: 'defective', label: '不良品数', width: '12%', tone: 'red' },
  { key: 'remaining', label: '未完成数', width: '12%', tone: 'yellow' },
]
</script>

<template>
  <BoardShell title="产线大屏">
    <div class="board-grid production-line-board">
      <BoardPanel title="不良品项分布" period="本月"><BoardChart :option="defectDistributionOption" label="不良品项分布" /></BoardPanel>
      <BoardMetrics :items="productionMetrics" />
      <BoardPanel title="工单执行进度"><BoardProcessTable :rows="demoOrders" compact searchable show-product-image /></BoardPanel>
      <BoardPanel title="不良品分析" period="本月"><BoardChart :option="defectTrendOption" label="不良品数量与比例趋势" /></BoardPanel>
      <BoardPanel title="质检信息"><BoardTable :columns="qualityColumns" :rows="qualityRows" /></BoardPanel>
      <BoardPanel title="人员生产统计">
        <BoardEmployeeList :rows="employeeDisplayRows" />
      </BoardPanel>
      <div class="board-bottom">
        <BoardPanel title="工序报工分析" period="本月"><BoardChart :option="outputTrendOption" label="工序报工数量趋势" /></BoardPanel>
        <BoardPanel title="任务执行进度"><BoardTable :columns="taskColumns" :rows="taskRows" /></BoardPanel>
      </div>
    </div>
  </BoardShell>
</template>
