<script setup lang="ts">
import { nextTick, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { AxiosError } from 'axios'
import { fetchOutsourcingOrder } from '@/api/outsourcing'
import { fetchTubeOrder } from '@/api/tubeOutsourcing'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import OutsourcingPrintDocument from './OutsourcingPrintDocument.vue'
import type { UnifiedOutsourcingOrder } from '@/types/unifiedOutsourcing'
import type { OutsourcingPrintDocumentData, OutsourcingPrintKind } from '@/types/outsourcingPrint'
import { buildRegularPrintDocument, buildTubePrintDocument } from '@/utils/outsourcingPrint'

const props = defineProps<{ record: UnifiedOutsourcingOrder; kind: OutsourcingPrintKind }>()
const emit = defineEmits<{ close: [] }>()
const printDocument = ref<OutsourcingPrintDocumentData | null>(null)
const loading = ref(false)
const error = ref('')
let active = true

function close(): void {
  active = false
  emit('close')
}

async function print(): Promise<void> {
  if (!active || !printDocument.value || loading.value) return
  await nextTick()
  await document.fonts?.ready
  if (!active) return
  try {
    window.print()
  } catch {
    error.value = '无法打开打印窗口，请检查浏览器设置后重新打印。'
  }
}

async function load(): Promise<void> {
  if (!active || loading.value) return
  loading.value = true
  error.value = ''
  printDocument.value = null
  try {
    if (props.record.record_type === 'TUBE') {
      const detail = await fetchTubeOrder(props.record.id)
      if (!active) return
      if (props.kind === 'spray' && (detail.category === 'cutting' || !['RAW_PIPE', 'PUBLIC_SEMI', 'METAL'].includes(detail.source_kind))) {
        error.value = '管材喷塑打印仅支持管材喷塑单。'
        return
      }
      printDocument.value = buildTubePrintDocument(detail, props.kind)
    } else if (props.record.record_type === 'ORIGINAL' && props.record.detail_access === 'REGULAR' && props.kind === 'processing') {
      const detail = await fetchOutsourcingOrder(props.record.id)
      if (!active) return
      printDocument.value = buildRegularPrintDocument(detail.data)
    } else {
      error.value = '当前单据没有可用的打印明细。'
    }
  } catch (failure) {
    if (!active) return
    const body = failure instanceof AxiosError ? failure.response?.data as { error?: { message?: string }; detail?: string } | undefined : undefined
    error.value = body?.error?.message || body?.detail || '打印数据读取失败，请重试。'
  } finally {
    loading.value = false
  }
  if (active && printDocument.value) await print()
}

onMounted(() => { void load() })
onBeforeUnmount(() => { active = false })
onDeactivated(close)
</script>

<template>
  <AppWindowDialog :model-value="true" :title="`${kind === 'spray' ? '管材喷塑打印' : '加工单打印'} · A4 纵向`" :width="900" height="88vh" :minimizable="false" modal-class="outsourcing-print-overlay" @update:model-value="value => { if (!value) close() }">
    <ElSkeleton v-if="loading" :rows="8" animated aria-label="正在读取打印数据" />
    <div v-if="error" class="outsourcing-print-error" role="alert">
      <ElAlert :title="error" type="error" :closable="false" show-icon />
      <ElButton v-if="!printDocument" data-testid="print-retry" :disabled="loading" @click="load">重新读取</ElButton>
    </div>
    <div v-if="printDocument" class="outsourcing-print-paper"><OutsourcingPrintDocument :document="printDocument" /></div>
    <template #footer><span class="outsourcing-print-hint">A4 纵向 · 每次一份</span><ElButton @click="close">关闭</ElButton><ElButton type="primary" :disabled="loading || !printDocument" @click="print">打印</ElButton></template>
  </AppWindowDialog>
</template>

<style lang="scss">
.outsourcing-print-overlay {
  .app-window-dialog__body { background: #e8e8e8; overflow: auto; }
  .outsourcing-print-paper { box-sizing: border-box; width: 210mm; min-height: 297mm; margin: 0 auto; padding: 23mm 16mm 15mm; background: #fff; }
  .outsourcing-print-error { display: grid; gap: 12px; margin-bottom: 12px; }
  .outsourcing-print-hint { margin-right: auto; font-size: 12px; color: var(--erp-color-text-secondary); }
}
@media print {
  html:has(.outsourcing-print-overlay .outsourcing-print-document) { height: auto !important; overflow: visible !important; background: #fff !important; }
  body:has(.outsourcing-print-overlay .outsourcing-print-document) {
    page: outsourcing-document;
    height: auto !important; min-height: 0 !important; overflow: visible !important; margin: 0 !important; padding: 0 !important; background: #fff !important;
    > :not(.outsourcing-print-overlay) { display: none !important; }
    .outsourcing-print-overlay, .outsourcing-print-overlay .app-window-dialog, .outsourcing-print-overlay .app-window-dialog__body, .outsourcing-print-paper {
      display: block !important; position: static !important; inset: auto !important; transform: none !important;
      width: auto !important; height: auto !important; min-height: 0 !important; max-height: none !important; max-width: none !important;
      overflow: visible !important; margin: 0 !important; padding: 0 !important; border: 0 !important; border-radius: 0 !important;
      box-shadow: none !important; backdrop-filter: none !important; background: #fff !important;
    }
    .outsourcing-print-overlay .app-window-dialog__header, .outsourcing-print-overlay .app-window-dialog__footer,
    .outsourcing-print-overlay .app-window-dialog__resize-handle, .outsourcing-print-error { display: none !important; }
  }
}
</style>
