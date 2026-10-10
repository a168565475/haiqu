<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { deleteSampleParameterImage, fetchSampleBusinessFile, uploadSampleParameterImage } from '@/api/samples'
import type { SampleDetail, SampleParameterImage } from '@/types/sample'

const props = defineProps<{
  sample: SampleDetail
  etag: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  saved: [sample: SampleDetail, etag: string]
}>()

const uploading = ref<'METALWORK' | 'CUTTING' | null>(null)
const previewVisible = ref(false)
const previewTitle = ref('')
const previewUrl = ref('')
const imageUrls = reactive<Record<string, string>>({})
let imageLoadVersion = 0

const images = computed(() => props.sample.parameter_images || [])
const imagesFor = (type: 'METALWORK' | 'CUTTING') => images.value.filter(image => image.parameter_type === type)
const canUpload = (type: 'METALWORK' | 'CUTTING') => type === 'METALWORK'
  ? Boolean(props.sample.workflow_actions?.can_upload_metalwork)
  : Boolean(props.sample.workflow_actions?.can_upload_cutting)

function messageForError(error: unknown) {
  const response = (error as { response?: { data?: { error?: { message?: string; field_errors?: Record<string, string[]> } } } }).response
  const fields = response?.data?.error?.field_errors
  return fields ? Object.values(fields).flat().join('；') : response?.data?.error?.message || '操作失败，请稍后重试。'
}

function selectFiles(type: 'METALWORK' | 'CUTTING', event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length || props.disabled || !canUpload(type)) return
  void uploadFiles(type, files)
}

async function uploadFiles(type: 'METALWORK' | 'CUTTING', files: File[]) {
  if (!props.etag) {
    ElMessage.error('缺少数据版本，请刷新后重试。')
    return
  }
  uploading.value = type
  let currentEtag = props.etag
  try {
    for (const file of files) {
      if (!/^image\/(jpeg|png|gif|webp)$/i.test(file.type) || file.size <= 0 || file.size > 5 * 1024 * 1024) {
        ElMessage.warning(`${file.name} 不是有效图片，需为 JPG、PNG、GIF 或 WebP，且不超过 5MB。`)
        continue
      }
      const result = await uploadSampleParameterImage(
        props.sample.id,
        type === 'METALWORK' ? 'metalwork' : 'cutting',
        file,
        currentEtag,
      )
      currentEtag = result.etag
      emit('saved', result.data, result.etag)
    }
    ElMessage.success(`${type === 'METALWORK' ? '金工' : '裁剪'}参数图片已上传。`)
  } catch (error) {
    ElMessage.error(messageForError(error))
  } finally {
    uploading.value = null
  }
}

async function removeImage(image: SampleParameterImage) {
  if (props.disabled || !props.etag) return
  uploading.value = image.parameter_type
  try {
    const result = await deleteSampleParameterImage(props.sample.id, image.id, props.etag)
    emit('saved', result.data, result.etag)
    ElMessage.success('参数图片已删除。')
  } catch (error) {
    ElMessage.error(messageForError(error))
  } finally {
    uploading.value = null
  }
}

async function openPreview(image: SampleParameterImage) {
  try {
    const blob = await fetchSampleBusinessFile(props.sample.id, image.file_id)
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = URL.createObjectURL(blob)
    previewTitle.value = image.file_name
    previewVisible.value = true
  } catch (error) {
    ElMessage.error(messageForError(error))
  }
}

function closePreview() {
  previewVisible.value = false
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
}

onBeforeUnmount(() => {
  closePreview()
  imageLoadVersion += 1
  for (const url of Object.values(imageUrls)) URL.revokeObjectURL(url)
})

async function hydrateThumbnails() {
  const version = ++imageLoadVersion
  for (const url of Object.values(imageUrls)) URL.revokeObjectURL(url)
  for (const key of Object.keys(imageUrls)) delete imageUrls[key]
  await Promise.all(images.value.map(async image => {
    try {
      const blob = await fetchSampleBusinessFile(props.sample.id, image.file_id)
      if (version === imageLoadVersion) imageUrls[image.id] = URL.createObjectURL(blob)
    } catch {
      // 缩略图加载失败时仍保留文件名和预览操作。
    }
  }))
}

watch(() => images.value.map(image => `${image.id}:${image.file_id}`).join('|'), () => { void hydrateThumbnails() }, { immediate: true })
</script>

