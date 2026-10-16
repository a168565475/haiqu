<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { init, use, type EChartsType } from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { AriaComponent, GridComponent, LegendComponent, LegendScrollComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsOption } from 'echarts'

use([BarChart, LineChart, PieChart, AriaComponent, GridComponent, LegendComponent, LegendScrollComponent, TooltipComponent, CanvasRenderer])
const props = defineProps<{ option: EChartsOption; label: string }>()
const container = ref<HTMLDivElement>()
let chart: EChartsType | undefined
let observer: ResizeObserver | undefined
defineExpose({ getChart: () => chart })
function render() {
  chart?.setOption({ ...props.option, animation: !window.matchMedia('(prefers-reduced-motion: reduce)').matches }, true)
}
onMounted(() => {
  chart = init(container.value!, undefined, { renderer: 'canvas' })
  render()
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(container.value!)
})
watch(() => props.option, render)
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
</script>

<template><div ref="container" class="board-chart" role="img" :aria-label="`${label}，演示数据`" /></template>
