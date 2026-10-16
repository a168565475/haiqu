import type { EChartsOption } from 'echarts'
import {
  defectSamples,
  productionSamples,
  stockAgeSamples,
  warehouseSamples,
} from './demoData'

const axisColor = '#3e789c'
const gridColor = '#2b506a'
const blue = {
  type: 'linear' as const, x: 0, y: 0, x2: 0, y2: 1,
  colorStops: [{ offset: 0, color: '#69b8e9' }, { offset: 1, color: '#325e84' }],
}
const yellow = '#ffff00'
const green = '#00c894'
const ringColors = ['#299dff', '#24d6c1', '#ffce54', '#f1856b']
const defectColors = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc']
const tooltip = {
  backgroundColor: 'rgba(5, 29, 57, .96)',
  borderColor: '#2e739f',
  textStyle: { color: '#e1f4ff', fontFamily: 'sans-serif', fontSize: 12 },
  extraCssText: 'box-shadow: 0 4px 18px rgba(0,0,0,.28);',
  confine: true,
}
const splitLine = { show: true, lineStyle: { color: gridColor, type: 'dashed' as const } }
const axisLabel = { color: axisColor, fontSize: 12, fontFamily: 'sans-serif' }
const axisLine = { show: true, lineStyle: { color: '#31546c' } }
const legend = {
  top: 20,
  left: 'center',
  icon: 'circle',
  itemWidth: 14,
  itemHeight: 14,
  textStyle: { color: axisColor, fontSize: 14, fontFamily: 'sans-serif' },
}

function chartBase(description: string): EChartsOption {
  return {
    backgroundColor: 'transparent',
    animationDuration: 500,
    textStyle: { color: axisColor, fontFamily: 'sans-serif' },
    aria: { enabled: true, label: { description: `固定内存演示数据。${description}` } },
    tooltip,
  }
}

export const defectTrendOption: EChartsOption = {
  ...chartBase('十月不良数量与不良率；蓝色柱形表示不良数量，黄色折线表示不良率；未来日期不展示数值。'),
  legend,
  grid: { left: 40, right: 60, top: 60, bottom: 26 },
  tooltip: { ...tooltip, trigger: 'axis' },
  xAxis: {
    type: 'category',
    data: productionSamples.map((sample) => sample.day),
    axisLabel,
    axisLine,
    axisTick: { show: false },
  },
  yAxis: [
    { type: 'value', name: '不良品数', axisLabel, axisLine, axisTick: { show: false }, splitLine, nameTextStyle: { color: axisColor, fontSize: 14 }, minInterval: 1 },
    { type: 'value', name: '不良品率', min: 0, axisLabel: { ...axisLabel, formatter: '{value}%' }, axisLine, axisTick: { show: false }, splitLine: { show: false }, nameTextStyle: { color: axisColor, fontSize: 14 } },
  ],
  series: [
    {
      name: '不良品数',
      type: 'bar',
      barMaxWidth: 14,
      itemStyle: { color: blue },
      data: productionSamples.map((sample) => sample.defective),
    },
    {
      name: '不良品率',
      type: 'line',
      yAxisIndex: 1,
      smooth: false,
      symbol: 'circle',
      symbolSize: 5,
      itemStyle: { color: yellow },
      lineStyle: { color: yellow, width: 2 },
      data: productionSamples.map((sample) => sample.reported === null || sample.defective === null ? null : sample.reported === 0 ? 0 : Number(((sample.defective / sample.reported) * 100).toFixed(2))),
      tooltip: { valueFormatter: (value) => `${value}%` },
    },
  ],
}

function ringOption(description: string, data: Array<{ name: string; value: number }>): EChartsOption {
  return {
    ...chartBase(description),
    color: ringColors,
    tooltip: { ...tooltip, trigger: 'item', formatter: '{b}<br/>{c} 件 · {d}%' },
    legend: {
      itemWidth: 10,
      itemHeight: 7,
      textStyle: { color: '#a8d9f4', fontSize: 12, fontFamily: 'sans-serif' },
      orient: 'vertical',
      top: 'center',
      right: '3%',
      itemGap: 14,
      formatter: (name) => `${name}  ${data.find((item) => item.name === name)?.value ?? 0}`,
    },
    series: [{
      name: description,
      type: 'pie',
      radius: ['38%', '65%'],
      center: ['40%', '54%'],
      avoidLabelOverlap: true,
      label: { show: true, formatter: '{b}\n{d}%', fontSize: 11, color: 'inherit' },
      labelLine: { show: true, length: 10, length2: 8 },
      itemStyle: { borderWidth: 0 },
      emphasis: { scaleSize: 5 },
      data,
    }],
  }
}

