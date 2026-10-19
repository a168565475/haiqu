<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ArrowLeft, Printer } from '@element-plus/icons-vue'

import { fetchBom } from '@/api/boms'
import BomLineImageSummary from '@/components/BomLineImageSummary.vue'
import BomPrintDocument from '@/components/boms/BomPrintDocument.vue'
import { useAuthStore } from '@/stores/auth'
import type { BomDetail, BomLine, BomSection } from '@/types/bom'
import { bomPreviewCell, bomPreviewColumns } from '@/utils/bomPreview'
import { cuttingCalculation, legacyPipeCuttingValues } from '@/utils/bomCuttingQuantities'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const loading = ref(true)
const errorMessage = ref('')
const bom = ref<BomDetail | null>(null)
const activeSectionIndex = ref(0)
const documentScroller = ref<HTMLElement | null>(null)
const canEdit = computed(() => authStore.hasPermission('boms.change_bom'))
const bomId = computed(() => String(route.params.bomId || ''))
const sectionOrder = ['管材类', '五金件', '塑料件类', '面料类', '裁剪明细', '辅料类', '包材类']
const sections = computed(() => [...(bom.value?.sections || [])].sort((left, right) => {
  const rank = (title: string) => sectionOrder.includes(title) ? sectionOrder.indexOf(title) : sectionOrder.length
  return rank(left.title) - rank(right.title)
}))
const totalLines = computed(() => sections.value.reduce((sum, section) => sum + section.lines.length, 0))
const previewStatusLabel = computed(() => bom.value?.status === 'VERIFIED' ? '已确认' : '草稿')
const quantityChanged = computed(() => Number(bom.value?.order_quantity) !== Number(bom.value?.current_order_quantity))

function number(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(parsed) : String(value)
}
function lineValue(line: BomLine, key: string, section: BomSection) {
  return bomPreviewCell(line, key, section, bom.value?.order_quantity || '', sections.value)
}
function cuttingNote(line: BomLine, section: BomSection) {
  if (!/裁剪|裁片/.test(section.title)) return ''
  if (legacyPipeCuttingValues(line)) return '管材旧口径：片数、米/片和套数沿用编辑页只读试算，仍按原单位流转。'
  return cuttingCalculation(line, bom.value?.order_quantity).error
}
function tableWidth(section: BomSection) {
  return `${bomPreviewColumns(section).reduce((sum, column) => sum + column.width, 0)}px`
}
function sectionAnchor(index: number) { return `bom-section-${index + 1}` }
function scrollToSection(index: number) {
  const container = documentScroller.value
  const target = document.getElementById(sectionAnchor(index))
  if (!container || !target) return
  activeSectionIndex.value = index
  container.scrollTo({ top: container.scrollTop + target.getBoundingClientRect().top - container.getBoundingClientRect().top - 16, behavior: 'smooth' })
}
function updateActiveSection() {
  const container = documentScroller.value
  if (!container) return
  if (container.scrollTop > 0 && container.scrollTop + container.clientHeight >= container.scrollHeight - 2) {
    activeSectionIndex.value = sections.value.length - 1
    return
  }
  const top = container.getBoundingClientRect().top + 40
  const index = sections.value.findIndex((_, sectionIndex) => {
    const element = document.getElementById(sectionAnchor(sectionIndex))
    return element && element.getBoundingClientRect().bottom > top
  })
  if (index >= 0) activeSectionIndex.value = index
}
function errorText(error: unknown) {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : 'BOM 预览加载失败。'
  if (!error.response) return '网络连接异常，请检查后重试。'
  const data = error.response.data as { detail?: string; error?: { message?: string } }
  return data.error?.message || data.detail || 'BOM 预览加载失败。'
}
async function loadPage() {
  loading.value = true
  errorMessage.value = ''
  try { bom.value = await fetchBom(bomId.value) }
  catch (error) { errorMessage.value = errorText(error) }
  finally { loading.value = false }
}
function goBack() {
  void router.push(canEdit.value ? { name: 'bom-edit', params: { bomId: bomId.value } } : { name: 'boms' })
}
function printPage() { window.print() }
onMounted(loadPage)
</script>

