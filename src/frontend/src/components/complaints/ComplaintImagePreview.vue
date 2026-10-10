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
.preview-body { height: 640px; display: grid; grid-template-columns: 1fr 300px; margin: 0; background: #262320; }.image-stage { display: grid; place-items: center; min-width: 0; padding: 24px; }.image-stage img { max-width: 100%; max-height: 592px; object-fit: contain; }.preview-body aside { padding: 28px 24px; color: #2c2926; background: #f4f1ea; }.preview-body h3 { margin: 0 0 24px; font-size: 19px; }.preview-body dl { margin: 0; }.preview-body dl div { margin-bottom: 20px; }.preview-body dt { color: #827c75; font-size: 12px; }.preview-body dd { margin: 6px 0 0; word-break: break-word; font-size: 14px; line-height: 21px; }.download-link { min-width: 112px; height: 42px; box-sizing: border-box; display: inline-flex; align-items: center; justify-content: center; margin-left: 12px; border-radius: 5px; color: #fff; background: #c7441d; font-size: 16px; text-decoration: none; }
</style>
