<script setup lang="ts">
import BoardChart from './components/BoardChart.vue'
import BoardFeedTable from './components/BoardFeedTable.vue'
import BoardMetrics from './components/BoardMetrics.vue'
import BoardPanel from './components/BoardPanel.vue'
import BoardProcessTable from './components/BoardProcessTable.vue'
import BoardRankingList from './components/BoardRankingList.vue'
import BoardShell from './components/BoardShell.vue'
import BoardTable from './components/BoardTable.vue'
import {
  defectDistributionOption,
  defectTrendOption,
  outputTrendOption,
} from './chartOptions'
import { demoOrders, employeeRows, productionMetrics, taskRows, workReportRows } from './demoData'

const employeeRankingRows = employeeRows.map(row => ({ name: row.name, value: row.reported }))

const workReportColumns = [
  { key: 'time', label: '时间', width: '14%' },
  { key: 'worker', label: '报工人', width: '12%' },
  { key: 'process', label: '工序', width: '18%' },
  { key: 'product', label: '产品', width: '16%' },
  { key: 'code', label: '编号', width: '16%' },
  { key: 'good', label: '良品数', width: '12%', tone: 'green' },
  { key: 'defective', label: '不良品数', width: '12%', tone: 'red' },
]

const taskColumns = [
  { key: 'order', label: '工单编号', width: '16%' },
  { key: 'process', label: '工序', width: '15%', tone: 'white' },
  { key: 'worker', label: '生产人员', width: '23%' },
  { key: 'planned', label: '任务数', width: '11%' },
  { key: 'good', label: '良品数', width: '11%', tone: 'green' },
  { key: 'defective', label: '不良品数', width: '12%', tone: 'red' },
  { key: 'remaining', label: '未完成数', width: '12%', tone: 'yellow' },
]
</script>

<template>
  <BoardShell title="生产中控大屏">
    <div class="board-grid production-board">
      <BoardPanel title="员工报工排行" period="本月">
        <BoardRankingList :rows="employeeRankingRows" label="员工报工排行" />
      </BoardPanel>

      <BoardMetrics :items="productionMetrics" />

      <BoardPanel title="不良品分析" period="本月">
        <BoardChart :option="defectTrendOption" label="本月不良品数量及不良品率趋势" />
      </BoardPanel>

      <BoardPanel title="工单产出分析" period="本月">
        <BoardChart :option="outputTrendOption" label="本月工单产出数量趋势" />
      </BoardPanel>

      <BoardPanel title="实时报工数据">
        <BoardFeedTable :columns="workReportColumns" :rows="workReportRows" />
      </BoardPanel>

      <BoardPanel title="不良品项分布" period="本月">
        <BoardChart :option="defectDistributionOption" label="本月各不良品项目数量分布" />
      </BoardPanel>

      <div class="board-bottom">
        <BoardPanel title="工单执行进度">
          <BoardProcessTable :rows="demoOrders" compact searchable />
        </BoardPanel>

        <BoardPanel title="任务执行进度">
          <BoardTable :columns="taskColumns" :rows="taskRows" />
        </BoardPanel>
      </div>
    </div>
  </BoardShell>
</template>
