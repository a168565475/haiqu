<script setup lang="ts">
import { computed } from 'vue'
import BomLineImageSummary from '@/components/BomLineImageSummary.vue'
import type { BomDetail } from '@/types/bom'
import { bomPreviewCell, bomPreviewColumns, type BomPreviewColumn, type BomPreviewSection } from '@/utils/bomPreview'

const props = defineProps<{ bom: BomDetail; sections: BomPreviewSection[] }>()
const sectionOrder = ['管材类', '五金件', '塑料件类', '面料类', '裁剪明细', '辅料类', '包材类']
const sections = computed(() => [...props.sections].sort((a, b) => {
  const rank = (title: string) => sectionOrder.includes(title) ? sectionOrder.indexOf(title) : sectionOrder.length
  return rank(a.title) - rank(b.title)
}))
const totalLines = computed(() => sections.value.reduce((sum, section) => sum + section.lines.length, 0))
function printWeight(column: BomPreviewColumn) {
  if (column.key === 'line_number') return 48
  if (column.key === 'unit') return 54
  if (column.key === 'images') return 90
  if (column.key === 'notes') return 160
  return column.width
}
function columnWidth(column: BomPreviewColumn, section: BomPreviewSection) {
  const total = bomPreviewColumns(section).reduce((sum, item) => sum + printWeight(item), 0)
  return `${printWeight(column) / total * 100}%`
}
</script>

<template>
  <article class="bom-print-document paper" aria-label="BOM 打印文档">
    <header class="bom-print-heading">
      <div class="bom-print-title">BOM 物料明细</div>
      <div>{{ bom.bom_number }}</div>
    </header>
    <section v-for="(section, sectionIndex) in sections" :key="section.id || section.title" class="bom-print-section" :class="{ 'bom-print-section--short': section.lines.length <= 4 }">
      <table :aria-label="section.title">
        <colgroup><col v-for="column in bomPreviewColumns(section)" :key="column.key" :style="{ width: columnWidth(column, section) }"></colgroup>
        <thead>
          <tr><th :colspan="bomPreviewColumns(section).length" class="bom-print-section-title">{{ section.title }}（{{ section.lines.length }} 条）</th></tr>
          <tr><th v-for="column in bomPreviewColumns(section)" :key="column.key" scope="col">{{ column.label }}</th></tr>
        </thead>
        <tbody>
          <tr v-for="(line, index) in section.lines" :key="line.id || `${sectionIndex}-${index}`">
            <td v-for="column in bomPreviewColumns(section)" :key="column.key" :data-field="column.key">
              <template v-if="column.key === 'line_number'">{{ index + 1 }}</template>
              <template v-else-if="column.key === 'images'">
                <BomLineImageSummary v-if="line.images?.length || line.draft_images?.length" :line="line" />
                <template v-else>—</template>
              </template>
              <template v-else>{{ bomPreviewCell(line, column.key, section, bom.order_quantity, sections) }}</template>
            </td>
          </tr>
          <tr v-if="!section.lines.length"><td :colspan="bomPreviewColumns(section).length" class="bom-print-empty">暂无明细</td></tr>
        </tbody>
        <tfoot v-if="sectionIndex === sections.length - 1"><tr><td :colspan="bomPreviewColumns(section).length" class="bom-print-footer">{{ bom.bom_number }} · 共 {{ totalLines }} 条用料</td></tr></tfoot>
      </table>
    </section>
  </article>
</template>

<style lang="scss">
.bom-print-document { display: none; }
@page bom-document {
  size: A4 landscape;
  margin: 10mm 9mm 13mm;
  @bottom-left { content: 'BOM 物料明细'; font: 8pt 'Microsoft YaHei', sans-serif; color: #555; }
  @bottom-right { content: '第 ' counter(page) ' 页 / 共 ' counter(pages) ' 页'; font: 8pt 'Microsoft YaHei', sans-serif; color: #555; }
}
@media print {
  html:has(.bom-print-document) { min-height: 0 !important; height: auto !important; background: #fff !important; }
  // 只在有 BOM 打印文档的页面解除应用滚动/弹性布局，确保浏览器能够正常分页。
  body:has(.bom-print-document) {
    page: bom-document;
    margin: 0 !important; padding: 0 !important; min-height: 0 !important; height: auto !important; background: #fff !important;
    #app, .erp-layout, .erp-layout__body, .erp-layout__workspace, .erp-layout__main, [data-page-container], .page-container__content, .bom-editor-page, .bom-preview-page {
      display: block !important; width: 100% !important; height: auto !important; min-height: 0 !important; max-height: none !important;
      overflow: visible !important; margin: 0 !important; padding: 0 !important; border: 0 !important; border-radius: 0 !important;
      background: #fff !important; box-shadow: none !important; backdrop-filter: none !important;
    }
    .erp-layout__header, .erp-layout__sidebar, .bom-editor-page > :not(.bom-print-document), .bom-preview-page > :not(.bom-print-document) { display: none !important; }
  }
  .bom-print-document {
    display: block; page: bom-document; color: #111; background: #fff;
    font: 9pt/1.45 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
    print-color-adjust: exact; -webkit-print-color-adjust: exact;
    .bom-print-heading { text-align: center; margin-bottom: 4mm; }
    .bom-print-title { margin: 0 0 1mm; font-size: 12pt; font-weight: 700; line-height: 1.4; }
    .bom-print-section { margin: 0 0 3mm; }
    .bom-print-section--short { break-inside: avoid; }
    table { width: 100%; table-layout: fixed; border-collapse: collapse; }
    thead { display: table-header-group; }
    tfoot { display: table-row-group; }
    tr { break-inside: avoid; }
    th, td { padding: 1mm 1.2mm; border: .2mm solid #888; vertical-align: middle; text-align: left; overflow-wrap: anywhere; }
    th { background: #eee; font-weight: 600; }
    .bom-print-section-title { font-size: 10pt; background: #e3e3e3; }
    .bom-print-empty { text-align: center; color: #666; }
    .bom-print-footer { font-size: 8pt; color: #444; }
    .bom-line-image-summary { flex-wrap: wrap; min-height: 0; white-space: normal; font-size: 7pt; color: #333; }
    .image-thumbnails { flex-wrap: wrap; }
    .image-thumbnails .el-image { width: 10mm; height: 10mm; }
  }
}
</style>
