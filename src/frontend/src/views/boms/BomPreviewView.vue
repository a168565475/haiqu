<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ArrowLeft, Printer } from '@element-plus/icons-vue'

import { fetchBom } from '@/api/boms'
import { useAuthStore } from '@/stores/auth'
import type { BomDetail, BomLine, BomSection } from '@/types/bom'
import { cuttingCalculation } from '@/utils/bomCuttingQuantities'

type PrintColumn = { key: string; label: string; width?: string }

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const loading = ref(true)
const errorMessage = ref('')
const bom = ref<BomDetail | null>(null)
const canEdit = computed(() => authStore.hasPermission('boms.change_bom'))
const bomId = computed(() => String(route.params.bomId || ''))
const totalLines = computed(() => bom.value?.sections.reduce((sum, section) => sum + section.lines.length, 0) || 0)
const previewStatusLabel = computed(() => bom.value?.status === 'VERIFIED' ? '已确认' : '草稿')
const documentOutlineGroups = computed(() => {
  const sections = bom.value?.sections || []
  const definitions = [
    { label: '型材', patterns: [/管材|型材/] },
    { label: '五金', patterns: [/五金/] },
    { label: '塑料', patterns: [/塑料/] },
    { label: '半成品', patterns: [/裁剪|裁片|半成品/] },
    { label: '面辅料', patterns: [/辅料|面料/] },
    { label: '包材', patterns: [/包材|包装/] },
  ]
  return definitions.map((definition) => {
    const indexes = sections.flatMap((section, index) => definition.patterns.some((pattern) => pattern.test(section.title)) ? [index] : [])
    return {
      ...definition,
      indexes,
      count: indexes.reduce((sum, index) => sum + (sections[index]?.lines.length || 0), 0),
    }
  })
})

function number(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return '—'
  const parsed = Number(value)
  return Number.isFinite(parsed)
    ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(parsed)
    : String(value)
}

function date(value: string | null | undefined) {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value || '—'
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(parsed)
}

function sectionName(section: BomSection) {
  const title = section.title.replace(/类$|件$/g, '')
  if (/管材|型材/.test(title)) return '型材'
  if (/五金/.test(title)) return '五金'
  if (/面料/.test(title)) return '面料'
  if (/辅料/.test(title)) return '辅料'
  if (/塑料/.test(title)) return '塑料'
  if (/包材|包装/.test(title)) return '包材'
  if (/裁剪|裁片/.test(title)) return '裁剪'
  return title || section.section_type_display
}