<template>
  <div class="sample-parameter-images">
    <article v-for="section in [{ type: 'METALWORK' as const, label: '金工参数', allow: canUpload('METALWORK') }, { type: 'CUTTING' as const, label: '裁剪参数', allow: canUpload('CUTTING') }]" :key="section.type" class="parameter-panel">
      <header class="parameter-panel__header">
        <div>
          <h3>{{ section.label }}</h3>
          <p>{{ imagesFor(section.type).length ? `已上传 ${imagesFor(section.type).length} 张` : '至少上传 1 张图片' }}</p>
        </div>
        <label class="upload-button" :class="{ disabled: !section.allow || disabled || uploading !== null }">
          <input type="file" multiple accept=".jpg,.jpeg,.png,.gif,.webp" :disabled="!section.allow || disabled || uploading !== null" @change="selectFiles(section.type, $event)">
          {{ uploading === section.type ? '上传中…' : '上传图片' }}
        </label>
      </header>
      <div class="parameter-upload-area">
        <span class="upload-icon">＋</span>
        <span>支持 JPG、PNG、GIF、WebP，单张不超过 5MB</span>
      </div>
      <div v-if="imagesFor(section.type).length" class="parameter-thumbnails">
        <figure v-for="image in imagesFor(section.type)" :key="image.id" class="parameter-thumbnail">
          <button type="button" class="thumbnail-preview" :aria-label="`预览${image.file_name}`" @click="openPreview(image)">
            <img v-if="imageUrls[image.id]" :src="imageUrls[image.id]" :alt="image.file_name">
            <span v-else class="thumbnail-placeholder">图片</span>
          </button>
          <figcaption :title="image.file_name">{{ image.file_name }}</figcaption>
          <button type="button" class="thumbnail-delete" :disabled="disabled || uploading !== null" @click="removeImage(image)">删除</button>
        </figure>
      </div>
    </article>

    <AppWindowDialog v-model="previewVisible" :title="previewTitle || '图片预览'" :width="1200" :height="760" destroy-on-close @close="closePreview">
      <div class="parameter-preview"><img v-if="previewUrl" :src="previewUrl" :alt="previewTitle"></div>
    </AppWindowDialog>
  </div>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.sample-parameter-images { display: grid; gap: token.$crm-space-4; }
.parameter-panel { border: 1px solid token.$crm-border-subtle; border-radius: token.$crm-radius-2; background: token.$crm-color-surface; padding: token.$crm-space-4; }
.parameter-panel__header { display: flex; align-items: center; justify-content: space-between; gap: token.$crm-space-4; }
h3 { margin: 0; color: token.$crm-text-primary; font: 600 16px/24px token.$crm-font-body; }
p { margin: token.$crm-space-1 0 0; color: token.$crm-text-secondary; font: 400 13px/20px token.$crm-font-body; }
.upload-button { display: inline-flex; align-items: center; justify-content: center; min-width: 88px; height: token.$crm-control-height; padding: 0 token.$crm-space-3; border-radius: token.$crm-radius-2; background: token.$crm-primary; color: token.$crm-text-inverse; cursor: pointer; font: 500 14px/20px token.$crm-font-body; }
.upload-button:hover { background: token.$crm-primary-hover; }
.upload-button.disabled { background: token.$crm-color-disabled; color: token.$crm-text-disabled; cursor: not-allowed; }
.upload-button input { display: none; }
.parameter-upload-area { display: flex; align-items: center; gap: token.$crm-space-3; min-height: 76px; margin-top: token.$crm-space-4; padding: token.$crm-space-4; border: 1px dashed token.$crm-border-default; border-radius: token.$crm-radius-2; background: token.$crm-color-page; color: token.$crm-text-secondary; font: 400 13px/20px token.$crm-font-body; }
.upload-icon { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border: 1px solid token.$crm-border-default; border-radius: token.$crm-radius-2; color: token.$crm-primary; font-size: 24px; }
.parameter-thumbnails { display: grid; grid-template-columns: repeat(auto-fill, minmax(128px, 1fr)); gap: token.$crm-space-3; margin-top: token.$crm-space-4; }
.parameter-thumbnail { margin: 0; min-width: 0; }
.thumbnail-preview { display: block; width: 100%; height: 96px; padding: 0; overflow: hidden; border: 1px solid token.$crm-border-default; border-radius: token.$crm-radius-2; background: token.$crm-color-page; cursor: pointer; }
.thumbnail-preview img { display: block; width: 100%; height: 100%; object-fit: cover; }
.thumbnail-placeholder { display: grid; place-items: center; height: 100%; color: token.$crm-text-muted; font: 400 13px/20px token.$crm-font-body; }
figcaption { overflow: hidden; margin-top: token.$crm-space-1; color: token.$crm-text-regular; font: 400 12px/18px token.$crm-font-body; text-overflow: ellipsis; white-space: nowrap; }
.thumbnail-delete { margin-top: token.$crm-space-1; padding: 0; border: 0; background: transparent; color: token.$crm-danger; cursor: pointer; font: 400 12px/18px token.$crm-font-body; }
.thumbnail-delete:disabled { color: token.$crm-text-disabled; cursor: not-allowed; }
.parameter-preview { display: grid; place-items: center; min-height: 560px; background: #272522; }
.parameter-preview img { display: block; max-width: 100%; max-height: 720px; object-fit: contain; }
</style>
