<script setup lang="ts">
import BoardChart from './components/BoardChart.vue'
import BoardMetrics from './components/BoardMetrics.vue'
import BoardPanel from './components/BoardPanel.vue'
import BoardRankingList from './components/BoardRankingList.vue'
import BoardShell from './components/BoardShell.vue'
import BoardTable from './components/BoardTable.vue'
import {
  inboundTrendOption,
  outboundTrendOption,
  stockDistributionOption,
} from './chartOptions'
import { inboundRankingRows, stockMovementRows, stockRows, warehouseMetrics, warehouseProductTotals } from './demoData'

const outboundRankingRows = warehouseProductTotals.map((row) => ({ name: row.name, value: row.outbound }))

const stockColumns = [
  { key: 'product', label: '商品名', width: '24%' },
  { key: 'code', label: '商品编号', width: '22%' },
  { key: 'specification', label: '商品规格', width: '22%' },
  { key: 'source', label: '商品来源', width: '17%' },
  { key: 'stock', label: '库存数', width: '15%' },
]

const movementColumns = [
  { key: 'order', label: '出入库单号', width: '17%' },
  { key: 'product', label: '商品名', width: '17%' },
  { key: 'code', label: '商品编号', width: '17%' },
  { key: 'specification', label: '商品规格', width: '14%' },
  { key: 'quantity', label: '数量', width: '9%' },
  { key: 'type', label: '单据类型', width: '14%' },
  { key: 'warehouse', label: '仓库', width: '12%' },
]
</script>

<template>
  <BoardShell title="仓库大屏">
    <div class="board-grid warehouse-board">
      <BoardPanel title="商品出库统计" period="本月">
        <BoardChart :option="outboundTrendOption" label="本月商品出库数量及增长率趋势" />
      </BoardPanel>

      <BoardMetrics :items="warehouseMetrics" />

      <BoardPanel title="商品入库统计" period="本月">
        <BoardChart :option="inboundTrendOption" label="本月商品入库数量及增长率趋势" />
      </BoardPanel>

      <BoardPanel title="出库商品排行">
        <BoardRankingList :rows="outboundRankingRows" label="出库商品数量排行" />
      </BoardPanel>

      <BoardPanel title="呆滞库存分布">
        <BoardChart :option="stockDistributionOption" label="呆滞库存商品分布" />
      </BoardPanel>

      <BoardPanel title="入库商品排行">
        <BoardRankingList :rows="inboundRankingRows" label="入库商品数量排行" />
      </BoardPanel>

      <div class="board-bottom">
        <BoardPanel title="实时库存统计">
          <BoardTable :columns="stockColumns" :rows="stockRows" />
        </BoardPanel>

        <BoardPanel title="出入库流水">
          <BoardTable :columns="movementColumns" :rows="stockMovementRows" />
        </BoardPanel>
      </div>
    </div>
  </BoardShell>
</template>