function sectionColumns(section: BomSection): PrintColumn[] {
  const common = (codeKey = 'material_code'): PrintColumn[] => [
    { key: 'line_number', label: '序号', width: '46px' },
    { key: codeKey, label: codeKey === 'source_serial' ? '原表编号' : '物料编码', width: '112px' },
    { key: 'material_name', label: '物料名称', width: '140px' },
    { key: 'specification', label: '规格 / 型号', width: '140px' },
    { key: 'unit', label: '单位', width: '58px' },
  ]
  if (section.section_type === 'PROFILE') {
    return [
      ...common('source_serial'),
      { key: 'tube_coating_color', label: '喷塑颜色', width: '92px' },
      { key: 'length_value', label: '切割长度mm', width: '88px' },
      { key: 'suggested_purchase_meters', label: '建议采购米数', width: '108px' },
      { key: 'unit_consumption', label: '单件用量', width: '88px' },
      { key: 'total_consumption', label: '总需求量', width: '98px' },
      { key: 'tube_cut_piece_count', label: '切割支数', width: '82px' },
      { key: 'tube_cut_length_m', label: '原材料长度（m）', width: '108px' },
      { key: 'branch_count', label: '采购根数', width: '82px' },
      { key: 'notes', label: '备注', width: '108px' },
    ]
  }
  if (/五金/.test(section.title)) {
    return [
      ...common('hardware_material_number'),
      { key: 'hardware_color', label: '颜色', width: '86px' },
      { key: 'unit_consumption', label: '单件用量', width: '80px' },
      { key: 'total_consumption', label: '总需求量', width: '92px' },
      { key: 'unit_material_weight_kg', label: '单件重量kg', width: '88px' },
      { key: 'powder_coating_color', label: '喷塑颜色', width: '92px' },
      { key: 'notes', label: '备注', width: '105px' },
    ]
  }
  if (/塑料/.test(section.title)) {
    return [
      ...common('plastic_material_number'),
      { key: 'plastic_color', label: '颜色', width: '92px' },
      { key: 'unit_consumption', label: '单件用量', width: '86px' },
      { key: 'total_consumption', label: '总需求量', width: '96px' },
      { key: 'unit_material_weight_kg', label: '单件重量kg', width: '90px' },
      { key: 'notes', label: '备注', width: '116px' },
    ]
  }
  if (/辅料/.test(section.title) && !/面料/.test(section.title)) {
    return [
      ...common(),
      { key: 'material', label: '材质', width: '90px' },
      { key: 'accessory_color', label: '颜色', width: '92px' },
      { key: 'unit_consumption', label: '单件用量', width: '86px' },
      { key: 'total_consumption', label: '总需求量', width: '96px' },
      { key: 'notes', label: '备注', width: '125px' },
    ]
  }
  if (/面料/.test(section.title)) {
    return [
      ...common(),
      { key: 'fabric_width', label: '门幅', width: '78px' },
      { key: 'fabric_color_card', label: '色卡', width: '78px' },
      { key: 'fabric_color_code', label: '色号', width: '88px' },
      { key: 'fabric_color_name', label: '颜色', width: '88px' },
      { key: 'unit_consumption', label: '单件用量', width: '84px' },
      { key: 'total_consumption', label: '总需求量', width: '94px' },
      { key: 'notes', label: '备注', width: '105px' },
    ]
  }
  if (/包材|包装/.test(section.title)) {
    return [
      ...common('packaging_material_number'),
      { key: 'packaging_color', label: '颜色', width: '90px' },
      { key: 'units_per_box', label: '每箱数', width: '76px' },
      { key: 'unit_consumption', label: '单件用量', width: '84px' },
      { key: 'total_consumption', label: '总需求量', width: '94px' },
      { key: 'notes', label: '备注', width: '115px' },
    ]
  }
  if (/裁剪|裁片/.test(section.title)) {
    return [
      { key: 'line_number', label: '序号', width: '34px' },
      { key: 'material_name', label: '裁剪名称 / 资料', width: '95px' },
      { key: 'fabric_source_line_id', label: '来源面料', width: '90px' },
      { key: 'unit', label: '单位', width: '40px' },
      { key: 'cutting_pieces_per_set', label: '裁片量（片/套）', width: '78px' },
      { key: 'fabric_meters_per_piece', label: '单个用量（米/片）', width: '80px' },
      { key: 'cutting_sets_per_product', label: '每成品套数（套/成品）', width: '90px' },
      { key: 'cutting_meters_per_set', label: '每套耗米（米/套）', width: '85px' },
      { key: 'cutting_order_sets', label: '订单套数（套）', width: '72px' },
      { key: 'cutting_order_pieces', label: '订单片数（片）', width: '72px' },
      { key: 'cutting_total_meters', label: '订单耗米（米）', width: '78px' },
      ...(section.lines.some(line => cuttingCalculation(line, bom.value?.order_quantity).mode === 'legacy') ? [{ key: 'cutting_legacy_quantity', label: '旧裁片量（原值）', width: '78px' }] : []),
      { key: 'notes', label: '备注', width: '118px' },
    ]
  }
  return [
    ...common(),
    { key: 'unit_consumption', label: '单件用量', width: '92px' },
    { key: 'total_consumption', label: '总需求量', width: '100px' },
    { key: 'notes', label: '备注', width: '150px' },
  ]
}

function materialCode(line: BomLine) {
  return line.hardware_material_number
    || line.plastic_material_number
    || line.packaging_material_number
    || line.cutting_material_number
    || '—'
}

