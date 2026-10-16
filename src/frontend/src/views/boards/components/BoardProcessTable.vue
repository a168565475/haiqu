<script setup lang="ts">
import { computed, ref, watch, type ComponentPublicInstance } from 'vue'
import type { BoardOrder, BoardProcess } from '@/types/board'
import { useBoardAutoScroll } from '../useBoardAutoScroll'

const props = withDefaults(defineProps<{ rows: BoardOrder[]; compact?: boolean; searchable?: boolean; showProductImage?: boolean }>(), { compact: false, searchable: false, showProductImage: false })
const query = ref('')
const filtered = computed(() => {
  const term = query.value.trim().toLocaleLowerCase()
  return props.rows.filter(row => `${row.id} ${row.productCode} ${row.product} ${row.specification}`.toLocaleLowerCase().includes(term))
})
const scroll = ref<HTMLElement>()
const content = ref<HTMLElement>()
function setContent(element: Element | ComponentPublicInstance | null) { content.value = element as HTMLElement | undefined }
const { hovered, focused, looping, reset } = useBoardAutoScroll(scroll, content, props.compact ? 26.84 : 34.56)
watch(filtered, reset, { flush: 'post' })
const columns = computed(() => props.compact
  ? [{ key: 'id', label: '工单编号', width: props.showProductImage ? '12.5%' : '9.16%' }, { key: 'product', label: '产品', width: props.showProductImage ? '12.5%' : '11.12%' },
    { key: 'productCode', label: props.showProductImage ? '产品编号' : '编号', width: props.showProductImage ? '12.5%' : '6.98%' },
    ...(props.showProductImage ? [{ key: 'image', label: '产品图片', width: '12.5%' }] : []),
    { key: 'specification', label: props.showProductImage ? '产品规格' : '规格', width: props.showProductImage ? '12.5%' : '7.85%' }, { key: 'planned', label: '计划数', width: props.showProductImage ? '12.5%' : '10.8%' },
    { key: 'priority', label: '优先级', width: props.showProductImage ? '12.5%' : '12%' }, { key: 'processes', label: '工序进度', width: props.showProductImage ? '12.5%' : '42.09%' }]
  : [{ key: 'id', label: '工单编号', width: '25%' }, { key: 'productCode', label: '产品编号', width: '25%' },
    { key: 'product', label: '产品', width: '25%' }, { key: 'processes', label: '工序进度', width: '25%' }])
function status(process: BoardProcess) { return process.completed >= process.total ? '已完成' : process.completed > 0 ? '进行中' : '未开始' }
</script>

<template>
  <div class="board-process-table" :class="{ 'is-compact': compact, 'has-product-image': showProductImage }">
    <label v-if="searchable" class="board-search">
      <span class="board-sr-only">搜索工单编号、产品、编号或规格</span>
      <input v-model="query" type="search" placeholder="请输入工单编号/产品名/编号/规格" autocomplete="off" />
      <svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="8" cy="8" r="5" /><path d="m12 12 5 5" /></svg>
    </label>
    <div ref="scroll" class="board-table-scroll" :data-loop-active="looping" tabindex="0" aria-label="工单工序进度，可滚动；停留时暂停轮播"
      @mouseenter="hovered = true" @mouseleave="hovered = false" @focusin="focused = true" @focusout="focused = false">
      <table class="board-table board-processes">
        <colgroup><col v-for="column in columns" :key="column.key" :style="{ width: column.width }" /></colgroup>
        <thead><tr><th v-for="column in columns" :key="column.key" scope="col" :title="column.label">{{ column.label }}</th></tr></thead>
        <tbody v-for="copy in looping ? 2 : 1" :key="copy" :ref="copy === 1 ? setContent : undefined"
          :data-loop-content="copy === 1 ? '' : undefined" :data-loop-copy="copy === 2 ? '' : undefined"
          :aria-hidden="copy === 2 ? 'true' : undefined" :inert="copy === 2"><tr v-for="order in filtered" :key="order.id">
          <td v-for="column in columns" :key="column.key" :class="`board-process-column-${column.key}`" :title="column.key === 'processes' ? undefined : String(order[column.key as keyof BoardOrder] ?? '未配置演示图片')">
            <div v-if="column.key === 'processes'" class="board-process-cell" tabindex="0" aria-label="工序节点，超出时可横向滚动"><ol class="board-process-track">
            <li v-for="(process, index) in order.processes" :key="index" :class="{ 'is-complete': status(process) === '已完成', 'is-working': status(process) === '进行中' }" :aria-label="`${process.label}：${status(process)}，${process.completed}/${process.total}`">
              <div class="board-process-step">
              <span class="board-process-node" :class="{ 'has-long-value': process.completed > 999 }" :title="`${status(process)} ${process.completed}/${process.total}`">{{ process.completed || '' }}</span>
              <span class="board-process-label" :title="process.label">{{ process.label }}</span>
              </div>
            </li>
            </ol></div>
            <span v-else-if="column.key === 'image'" aria-label="演示产品未配置图片">—</span>
            <span v-else-if="column.key === 'priority'" class="board-priority" :class="{ 'is-urgent': order.priority === '紧急' }">{{ order.priority }}</span>
            <template v-else>{{ order[column.key as keyof BoardOrder] }}</template>
          </td>
        </tr></tbody>
      </table>
      <p v-if="filtered.length === 0" class="board-empty" role="status">暂无匹配工单</p>
    </div>
  </div>
</template>
