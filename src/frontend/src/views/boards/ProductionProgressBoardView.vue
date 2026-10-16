<script setup lang="ts">
import BoardShell from './components/BoardShell.vue'
import BoardPanel from './components/BoardPanel.vue'
import BoardProcessTable from './components/BoardProcessTable.vue'
import { demoOrders } from './demoData'
</script>

<template>
  <BoardShell title="生产进度看板">
    <BoardPanel title="工单执行进度" class="board-progress-panel"><BoardProcessTable :rows="demoOrders" searchable /></BoardPanel>
  </BoardShell>
</template>