function lineValue(line: BomLine, key: string) {
  if (key === 'fabric_source_line_id') return bom.value?.sections.flatMap((item) => item.lines).find((item) => item.id === line.fabric_source_line_id)?.part_name || '待关联'
  if (['tube_cut_length_m', 'suggested_purchase_meters'].includes(key)) return String(line[key as keyof BomLine] || '—')

  if (key === 'line_number') return String(line.line_number)
  if (key === 'material_code') return materialCode(line)
  if (key === 'material_name') return line.part_name || line.material || line.raw_material || '—'
  if (['cutting_pieces_per_set', 'fabric_meters_per_piece', 'cutting_sets_per_product', 'cutting_meters_per_set', 'cutting_order_sets', 'cutting_order_pieces', 'cutting_total_meters', 'cutting_legacy_quantity'].includes(key)) {
    const calculation = cuttingCalculation(line, bom.value?.order_quantity)
    if (key === 'cutting_legacy_quantity') return calculation.mode === 'legacy' ? `${line.cut_piece_quantity || '—'}（旧需求口径）` : '—'
    if (key === 'cutting_meters_per_set' && calculation.mode === 'legacy') return line.fabric_meters_per_set ? `${line.fabric_meters_per_set}（原值）` : '待补充'
    if (calculation.mode !== 'valid') return calculation.mode === 'legacy' ? '待补充' : '参数待检查'
    const values: Record<string, string> = {
      cutting_pieces_per_set: calculation.piecesPerSet,
      fabric_meters_per_piece: calculation.metersPerPiece,
      cutting_sets_per_product: calculation.setsPerProduct,
      cutting_meters_per_set: calculation.metersPerSet,
      cutting_order_sets: calculation.orderSets,
      cutting_order_pieces: calculation.orderPieces,
      cutting_total_meters: calculation.totalMeters,
    }
    return values[key] || '—'
  }
  const rawValue = line[key as keyof BomLine]
  if (['unit_consumption', 'total_consumption', 'cut_piece_quantity', 'tube_cut_piece_count', 'tube_cut_length_m', 'branch_count', 'unit_material_weight_kg', 'units_per_box'].includes(key)) {
    return number(typeof rawValue === 'string' || typeof rawValue === 'number' ? rawValue : null)
  }
  return typeof rawValue === 'string' && rawValue ? rawValue : '—'
}

