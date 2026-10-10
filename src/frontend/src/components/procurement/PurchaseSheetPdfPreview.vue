<script setup lang="ts">
import ElDialog from '@/components/common/AppWindowDialog.vue'
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'
import type { PDFDocumentLoadingTask, PDFDocumentProxy } from 'pdfjs-dist'
import PurchasePdfPage from './PurchasePdfPage.vue'

const visible = defineModel<boolean>({ required: true })
const props = defineProps<{
  sheetNumber: string
  version: number
  supplierName: string
  draft: boolean
  loading: boolean
  error: string
  pdf: Blob | null
}>()
defineEmits<{ retry: [] }>()
const document = shallowRef<PDFDocumentProxy | null>(null)
const viewer = ref<HTMLElement>()
const parsing = ref(false)
const renderError = ref('')
const firstPageReady = ref(false)
const pageHeight = ref(1174)
const displayError = computed(() => props.error || renderError.value)
const displayLoading = computed(() => props.loading || parsing.value || (!!props.pdf && !firstPageReady.value && !displayError.value))
let loadingTask: PDFDocumentLoadingTask | null = null
let generation = 0
function release(): void {
  generation++
  document.value = null
  const task = loadingTask
  loadingTask = null
  if (task) void task.destroy().catch(() => {})
  parsing.value = false
  renderError.value = ''
  firstPageReady.value = false
}
watch([() => props.pdf, visible], async ([pdf, open]) => {
  release()
  if (!pdf || !open) return
  const current = generation
  parsing.value = true
  try {
    const { loadPurchasePdf } = await import('@/utils/purchasePdf')
    const data = new Uint8Array(await pdf.arrayBuffer())
    if (current !== generation) return
    const task = loadPurchasePdf(data)
    loadingTask = task
    const pdfDocument = await task.promise
    const firstPage = await pdfDocument.getPage(1)
    if (current !== generation) return
    const viewport = firstPage.getViewport({ scale: 1 })
    pageHeight.value = viewport.height * 830 / viewport.width
    document.value = pdfDocument
    await nextTick()
    if (viewer.value && current === generation) viewer.value.scrollTop = 0
  } catch {
    if (current === generation) renderError.value = 'PDF 文件无法显示，请重新加载。'
  } finally {
    if (current === generation) parsing.value = false
  }
}, { flush: 'post' })
onBeforeUnmount(release)
</script>

<template>
  <ElDialog v-model="visible" class="purchase-pdf-dialog" title="PDF 预览" width="1114px"
    append-to-body destroy-on-close :close-on-click-modal="false">
    <div class="pdf-meta-row">
      <p class="pdf-meta">{{ sheetNumber }} · V{{ version }} · {{ supplierName }}</p>
      <ElTag :class="{ published: !draft }">{{ draft ? '草稿' : '已发布' }}</ElTag>
    </div>
    <div class="pdf-notice"><ElIcon><InfoFilled /></ElIcon>
      <span>{{ draft ? '当前为草稿预览，发布后生成正式 PDF。' : '当前为已发布的正式 PDF。' }}</span>
    </div>
    <div ref="viewer" class="pdf-viewer" :aria-busy="displayLoading" tabindex="0" aria-label="采购表 PDF 阅读区">
      <div v-if="displayLoading" v-loading="true" class="pdf-state" role="status"><p>正在生成 PDF 预览…</p></div>
      <div v-else-if="displayError" class="pdf-state pdf-error" role="alert">
        <p>{{ displayError }}</p><ElButton @click="$emit('retry')">重新加载</ElButton>
      </div>
      <div v-if="document && viewer && !displayError" class="pdf-pages">
        <PurchasePdfPage v-for="number in document.numPages" :key="`${generation}-${number}`" :document="document"
          :page-number="number" :initial-height="pageHeight" :scroll-root="viewer"
          @ready="number === 1 && (firstPageReady = true)" @error="renderError = 'PDF 文件无法显示，请重新加载。'" />
      </div>
      <div v-else-if="!displayLoading && !displayError" class="pdf-state" role="status">暂无 PDF 内容</div>
    </div>
    <template #footer><ElButton type="primary" @click="visible = false">返回编辑</ElButton></template>
  </ElDialog>
</template>

<style lang="scss">
@use '@/styles/crm/tokens' as crm;
.el-dialog.purchase-pdf-dialog {
  box-sizing: border-box; margin-bottom: 0; padding: 0; height: 1030px;
  border-radius: 6px; background: crm.$crm-color-surface; color: crm.$crm-text-primary;
  box-shadow: 0 8px 24px #00000029; font-family: crm.$crm-font-body;
  --el-color-primary: #{crm.$crm-primary}; --el-fill-color-blank: #{crm.$crm-color-surface};
  --el-border-color: #{crm.$crm-border-default};
  .el-dialog__header { box-sizing: border-box; height: 108px; padding: 20px 26px 14px; margin: 0; }
  .el-dialog__headerbtn { top: 20px; right: 12px; width: 32px; height: 32px; font-size: 20px; }
  .el-dialog__headerbtn .el-dialog__close { color: crm.$crm-text-secondary; }
  .pdf-meta-row { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
  .pdf-meta-row .el-tag { flex: none; border: 0; border-radius: 999px; height: 24px; background: crm.$crm-color-subtle; color: crm.$crm-neutral; font-size: 12px; }
  .pdf-meta-row .el-tag.published { background: crm.$crm-success-soft; color: crm.$crm-success; }
  .pdf-meta { margin: 0; font-size: 16px; line-height: 24px; color: crm.$crm-text-secondary; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .el-dialog__body { padding: 0 26px; }
  .pdf-notice { box-sizing: border-box; height: 42px; margin-bottom: 14px; padding: 0 16px; display: flex; align-items: center; gap: 12px; border-radius: 4px; font-size: 14px; color: crm.$crm-text-secondary; background: crm.$crm-color-subtle; }
  .pdf-notice .el-icon { font-size: 16px; }
  .pdf-viewer { position: relative; height: 792px; overflow: auto; background: crm.$crm-color-subtle; border-radius: 4px; }
  .pdf-pages { box-sizing: border-box; min-height: 100%; display: flex; flex-direction: column; gap: 24px; padding: 14px 0 30px 118px; }
  .pdf-viewer::-webkit-scrollbar { width: 14px; }
  .pdf-viewer::-webkit-scrollbar-thumb { border: 3px solid transparent; border-radius: 7px; background: crm.$crm-border-default; background-clip: padding-box; }
  .pdf-state { position: absolute; inset: 0; z-index: 2; box-sizing: border-box; height: 792px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; color: crm.$crm-text-secondary; background: crm.$crm-color-subtle; }
  .pdf-state[role=status] p { position: relative; top: 45px; z-index: 2001; }
  .pdf-error p { color: crm.$crm-danger; }
  .el-dialog__footer { box-sizing: border-box; height: 74px; padding: 13px 26px 14px; border-top: 1px solid crm.$crm-border-subtle; }
  .el-dialog__footer .el-button { width: 128px; height: 46px; margin: 0; border-radius: 4px; font-size: 16px; }
}
</style>