<template>
  <section class="bom-preview-page erp-glass-detail" aria-label="BOM 预览与打印">
    <BomPrintDocument v-if="bom && !loading && !errorMessage" :bom="bom" :sections="sections" />
    <div v-if="loading" class="preview-loading" v-loading="true" />
    <ElResult v-else-if="errorMessage" icon="error" title="BOM 预览加载失败" :sub-title="errorMessage">
      <template #extra><ElButton type="primary" @click="loadPage">重新加载</ElButton></template>
    </ElResult>
    <template v-else-if="bom">
      <header class="preview-header">
        <div class="preview-title-line">
          <h1>BOM预览</h1>
          <strong>{{ bom.bom_number }} · V{{ bom.version_number }}</strong>
          <span class="preview-status-tag" :class="{ verified: bom.status === 'VERIFIED' }">{{ previewStatusLabel }}</span>
          <span class="readonly-tag">只读</span>
        </div>
        <div class="header-actions">
          <ElButton :icon="ArrowLeft" @click="goBack">{{ canEdit ? '返回编辑' : '返回列表' }}</ElButton>
          <ElButton type="primary" :icon="Printer" @click="printPage">打印</ElButton>
        </div>
      </header>
      <div class="preview-shell">
        <aside class="document-aside" aria-label="BOM 物料分类">
          <nav class="document-outline" aria-label="物料分区目录">
            <h2>物料分类</h2>
            <button v-for="(section, index) in sections" :key="section.id" type="button" :class="{ active: index === activeSectionIndex }" :aria-current="index === activeSectionIndex ? 'location' : undefined" @click="scrollToSection(index)">
              <span>{{ section.title }}</span><b>（{{ section.lines.length }}）</b>
            </button>
            <div class="outline-total"><span>合计</span><b>{{ totalLines }} 条</b></div>
          </nav>
        </aside>
        <main ref="documentScroller" class="paper-scroll" aria-label="BOM 只读文档" @scroll="updateActiveSection">
          <article class="paper">
            <header class="paper-header">
              <h2>浙江嗨趣休闲用品有限公司</h2>
              <h3>产品用料清单（BOM）</h3>
            </header>
            <section class="document-facts" aria-label="BOM 基本信息">
              <div><span>BOM编号</span><b>{{ bom.bom_number }}</b></div>
              <div><span>版本 / 状态</span><b>V{{ bom.version_number }} · {{ previewStatusLabel }}</b></div>
              <div><span>生产任务单</span><b>{{ bom.production_task_number || '—' }}</b></div>
              <div><span>销售订单</span><b>{{ bom.order_number || '—' }}</b></div>
              <div><span>客户</span><b>{{ bom.customer_name || '—' }}</b></div>
              <div><span>产品编码</span><b>{{ bom.product_code_snapshot || bom.product_number_snapshot || '—' }}</b></div>
              <div><span>产品名称</span><b>{{ bom.product_name_snapshot || '—' }}</b></div>
              <div><span>产品规格</span><b>{{ bom.specification_snapshot || '—' }}</b></div>
              <div><span>BOM计算数量</span><b>{{ number(bom.order_quantity) }}</b></div>
              <div v-if="quantityChanged"><span>当前计划数量</span><b>{{ number(bom.current_order_quantity) }}</b></div>
            </section>
            <p v-if="quantityChanged" class="quantity-note">当前计划数量与本版 BOM 不同，以下计算沿用本版 BOM 数量 {{ number(bom.order_quantity) }}。</p>
            <section v-for="(section, sectionIndex) in sections" :id="sectionAnchor(sectionIndex)" :key="section.id" class="paper-section" :data-section-title="section.title">
              <h4>{{ section.title }}<span>{{ section.lines.length }} 条</span></h4>
              <div class="table-frame" tabindex="0" role="region" :aria-label="`${section.title}明细表格`">
                <table class="bom-table" :style="{ minWidth: tableWidth(section) }">
                  <colgroup><col v-for="column in bomPreviewColumns(section)" :key="column.key" :style="{ width: `${column.width}px` }"></colgroup>
                  <thead><tr><th v-for="column in bomPreviewColumns(section)" :key="column.key" scope="col">{{ column.label }}</th></tr></thead>
                  <tbody>
                    <tr v-for="(line, lineIndex) in section.lines" :key="line.id">
                      <td v-for="column in bomPreviewColumns(section)" :key="column.key" :data-field="column.key">
                        <template v-if="column.key === 'line_number'">{{ lineIndex + 1 }}</template>
                        <BomLineImageSummary v-else-if="column.key === 'images'" :line="line" />
                        <template v-else>{{ lineValue(line, column.key, section) }}<small v-if="column.key === 'part_name' && cuttingNote(line, section)" class="line-note">{{ cuttingNote(line, section) }}</small></template>
                      </td>
                    </tr>
                    <tr v-if="!section.lines.length"><td :colspan="bomPreviewColumns(section).length" class="empty-row">暂无明细</td></tr>
                  </tbody>
                </table>
              </div>
            </section>
            <footer class="paper-footer">{{ bom.bom_number }} · 共 {{ totalLines }} 条用料</footer>
          </article>
        </main>
      </div>
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/theme/detail' as detail;
.bom-preview-page { min-width: 0; color: var(--erp-color-text-primary); }
.preview-loading { min-height: 480px; }
.preview-header, .preview-title-line, .header-actions { display: flex; align-items: center; gap: 12px; }
.preview-header { flex-wrap: wrap; justify-content: space-between; margin-bottom: 14px; }
.preview-title-line { flex-wrap: wrap; min-width: 0; }
.preview-title-line h1 { margin: 0; font: 700 32px/44px var(--erp-font-body); }
.preview-title-line strong { font-size: 16px; }
.preview-status-tag, .readonly-tag { padding: 4px 10px; border-radius: 4px; font-size: 12px; background: var(--erp-tag-warning-background); color: var(--erp-tag-warning-text); }
.preview-status-tag.verified, .readonly-tag { background: var(--erp-tag-success-background); color: var(--erp-tag-success-text); }
.preview-shell { display: grid; grid-template-columns: 176px minmax(0, 1fr); gap: 14px; height: calc(100dvh - 170px); min-height: 320px; }
.document-aside { @include detail.surface; align-self: start; max-height: 100%; overflow: auto; padding: 12px 6px; }
.document-outline h2 { margin: 0 10px 12px; font-size: 14px; }
.document-outline button { display: flex; align-items: center; justify-content: space-between; width: 100%; min-height: 42px; padding: 0 10px; border: 0; border-left: 3px solid transparent; border-radius: 4px; background: transparent; color: var(--erp-color-text-regular); font: inherit; font-size: 13px; cursor: pointer; }
.document-outline button:hover, .document-outline button.active { border-left-color: var(--erp-color-brand); background: var(--erp-color-selected); color: var(--erp-color-brand); }
.document-outline button:focus-visible, .table-frame:focus-visible { outline: 2px solid var(--erp-color-brand); outline-offset: -2px; }
.document-outline button b { font-weight: 500; }
.outline-total { display: flex; justify-content: space-between; margin: 10px 10px 0; padding-top: 12px; border-top: 1px solid var(--erp-color-border-subtle); font-size: 12px; }
.paper-scroll { @include detail.surface; min-height: 0; overflow: auto; padding: 16px; }
.paper { min-width: 0; color: var(--erp-color-text-primary); font-family: var(--erp-font-body); }
.paper-header { display: none; }
.document-facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px 20px; padding-bottom: 18px; border-bottom: 1px solid var(--erp-color-border-subtle); }
.document-facts div { min-width: 0; }
.document-facts span { display: block; margin-bottom: 5px; color: var(--erp-color-text-secondary); font-size: 12px; }
.document-facts b { font-size: 13px; font-weight: 500; overflow-wrap: anywhere; }
.quantity-note, .line-note { color: var(--erp-color-text-secondary); font-size: 12px; line-height: 1.5; }
.line-note { display: block; margin-top: 4px; }
.paper-section { min-width: 0; margin-top: 20px; }
.paper-section h4 { display: flex; align-items: center; gap: 12px; margin: 0 0 10px; font-size: 16px; }
.paper-section h4 span { color: var(--erp-color-text-secondary); font-size: 12px; font-weight: 400; }
.table-frame { overflow: auto; border: 1px solid var(--erp-table-border); border-radius: var(--erp-radius-control); background: var(--erp-table-background); }
.bom-table { width: 100%; border-spacing: 0; table-layout: fixed; color: var(--erp-table-text); font-size: 12px; }
.bom-table th, .bom-table td { box-sizing: border-box; padding: 8px 12px; border-right: 1px solid var(--erp-table-border); border-bottom: 1px solid var(--erp-table-border); line-height: 20px; text-align: left; vertical-align: middle; overflow-wrap: anywhere; }
.bom-table th { height: 44px; background: var(--erp-table-header-background); color: var(--erp-table-header-text); font-size: 11px; font-weight: 600; }
.bom-table td { height: 40px; background: var(--erp-table-background); }
.bom-table tbody tr:hover td { background: var(--erp-table-hover); }
.bom-table th:last-child, .bom-table td:last-child { border-right: 0; }
.bom-table tbody tr:last-child td { border-bottom: 0; }
.empty-row { text-align: center !important; color: var(--erp-color-text-secondary); }
.paper-footer { margin-top: 20px; color: var(--erp-color-text-secondary); font-size: 12px; }
@media (max-width: 760px) {
  .preview-shell { grid-template-columns: 130px minmax(0, 1fr); height: calc(100dvh - 210px); gap: 10px; }
  .document-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .paper-scroll { padding: 12px; }
}
</style>