function sectionAnchor(index: number) { return `bom-section-${index + 1}` }
function scrollToSection(index: number) { document.getElementById(sectionAnchor(index))?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
function scrollToGroup(indexes: number[]) {
  if (indexes.length) scrollToSection(indexes[0])
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
  <section class="bom-preview-page" aria-label="BOM 预览与打印">
    <div v-if="loading" class="preview-loading" v-loading="true" />
    <ElResult v-else-if="errorMessage" icon="error" title="BOM 预览加载失败" :sub-title="errorMessage">
      <template #extra><ElButton type="primary" @click="loadPage">重新加载</ElButton></template>
    </ElResult>

    <template v-else-if="bom">
      <header class="preview-header">
        <div class="preview-heading">
          <div class="preview-title-line">
            <h1>BOM预览与打印</h1>
            <strong>{{ bom.bom_number }}&nbsp; V{{ bom.version_number }}</strong>
            <span class="preview-status-tag" :class="{ verified: bom.status === 'VERIFIED' }">{{ previewStatusLabel }}</span>
            <span class="readonly-tag">只读</span>
          </div>
          <p>来源：{{ bom.production_task_number || '—' }}　/　客户：{{ bom.customer_name || '—' }}　/　产品：{{ bom.product_code_snapshot || bom.product_number_snapshot || '—' }} {{ bom.product_name_snapshot || '—' }}　/　计划生产数量：{{ number(bom.current_order_quantity) }}</p>
        </div>
        <div class="header-actions">
          <ElButton :icon="ArrowLeft" @click="goBack">{{ canEdit ? '返回编辑' : '返回列表' }}</ElButton>
          <ElButton type="primary" :icon="Printer" @click="printPage">打印</ElButton>
        </div>
      </header>

      <div class="preview-shell">
        <aside class="document-aside" aria-label="BOM 文档信息和目录">
          <section class="aside-section">
            <h2>文档信息</h2>
            <dl>
              <div><dt>BOM编号</dt><dd>{{ bom.bom_number }}</dd></div>
              <div><dt>版本 / 状态</dt><dd>V{{ bom.version_number }} · {{ previewStatusLabel }}</dd></div>
              <div><dt>生产任务单</dt><dd>{{ bom.production_task_number || '—' }}</dd></div>
              <div><dt>销售订单</dt><dd>{{ bom.order_number || '—' }}</dd></div>
              <div><dt>客户</dt><dd>{{ bom.customer_name || '—' }}</dd></div>
              <div><dt>产品名称</dt><dd>{{ bom.product_code_snapshot || bom.product_number_snapshot || '—' }} {{ bom.product_name_snapshot || '—' }}</dd></div>
              <div><dt>生产数量</dt><dd>{{ number(bom.current_order_quantity) }}</dd></div>
              <div><dt>确认状态</dt><dd><span class="aside-status" :class="{ verified: bom.status === 'VERIFIED' }">{{ previewStatusLabel }}</span></dd></div>
              <div><dt>确认日期</dt><dd>{{ date(bom.confirmed_at) }}</dd></div>
            </dl>
          </section>
          <section class="aside-section document-outline">
            <h2>文档目录</h2>
            <button v-for="(group, index) in documentOutlineGroups" :key="group.label" type="button" :class="{ active: index === 0 }" :disabled="!group.indexes.length" @click="scrollToGroup(group.indexes)">
              <span>{{ group.label }}</span><b>（{{ group.count }}）</b>
            </button>
            <div class="outline-total"><span>合计</span><b>{{ totalLines }} 条</b></div>
          </section>
        </aside>

        <main class="paper-scroll" aria-label="BOM 只读文档">
          <article class="paper">
            <header class="paper-header">
              <div class="paper-corner">{{ bom.bom_number }} · V{{ bom.version_number }} · {{ previewStatusLabel }}</div>
              <h2>浙江嗨趣休闲用品有限公司</h2>
              <h3>产品用料清单（BOM）</h3>
            </header>
            <section class="document-facts" aria-label="BOM 基本信息">
              <div><span>BOM编号</span><b>{{ bom.bom_number }}</b></div><div><span>版本 / 状态</span><b>V{{ bom.version_number }} · {{ previewStatusLabel }}</b></div><div><span>生产任务单</span><b>{{ bom.production_task_number || '—' }}</b></div>
              <div><span>销售订单</span><b>{{ bom.order_number || '—' }}</b></div><div><span>客户</span><b>{{ bom.customer_name || '—' }}</b></div><div><span>产品编码</span><b>{{ bom.product_code_snapshot || bom.product_number_snapshot || '—' }}</b></div>
              <div><span>产品名称</span><b>{{ bom.product_name_snapshot || '—' }}</b></div><div><span>产品规格</span><b>{{ bom.specification_snapshot || '—' }}</b></div><div><span>生产数量</span><b>{{ number(bom.current_order_quantity) }}</b></div>
            </section>

            <section v-for="(section, sectionIndex) in bom.sections" :id="sectionAnchor(sectionIndex)" :key="section.id" class="paper-section">
              <h4>{{ ['一', '二', '三', '四', '五', '六', '七'][sectionIndex] || sectionIndex + 1 }}、{{ sectionName(section) }}（{{ section.lines.length }}行）</h4>
              <p v-if="/裁剪|裁片/.test(section.title)" class="cutting-formula-note">每套耗米＝裁片量 × 单个用量；订单套数＝BOM 订单 {{ number(bom.order_quantity) }} × 每成品套数；订单片数＝订单套数 × 裁片量；订单耗米＝订单套数 × 每套耗米。待补充的旧记录保留原每套耗米和旧裁片量，不反推新参数。</p>
              <div class="table-frame"><table class="bom-table">
                <colgroup><col v-for="column in sectionColumns(section)" :key="column.key" :style="{ width: column.width }"></colgroup>
                <thead><tr><th v-for="column in sectionColumns(section)" :key="column.key">{{ column.label }}</th></tr></thead>
                <tbody>
                  <tr v-for="line in section.lines" :key="line.id"><td v-for="column in sectionColumns(section)" :key="column.key">{{ lineValue(line, column.key) }}<template v-if="column.key === 'material_name' && /裁剪|裁片/.test(section.title)"><small>品号 {{ line.cutting_material_number || '—' }}</small><small>规格 {{ line.specification || '—' }}</small><small>颜色 {{ line.cutting_color || '—' }}</small></template><small v-if="column.key === 'notes' && line.images?.length">图片 {{ line.images.length }} 张</small></td></tr>
                  <tr v-if="!section.lines.length"><td :colspan="sectionColumns(section).length" class="empty-row">暂无明细</td></tr>
                </tbody>
              </table></div>
            </section>

            <footer class="paper-footer"><span>备注：本 BOM 仅用于生产开工和生产领料，不直接作为采购订单依据。</span><span>{{ bom.bom_number }} · 共 {{ totalLines }} 条用料</span></footer>
          </article>
        </main>
      </div>
    </template>
  </section>
</template>

<style scoped lang="scss">
.cutting-formula-note { margin: 4px 0 6px; color: #777; font-size: 10px; line-height: 1.5; }
.bom-preview-page{min-width:0;margin:-8px auto 0;color:#1f1d18;--el-color-primary:#d94a1f}.preview-loading{min-height:760px}.preview-header{display:flex;min-height:94px;align-items:center;justify-content:space-between;gap:28px}.preview-heading{min-width:0}.preview-title-line{display:flex;align-items:center;gap:12px;min-width:0}.preview-heading h1{margin:0;font-family:'Noto Serif SC','Songti SC',serif;font-size:32px;line-height:1.2}.preview-title-line>strong{font-family:'Noto Serif SC','Songti SC',serif;font-size:20px;white-space:nowrap}.preview-status-tag,.readonly-tag,.aside-status{display:inline-flex;min-height:24px;align-items:center;justify-content:center;padding:0 10px;border-radius:4px;background:#fff0d9;color:#b96b18;font-size:12px;line-height:1}.preview-status-tag.verified,.aside-status.verified{background:#e8f6ec;color:#31834b}.readonly-tag{border:1px solid #9bcfaa;background:#f6fff8;color:#31834b}.preview-heading p{margin:8px 0 0;color:#6f6a61;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.header-actions{display:flex;flex:0 0 auto;gap:10px}.header-actions :deep(.el-button){min-width:112px}.preview-shell{display:grid;grid-template-columns:268px minmax(0,1fr);height:calc(100vh - 224px);min-height:660px;gap:24px}.document-aside{overflow:auto;border:1px solid #ddd6c9;border-radius:5px;background:#fcfbf7}.aside-section{padding:20px 18px}.aside-section+.aside-section{border-top:1px solid #e5ded2}.aside-section h2{margin:0 0 15px;font-family:'Noto Serif SC','Songti SC',serif;font-size:20px}.aside-section dl{display:grid;gap:13px;margin:0}.aside-section dl div{display:grid;grid-template-columns:78px minmax(0,1fr);gap:8px;align-items:start}.aside-section dt{color:#6f6a61;font-size:12px}.aside-section dd{margin:0;font-size:12px;line-height:1.55;overflow-wrap:anywhere}.aside-status{min-height:20px;padding:0 8px}.document-outline{display:grid;gap:4px}.document-outline h2{margin-bottom:8px}.document-outline button{display:flex;width:100%;min-height:38px;align-items:center;justify-content:space-between;padding:0 12px;border:0;border-left:3px solid transparent;border-radius:4px;background:transparent;color:#383733;font-size:13px;cursor:pointer}.document-outline button:hover,.document-outline button.active{border-left-color:#d94a1f;background:#f7e9e1;color:#b74120}.document-outline button:disabled{cursor:not-allowed;opacity:.42}.document-outline button b{font-weight:500}.outline-total{display:flex;justify-content:space-between;margin-top:8px;padding:13px 12px 0;border-top:1px solid #e5ded2;font-size:12px}.paper-scroll{min-width:0;overflow:auto;padding:28px;background:#e7e4dd}.paper{position:relative;box-sizing:border-box;width:max(1120px,100%);min-height:100%;margin:0 auto;padding:30px 28px 18px;border:1px solid #d8d4cc;background:#fff;box-shadow:0 5px 18px rgba(31,29,24,.08);color:#222;font-family:'Noto Sans SC','Microsoft YaHei',sans-serif}.paper-header{position:relative;text-align:center}.paper-header h2{margin:0;font-size:23px;line-height:1.4}.paper-header h3{margin:3px 0 16px;font-size:17px}.paper-corner{position:absolute;top:1px;right:0;color:#777;font-size:10px}.document-facts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin-bottom:12px;border-top:1px solid #cfd1d4;border-left:1px solid #cfd1d4}.document-facts div{display:grid;grid-template-columns:92px minmax(0,1fr);min-height:32px;border-right:1px solid #cfd1d4;border-bottom:1px solid #cfd1d4;font-size:11px}.document-facts span,.document-facts b{display:flex;align-items:center;padding:6px 10px}.document-facts span{border-right:1px solid #cfd1d4;background:#f4f4f3;color:#666;font-weight:500}.document-facts b{font-weight:500;overflow-wrap:anywhere}.paper-section{scroll-margin-top:18px;break-inside:auto}.paper-section h4{margin:10px 0 5px;font-size:14px}.table-frame{overflow:hidden;border-top:1px solid #cfd1d4;border-left:1px solid #cfd1d4}.bom-table{width:100%;border-collapse:collapse;table-layout:fixed;font-size:10px}.bom-table th,.bom-table td{box-sizing:border-box;padding:5px 7px;border-right:1px solid #cfd1d4;border-bottom:1px solid #cfd1d4;line-height:1.35;text-align:left;vertical-align:top;overflow-wrap:anywhere}.bom-table th{background:#efefee;color:#555;font-weight:500}.bom-table td small{display:block;margin-top:2px;color:#8b5d4e;font-size:9px}.empty-row{text-align:center!important;color:#8a8882}.paper-footer{display:flex;justify-content:space-between;gap:20px;margin-top:10px;color:#666;font-size:9px}.paper-footer span:last-child{white-space:nowrap}
@media(max-width:1250px){.preview-shell{grid-template-columns:228px minmax(0,1fr);gap:16px}.paper-scroll{padding:18px}.preview-heading h1{font-size:28px}}
@page{size:A4 landscape;margin:9mm;@bottom-right{content:"第 " counter(page) " 页 / 共 " counter(pages) " 页";color:#666;font-size:8pt}}
@media print{:global(html),:global(body),:global(#app){height:auto!important;min-height:0!important;background:#fff!important}:global(.erp-layout){display:block!important;height:auto!important;min-height:0!important;overflow:visible!important;background:#fff!important}:global(.erp-layout__sidebar),:global(.erp-layout__header){display:none!important}:global(.erp-layout__workspace),:global(.erp-layout__main){display:block!important;width:100%!important;height:auto!important;min-height:0!important;overflow:visible!important;background:#fff!important}:global([data-page-container]),:global(.page-container__content){width:100%!important;min-height:0!important;padding:0!important;background:#fff!important}.bom-preview-page{margin:0}.preview-header,.document-aside{display:none!important}.preview-shell{display:block;height:auto;min-height:0}.paper-scroll{overflow:visible;padding:0;background:#fff}.paper{width:100%;min-height:0;padding:0;border:0;box-shadow:none}.paper-corner{right:0}.paper-section{break-inside:auto;page-break-inside:auto}.paper-section h4{break-after:avoid;page-break-after:avoid}.bom-table thead{display:table-header-group}.bom-table tr,.bom-table td,.bom-table th{break-inside:avoid;page-break-inside:avoid}.paper-footer{break-inside:avoid;page-break-inside:avoid}}
</style>
