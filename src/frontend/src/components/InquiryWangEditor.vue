<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { IDomEditor } from '@wangeditor/editor'
import { Editor, Toolbar } from '@wangeditor/editor-for-vue'
import '@wangeditor/editor/dist/css/style.css'

const props = withDefaults(defineProps<{
  modelValue: string
  uploadUrl: string
  uploadEtag: string
  maxlength?: number
  placeholder?: string
  showUploadNotice?: boolean
  compact?: boolean
}>(), {
  maxlength: 5000,
  placeholder: '记录与客户的沟通过程、原始需求和重要结论，不替代正式报价。',
  showUploadNotice: true,
  compact: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:uploadEtag': [value: string]
}>()

const editorRef = shallowRef<IDomEditor>()
const valueHtml = ref(props.modelValue || '')
const mode = 'default'

function csrfToken() {
  const token = document.cookie.split('; ').find((item) => item.startsWith('csrftoken='))?.split('=')[1]
  return token ? decodeURIComponent(token) : ''
}

function uploadHeaders() {
  const headers: Record<string, string> = { 'If-Match': props.uploadEtag }
  const token = csrfToken()
  if (token) headers['X-CSRFToken'] = token
  return headers
}

function uploadErrorMessage(response: unknown, fallback: string) {
  if (response && typeof response === 'object' && 'message' in response && typeof response.message === 'string') {
    return response.message
  }
  return fallback
}

const toolbarConfig = computed(() => ({
  ...(props.compact ? { toolbarKeys: props.uploadUrl ? ['uploadImage'] : [] } : {}),
  // 新建询盘还没有可关联的业务记录，先隐藏上传入口，保存草稿后自动出现。
  excludeKeys: props.uploadUrl ? [] : ['uploadImage'],
}))

const editorConfig = computed(() => ({
  placeholder: props.placeholder,
  maxLength: props.maxlength,
  MENU_CONF: {
    uploadImage: {
      server: props.uploadUrl,
      fieldName: 'file',
      maxFileSize: 5 * 1024 * 1024,
      maxNumberOfFiles: 1,
      allowedFileTypes: ['image/jpeg', 'image/png', 'image/gif', 'image/webp'],
      headers: uploadHeaders(),
      withCredentials: true,
      timeout: 120000,
      onBeforeUpload(file: File) {
        if (!props.uploadEtag) {
          ElMessage.warning('请先保存草稿，再上传沟通图片。')
          return false
        }
        return file
      },
      onSuccess(_file: File, response: unknown) {
        const result = response as { errno?: number; data?: { etag?: string } }
        if (result.errno !== 0) return
        if (result.data?.etag) emit('update:uploadEtag', result.data.etag)
      },
      onFailed(_file: File, response: unknown) {
        ElMessage.error(uploadErrorMessage(response, '图片上传失败，请稍后重试。'))
      },
      onError(_file: File, _error: unknown, response: unknown) {
        ElMessage.error(uploadErrorMessage(response, '图片上传出错或超时，请稍后重试。'))
      },
    },
  },
}))

function syncUploadHeaders() {
  const menuConfig = editorRef.value?.getMenuConfig('uploadImage') as { headers?: Record<string, string> } | undefined
  if (menuConfig) menuConfig.headers = uploadHeaders()
}

function handleCreated(editor: IDomEditor) {
  editorRef.value = editor
  syncUploadHeaders()
}

function handleChange(editor: IDomEditor) {
  const html = editor.getHtml()
  if (valueHtml.value !== html) valueHtml.value = html
  emit('update:modelValue', html)
}

function handleMaxLength() {
  ElMessage.warning(`沟通内容不能超过 ${props.maxlength} 个文字。`)
}

function customAlert(message: string, type: string) {
  if (type === 'error' || type === 'warning') ElMessage.error(message)
  else ElMessage.info(message)
}

watch(() => props.modelValue, (value) => {
  if (value !== valueHtml.value) valueHtml.value = value || ''
})
watch(() => props.uploadEtag, syncUploadHeaders)

onBeforeUnmount(() => editorRef.value?.destroy())
</script>

<template>
  <section class="inquiry-wang-editor" :class="{ 'inquiry-wang-editor--compact': compact }">
    <el-alert v-if="showUploadNotice && !uploadUrl" title="保存草稿后即可通过图片工具上传 JPG、PNG、GIF 或 WebP 图片（单张最大 5MB）。" type="info" :closable="false" class="inquiry-wang-editor__notice" />
    <div class="inquiry-wang-editor__surface">
      <Toolbar :key="`${uploadUrl || 'new'}-toolbar`" :editor="editorRef" :default-config="toolbarConfig" :mode="mode" />
      <Editor :key="uploadUrl || 'new'" v-model="valueHtml" :default-config="editorConfig" :mode="mode" @on-created="handleCreated" @on-change="handleChange" @on-max-length="handleMaxLength" @custom-alert="customAlert" />
    </div>
  </section>
</template>

<style scoped lang="scss">
.inquiry-wang-editor{width:100%}.inquiry-wang-editor__notice{margin-bottom:8px}.inquiry-wang-editor__surface{overflow:hidden;border:1px solid #dcdfe6;border-radius:8px}.inquiry-wang-editor__surface:focus-within{border-color:#409eff;box-shadow:0 0 0 2px rgb(64 158 255 / 12%)}.inquiry-wang-editor__surface :deep(.w-e-toolbar){border-bottom:1px solid #dcdfe6;background:#fff}.inquiry-wang-editor__surface :deep(.w-e-bar){min-height:38px;flex-wrap:wrap}.inquiry-wang-editor__surface :deep(.w-e-text-container){min-height:170px;background:#fff}.inquiry-wang-editor__surface :deep(.w-e-text-placeholder){top:12px;color:#a8abb2}.inquiry-wang-editor__surface :deep(.w-e-text-container [data-slate-editor]){min-height:170px;padding:12px 14px;font-size:14px;line-height:1.75}.inquiry-wang-editor__surface :deep(img){max-width:100%;height:auto;border-radius:6px}@media(max-width:700px){.inquiry-wang-editor__surface :deep(.w-e-toolbar){max-height:94px;overflow-y:auto}.inquiry-wang-editor__surface :deep(.w-e-text-container),.inquiry-wang-editor__surface :deep(.w-e-text-container [data-slate-editor]){min-height:132px}}
</style>

<style scoped lang="scss">
.inquiry-wang-editor--compact {
  .inquiry-wang-editor__surface { position: relative; height: 166px; border-color: #e8e6dc; border-radius: 6px; }
  :deep(.w-e-toolbar) { position: absolute; right: 1px; bottom: 1px; z-index: 2; border: 0; border-radius: 6px; }
  :deep(.w-e-bar) { min-height: 28px; }
  :deep(.w-e-bar-item) { height: 28px; padding: 0 3px; }
  :deep(.w-e-bar-item button) { height: 28px; min-width: 28px; padding: 0 5px; background: transparent; border: 0; }
  :deep(.w-e-text-container) { height: 164px !important; min-height: 0; }
  :deep(.w-e-text-container [data-slate-editor]) { min-height: 164px; padding: 10px 12px 30px; font-size: 13px; line-height: 22px; }
  :deep(.w-e-text-container p) { margin: 0; }
}
</style>
