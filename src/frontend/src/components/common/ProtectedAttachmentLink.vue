<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { isCancel } from 'axios'
import { locateResource } from '@/api/protectedResources'
import { useProtectedResourceActions } from '@/composables/useProtectedResourceUrl'
import AppWindowDialog from './AppWindowDialog.vue'

defineOptions({ inheritAttrs: false })
const props = withDefaults(defineProps<{ src: string; filename?: string; download?: boolean; timeout?: number }>(), { download: false })
const location = computed(() => locateResource(props.src))
const actions = useProtectedResourceActions()
const visible = ref(false), busy = ref(false), errorMessage = ref('')
let sequence = 0
function close() { sequence++; visible.value = false; busy.value = false; actions.reset() }
watch(() => [props.src, props.download], () => {
  close(); errorMessage.value = ''
}, { flush: 'sync' })
watch(actions.active, value => { if (!value) { sequence++; close(); busy.value = false; errorMessage.value = '' } }, { flush: 'sync' })
async function activate(event: MouseEvent, downloading = props.download) {
  if (location.value.kind === 'public') return
  event.preventDefault()
  if (busy.value || !actions.active.value) return
  const current = ++sequence
  if (!downloading || props.download) errorMessage.value = ''
  if (location.value.kind === 'invalid') { errorMessage.value = '资源地址不可用。'; return }
  busy.value = true
  if (!downloading) visible.value = true
  try {
    const options = props.timeout === undefined ? {} : { timeout: props.timeout }
    if (downloading) await actions.download(props.src, props.filename, options)
    else await actions.preview(props.src, props.filename, options)
  } catch (error) {
    if (current === sequence && actions.active.value && !isCancel(error)) {
      errorMessage.value = error instanceof Error && !('response' in error)
        ? error.message : '文件读取失败，请检查权限或稍后重试。'
    }
  } finally {
    if (current === sequence && actions.active.value) busy.value = false
  }
}
</script>

<template>
  <a v-bind="$attrs" :href="location.kind === 'public' && actions.active.value ? location.url : undefined" :download="download && location.kind === 'public' ? filename || true : undefined" role="button" tabindex="0" rel="noopener noreferrer" :aria-disabled="busy || !actions.active.value" :aria-busy="busy" @click="activate" @keydown.enter.prevent="($event.currentTarget as HTMLElement).click()" @keydown.space.prevent="($event.currentTarget as HTMLElement).click()"><slot /></a>
  <span v-if="errorMessage && !visible" role="alert">{{ errorMessage }}</span>
  <AppWindowDialog :model-value="visible && actions.active.value" :title="actions.previewName.value || filename || '附件预览'" :width="1000" :height="680" destroy-on-close @update:model-value="value => { if (!value) close() }">
    <div class="protected-attachment-preview">
      <p v-if="actions.previewLoading.value" role="status">正在读取文件…</p>
      <p v-else-if="errorMessage" role="alert">{{ errorMessage }}</p>
      <img v-else-if="actions.previewUrl.value" :src="actions.previewUrl.value" :alt="actions.previewName.value" @error="errorMessage = '图片暂无法加载。'" />
    </div>
    <template #footer><el-button @click="close">关闭</el-button><el-button :disabled="busy || !actions.active.value" @click="activate($event, true)">下载原文件</el-button></template>
  </AppWindowDialog>
</template>

<style scoped>
.protected-attachment-preview { height: 100%; display: grid; place-items: center; min-height: 0; }
.protected-attachment-preview img { max-width: 100%; max-height: 100%; object-fit: contain; }
a[aria-disabled="true"] { cursor: default; }
</style>
