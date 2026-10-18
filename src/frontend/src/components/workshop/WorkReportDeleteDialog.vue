<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { isAxiosError } from 'axios'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { deleteWorkReport, fetchWorkReport } from '@/api/workshopReporting'
import type { WorkReport } from '@/types/workshopReporting'

const props = defineProps<{ modelValue: boolean; report: WorkReport | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; deleted: [] }>()
const current = ref<WorkReport | null>(null)
const reason = ref(''), error = ref(''), busy = ref(false), needsRefresh = ref(false)
const canSubmit = computed(() => !busy.value && !needsRefresh.value && !!reason.value.trim()
  && !!current.value?.etag && current.value.can_delete === true)
watch(() => props.modelValue, value => {
  if (value) { current.value = props.report; reason.value = ''; error.value = ''; needsRefresh.value = false }
}, { immediate: true })
function close() { if (!busy.value) emit('update:modelValue', false) }
function beforeClose(done: () => void) { if (!busy.value) done() }
function completed() { emit('update:modelValue', false); emit('deleted') }
function message(cause: unknown): string {
  return isAxiosError(cause) ? cause.response?.data?.error?.message || '请求未确认成功，请核对当前记录后再操作。'
    : '操作未完成，请核对当前记录后再操作。'
}
async function remove() {
  if (!canSubmit.value || !current.value) return
  busy.value = true; error.value = ''
  try { await deleteWorkReport(current.value.id, reason.value.trim(), current.value.etag!); completed() }
  catch (cause) { error.value = message(cause); needsRefresh.value = true }
  finally { busy.value = false }
}
async function refresh() {
  if (busy.value || !current.value) return
  busy.value = true
  try {
    const result = await fetchWorkReport(current.value.id)
    current.value = { ...result.data, etag: result.etag }
    needsRefresh.value = false
    error.value = current.value.can_delete ? '' : '当前账号已无权删除这条报工，请关闭后刷新列表。'
  } catch (cause) {
    if (isAxiosError(cause) && cause.response?.status === 404) completed()
    else error.value = message(cause)
  } finally { busy.value = false }
}
</script>

<template>
  <AppWindowDialog :model-value="modelValue" title="删除报工" :width="520" modal-class="work-report-delete-modal"
    :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" :before-close="beforeClose"
    @update:model-value="value => { if (!busy) emit('update:modelValue', value) }">
    <div class="work-report-delete-content">
      <p class="delete-report-number">{{ current?.report_number }} · {{ current?.workshop.name }} · ¥{{ current?.total_amount }}</p>
      <p>将永久删除这次报工及全部明细，保留删除日志。数量和金额会重新汇总；数量不足时，关联车间计划恢复为进行中。</p>
      <label for="work-report-delete-reason">删除原因 <span aria-hidden="true">*</span></label>
      <textarea id="work-report-delete-reason" v-model="reason" aria-required="true" maxlength="1000" :disabled="busy"
        placeholder="请说明删除原因" />
      <p v-if="error" class="delete-error" role="alert">{{ error }}</p>
    </div>
    <template #footer>
      <div class="work-report-delete-actions">
        <button v-if="needsRefresh" type="button" :disabled="busy" @click="refresh">核对当前记录</button>
        <button type="button" :disabled="busy" @click="close">取消</button>
        <button type="button" class="delete-confirm" :disabled="!canSubmit" @click="remove">{{ busy ? '处理中…' : '确认删除' }}</button>
      </div>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as t;
:global(.work-report-delete-modal .app-window-dialog) {border-radius:5px;}
.work-report-delete-content {display:flex;flex-direction:column;gap:16px;font-size:13px;line-height:1.6;
  p {margin:0;} .delete-report-number {font-weight:600;} label {font-weight:500;}
  textarea {height:96px;min-height:96px;resize:vertical;padding:8px 12px;border:1px solid t.$crm-border-default;border-radius:5px;background:t.$crm-color-surface;color:inherit;font:inherit;box-sizing:border-box;}
  textarea:focus-visible {outline:2px solid t.$crm-primary;outline-offset:2px;}
  label span,.delete-error {color:t.$crm-danger;}
}
.work-report-delete-actions {display:flex;justify-content:flex-end;gap:8px;
  button {height:32px;border:1px solid t.$crm-border-default;border-radius:5px;padding:0 12px;background:t.$crm-color-surface;color:inherit;font-size:13px;cursor:pointer;}
  button:disabled {opacity:.45;cursor:not-allowed;} .delete-confirm {background:t.$crm-danger;color:var(--erp-color-text-inverse);border-color:t.$crm-danger;}
}
</style>
