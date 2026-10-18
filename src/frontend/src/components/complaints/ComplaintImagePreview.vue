<script setup lang="ts">
import { computed } from 'vue'
import { complaintPreviewUrl } from '@/api/complaints'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { ComplaintAttachment } from '@/types/complaint'

const props = defineProps<{ modelValue: boolean; attachment: ComplaintAttachment | null }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
const imageUrl = computed(() => props.attachment ? complaintPreviewUrl(props.attachment.preview_url) : '')
function close() { emit('update:modelValue', false) }
</script>

<template>
  <AppWindowDialog class="complaint-operation-dialog complaint-preview-dialog" :model-value="modelValue" :title="attachment?.original_name || '图片预览'" :width="1400" :height="792" destroy-on-close @update:model-value="value => { if (!value) close() }">
    <div class="preview-body">
      <div class="image-stage"><img v-if="attachment" :src="imageUrl" :alt="attachment.original_name" /></div>
      <aside v-if="attachment"><h3>图片信息</h3><dl><div><dt>文件名</dt><dd>{{ attachment.original_name }}</dd></div><div><dt>说明</dt><dd>{{ attachment.caption || '未填写' }}</dd></div><div><dt>大小</dt><dd>{{ Math.ceil(attachment.size_bytes / 1024) }} KB</dd></div><div><dt>上传时间</dt><dd>{{ new Date(attachment.created_at).toLocaleString('zh-CN', { hour12: false }) }}</dd></div></dl></aside>
    </div>
    <template #footer><el-button @click="close">关闭</el-button><a v-if="attachment" class="download-link" :href="imageUrl" download>下载原图</a></template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.preview-body { height: auto; display: grid; grid-template-columns: minmax(0,1fr) 260px; margin: 0; background: #262320; min-height: 0; }.image-stage { display: grid; place-items: center; min-width: 0; padding: 16px; }.image-stage img { max-width: 100%; max-height: min(592px, 65dvh); object-fit: contain; }.preview-body aside { padding: 16px; color: var(--erp-color-text-primary); background: var(--erp-color-subtle); min-width: 0; }.preview-body h3 { margin: 0 0 14px; font-size: 16px; font-family: var(--erp-font-body); line-height: 24px; }.preview-body dl { margin: 0; }.preview-body dl div { margin-bottom: 20px; }.preview-body dt { color: var(--erp-color-text-regular); font-size: 12px; }.preview-body dd { margin: 6px 0 0; word-break: break-word; font-size: 14px; line-height: 21px; }.download-link { min-width: 112px; height: 42px; box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; margin-left: 12px; border-radius: 5px; color: var(--erp-button-primary-text); background: var(--erp-button-primary-surface); font-size: 16px; text-decoration: none; }:global(.complaint-preview-dialog) { container-type:inline-size; }@container (max-width:640px) { .preview-body { grid-template-columns:minmax(0,1fr); } }
</style>