export const defectDistributionOption: EChartsOption = {
  ...chartBase('今日不良原因分布；分类为自建演示样本，左右引线对应分类与占比，右侧图例可翻页。'),
  color: defectColors,
  tooltip: { ...tooltip, trigger: 'item', formatter: '{b}<br/>{c} 件 · {d}%' },
  legend: {
    type: 'scroll',
    orient: 'vertical',
    top: 30,
    bottom: 0,
    right: 0,
    icon: 'circle',
    itemWidth: 14,
    itemHeight: 14,
    itemGap: 10,
    textStyle: { fontSize: 12, fontFamily: 'sans-serif' },
    data: defectSamples.map((item, index) => ({ name: item.name, textStyle: { color: defectColors[index % defectColors.length] } })),
    pageIconSize: 14,
    pageIconColor: '#b7b7b7',
    pageIconInactiveColor: '#38566c',
    pageTextStyle: { color: '#dedede', fontSize: 12 },
  },
  series: [{
    name: '不良原因',
    type: 'pie',
    right: '20%',
    radius: ['40%', '70%'],
    center: ['50%', '50%'],
    avoidLabelOverlap: true,
    label: { show: true, formatter: '{b}\n{d}%', fontSize: 12, color: 'inherit', alignTo: 'edge', edgeDistance: 10 },
    labelLine: { show: true, length: 15, length2: 25 },
    itemStyle: { borderWidth: 0 },
    data: defectSamples,
  }],
}

// 原站此区域为空数据，以下库龄环图沿用自建演示样式；原站有数据时的样式来源为 UNKNOWN。
export const stockDistributionOption = ringOption('当前库存库龄分布；自建演示图，原站有数据时的图表样式来源 UNKNOWN', stockAgeSamples)

export const outputTrendOption: EChartsOption = {
  ...chartBase('十月报工数量，绿色直线与浅色面积表示每日报工数；未来日期不展示数值。'),
  legend: { ...legend, left: undefined, right: 24 },
  grid: { left: 56, right: 46, top: 60, bottom: 30 },
  tooltip: { ...tooltip, trigger: 'axis' },
  xAxis: {
    type: 'category',
    data: productionSamples.map((sample) => sample.day),
    axisLabel,
    axisLine,
    axisTick: { show: false },
  },
  yAxis: { type: 'value', name: '报工数量', axisLabel, axisLine, axisTick: { show: false }, splitLine, nameTextStyle: { color: axisColor, fontSize: 14 } },
  series: [{
    name: '报工数量',
    type: 'line',
    smooth: false,
    symbol: 'circle',
    symbolSize: 4,
    itemStyle: { color: green },
    lineStyle: { color: green, width: 2 },
    areaStyle: {
      color: {
        type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [{ offset: 0, color: 'rgba(0, 200, 148, .12)' }, { offset: 1, color: 'rgba(0, 200, 148, 0)' }],
      },
    },
    data: productionSamples.map((sample) => sample.reported),
  }],
}

function movementTrendOption(direction: 'inbound' | 'outbound'): EChartsOption {
  const name = direction === 'inbound' ? '入库数' : '出库数'
  return {
    ...chartBase(`十月${name}与较前一日增长率；首日及前日数量为零时无对比基数，不展示增长率；未来日期不展示数值。`),
    legend,
    grid: { left: 40, right: 60, top: 60, bottom: 30 },
    tooltip: { ...tooltip, trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: warehouseSamples.map((sample) => sample.day),
      axisLabel,
      axisLine,
      axisTick: { show: false },
    },
    yAxis: [
      { type: 'value', name: '商品数量', axisLabel, axisLine, axisTick: { show: false }, splitLine, nameTextStyle: { color: axisColor } },
      { type: 'value', name: '增长率', axisLabel: { ...axisLabel, formatter: '{value}%' }, axisLine, axisTick: { show: false }, splitLine: { show: false }, nameTextStyle: { color: axisColor } },
    ],
    series: [
      {
        name,
        type: 'bar',
        barMaxWidth: 14,
        itemStyle: { color: blue },
        data: warehouseSamples.map((sample) => sample[direction]),
      },
      {
        name: '增长率',
        type: 'line',
        yAxisIndex: 1,
        smooth: false,
        symbol: 'circle',
        symbolSize: 5,
        itemStyle: { color: yellow },
        lineStyle: { color: yellow, width: 2 },
        data: warehouseSamples.map((sample, index) => {
          const previous = warehouseSamples[index - 1]?.[direction]
          const current = sample[direction]
          return current !== null && previous ? Number((((current - previous) / previous) * 100).toFixed(2)) : null
        }),
        tooltip: { valueFormatter: (value) => `${value}%` },
      },
    ],
  }
}

export const inboundTrendOption = movementTrendOption('inbound')
export const outboundTrendOption = movementTrendOption('outbound')
