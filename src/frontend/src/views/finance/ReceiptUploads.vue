<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import axios from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { discardReceiptUpload, fetchReceiptUploadContent, uploadReceiptFile } from '@/api/financeReceipts'
import type { ReceiptUpload } from '@/types/financeReceipts'

const props = defineProps<{ modelValue: ReceiptUpload[]; statementId: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: ReceiptUpload[]]; busy: [value: boolean]; pending: [value: boolean] }>()
type Pending = { key: string; file: File; error: string }
const pending = ref<Pending[]>([])
const busy = ref(false)
const error = ref('')
const input = ref<HTMLInputElement>()
const preview = ref(false)
const previewUrl = ref('')
const previewName = ref('')
let disposed = false
function message(err: unknown) { return axios.isAxiosError(err) ? err.response?.data?.error?.message || '请求结果尚未确认，请重试原上传。' : '上传未完成，请重试。' }
function setBusy(value: boolean) { busy.value = value; emit('busy', value) }
function pendingChanged() { emit('pending', pending.value.length > 0) }
async function send(item: Pending) {
  const result = await uploadReceiptFile(props.statementId, item.file, item.key)
  pending.value = pending.value.filter(value => value.key !== item.key); pendingChanged()
  if (result.status === 'UNBOUND' || result.status === 'DISCARD_PENDING') {
    emit('update:modelValue', [...props.modelValue.filter(value => value.id !== result.id), result])
  } else throw new Error('上传已被绑定或清理，请刷新草稿核对。')
  return result
}
async function retry(item: Pending) {
  if (busy.value || props.disabled) return
  setBusy(true); item.error = ''; error.value = ''
  try { await send(item) } catch (err) {
    item.error = message(err)
    const code = axios.isAxiosError(err) ? err.response?.data?.error?.code : ''
    if (['FILE_INVALID', 'FILE_NOT_USABLE', 'SCANNER_UNAVAILABLE', 'STATEMENT_VOID'].includes(code)) {
      error.value = item.error; pending.value = pending.value.filter(value => value.key !== item.key); pendingChanged()
    }
  } finally { setBusy(false) }
}
async function choose(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (input.value) input.value.value = ''
  if (!file || props.disabled || busy.value) return
  if (!/\.(jpe?g|png)$/i.test(file.name) || file.size <= 0 || file.size > 20 * 1024 * 1024) {
    error.value = '请选择 JPG/PNG 水单，单文件须大于 0 且不超过 20 MB（20×1024×1024 字节）。'; return
  }
  const item = { key: crypto.randomUUID(), file, error: '' }
  pending.value.push(item); pendingChanged(); await retry(item)
}
async function remove(upload: ReceiptUpload) {
  if (busy.value || props.disabled) return
  setBusy(true); error.value = ''
  try {
    await discardReceiptUpload(upload.id)
    emit('update:modelValue', props.modelValue.filter(item => item.id !== upload.id))
  } catch (err) { error.value = message(err) } finally { setBusy(false) }
}
async function discardAll() {
  if (busy.value) return false
  setBusy(true); error.value = ''
  try {
    // 未确认上传先用原键查明结果，再清理；不能仅丢掉前端数组。
    const all = [...props.modelValue]
    for (const item of [...pending.value]) all.push(await send(item))
    let remaining = all
    for (const upload of all) {
      await discardReceiptUpload(upload.id)
      remaining = remaining.filter(item => item.id !== upload.id)
      emit('update:modelValue', remaining)
    }
    return true
  } catch (err) { error.value = message(err); return false } finally { setBusy(false) }
}
async function show(upload: ReceiptUpload) {
  if (upload.status !== 'UNBOUND' || busy.value) return
  setBusy(true); error.value = ''
  try {
    const blob = await fetchReceiptUploadContent(upload.id)
    if (disposed) return
    releasePreview(); previewUrl.value = URL.createObjectURL(blob); previewName.value = upload.original_name; preview.value = true
  } catch (err) { error.value = message(err) } finally { setBusy(false) }
}
function releasePreview() { if (previewUrl.value) URL.revokeObjectURL(previewUrl.value); previewUrl.value = '' }
onBeforeUnmount(() => { disposed = true; releasePreview() })
defineExpose({ discardAll })
</script>

<template>
  <section class="receipt-upload-section">
    <div class="receipt-section-heading"><div><h3>本次水单</h3></div><el-button type="primary" class="receipt-add-button" :disabled="disabled || busy || !statementId" :loading="busy" @click="input?.click()">添加水单</el-button><input ref="input" type="file" accept=".jpg,.jpeg,.png" class="file-input" tabindex="-1" aria-label="选择水单文件" @change="choose"/></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
    <p v-if="!modelValue.length && !pending.length" class="receipt-empty">尚未添加水单。上传完成后须保存收款才会绑定。</p>
    <div v-for="upload in modelValue" :key="upload.id" class="upload-line"><div><strong>{{ upload.original_name }}</strong><span v-if="upload.status === 'DISCARD_PENDING'" role="alert">清理失败，待重试</span><span v-if="['PENDING', 'INFECTED', 'FAILED'].includes(upload.scan_status)" role="alert">{{ upload.scan_label }}</span></div><el-button link type="primary" :disabled="busy || upload.status !== 'UNBOUND'" @click="show(upload)">预览</el-button><el-button link type="danger" :disabled="disabled || busy" @click="remove(upload)">{{ upload.status === 'DISCARD_PENDING' ? '重试清理' : '移除' }}</el-button></div>
    <div v-for="item in pending" :key="item.key" class="upload-line"><div><strong>{{ item.file.name }}</strong><span role="alert">{{ item.error || '正在上传并核对扫描状态…' }}</span></div><el-button :disabled="disabled || busy" @click="retry(item)">重试原上传</el-button></div>
  </section>
  <AppWindowDialog v-model="preview" :title="previewName" :width="900" :min-width="280" :minimizable="false" destroy-on-close modal-class="finance-receipt-overlay" @closed="releasePreview"><img v-if="previewUrl" :src="previewUrl" :alt="previewName" class="receipt-slip-preview"/><template #footer><el-button @click="preview = false">关闭</el-button></template></AppWindowDialog>
</template>

<style scoped lang="scss">
.upload-line>.el-button{margin-left:0}
.receipt-upload-section{border-top:1px solid var(--erp-color-border);margin-top:20px;padding-top:20px}.receipt-section-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:12px}.receipt-section-heading h3{margin:0;font-size:15px;line-height:22px;font-weight:600}.receipt-add-button{height:32px;min-height:32px;padding:0 14px;font-size:13px}.file-input{display:none}
.receipt-empty{padding:14px 16px;border-radius:5px;background:var(--erp-input-readonly-background);font-size:12px;color:var(--erp-color-text-secondary)}.upload-line{display:flex;align-items:center;gap:12px;padding:12px 14px;margin-top:10px;border:1px solid var(--erp-color-border);border-radius:5px;font-size:12px}.upload-line>div{flex:1;min-width:0}.upload-line strong,.upload-line span{display:block;line-height:20px;overflow-wrap:anywhere}.upload-line span{color:var(--erp-color-text-secondary)}.receipt-slip-preview{display:block;max-width:100%;height:auto;margin:auto}
@media(max-width:600px){.receipt-section-heading,.upload-line{flex-wrap:wrap}}
</style>
