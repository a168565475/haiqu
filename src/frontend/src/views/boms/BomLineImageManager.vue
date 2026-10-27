<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElButton, ElEmpty, ElImage } from 'element-plus'

import { bomLineImageUrl } from '@/api/boms'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import type { BomDraftLineImage, BomLineImage, BomLineInput } from '@/types/bom'

type CuttingDisplayImage = BomLineImage | BomDraftLineImage
type BeforeCloseHandler = (done: () => void) => void

const props = withDefaults(defineProps<{
  modelValue: boolean
  line: BomLineInput | null
  sectionTitle?: string
  lineIndex?: number
  canEdit?: boolean
  busy?: boolean
  uploading?: boolean
  deletingImageId?: string
  zIndex?: number
  beforeClose?: BeforeCloseHandler
}>(), {
  sectionTitle: '',
  lineIndex: 0,
  canEdit: true,
  busy: false,
  uploading: false,
  deletingImageId: '',
  zIndex: 0,
  beforeClose: undefined,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  upload: [event: Event]
  remove: [image: CuttingDisplayImage]
  'open-file-picker': []
  close: []
  closed: []
}>()

const images = computed<CuttingDisplayImage[]>(() => {
  if (!props.line) return []
  return [...(props.line.images || []), ...(props.line.draft_images || [])]
})

const sortedImages = computed(() => [...images.value].sort((left, right) => left.position - right.position))
const imageFileInput = ref<HTMLInputElement | null>(null)

function openFilePicker() {
  if (props.canEdit && !props.busy && images.value.length < 20) {
    imageFileInput.value?.click()
    emit('open-file-picker')
  }
}

function fileSizeText(sizeBytes: number) {
  if (!Number.isFinite(sizeBytes) || sizeBytes <= 0) return '0 KB'
  if (sizeBytes < 1024 * 1024) return `${Math.max(1, Math.round(sizeBytes / 1024))} KB`
  return `${(sizeBytes / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <AppWindowDialog
    :model-value="props.modelValue"
    class="line-image-manager-dialog"
    title="用料图片"
    width="860px"
    append-to-body
    destroy-on-close
    :z-index="props.zIndex"
    :close-on-click-modal="false"
    :before-close="props.beforeClose"
    @update:model-value="emit('update:modelValue', $event)"
    @closed="emit('closed')"
  >
    <div v-if="props.line" class="line-image-manager">
      <header class="line-image-manager-toolbar">
        <div>
          <strong>{{ props.sectionTitle }} · 第 {{ props.lineIndex + 1 }} 行</strong>
          <span>{{ props.line.part_name || '未填写品名' }} · {{ images.length }} / 20 张</span>
        </div>
        <ElButton
          size="small"
          plain
          type="primary"
          :loading="props.uploading"
          :disabled="!props.canEdit || props.busy || images.length >= 20"
          @click="openFilePicker"
        >
          {{ props.uploading ? '上传中…' : '上传图片' }}
        </ElButton>
          <input
            ref="imageFileInput"
          class="line-image-file-input"
          type="file"
          multiple
          accept=".jpg,.jpeg,.png,.gif,.webp,image/jpeg,image/png,image/gif,image/webp"
          aria-label="上传用料图片"
          :disabled="!props.canEdit || props.busy || images.length >= 20"
          @change="emit('upload', $event)"
        >
      </header>
      <div v-if="images.length" class="cutting-image-grid">
        <article v-for="image in sortedImages" :key="image.id">
          <ElImage :src="bomLineImageUrl(image.content_url)" :preview-src-list="sortedImages.map((item) => bomLineImageUrl(item.content_url))" preview-teleported fit="cover" />
          <div><strong :title="image.name">{{ image.name }}</strong><span>{{ fileSizeText(image.size_bytes) }}</span></div>
          <ElButton type="danger" link :loading="props.deletingImageId === image.id" :disabled="!props.canEdit || props.busy" @click="emit('remove', image)">删除</ElButton>
        </article>
      </div>
      <ElEmpty v-else :image-size="64" description="暂无用料图片，点击右上角按钮上传" />
    </div>
    <template #footer>
      <ElButton type="primary" :disabled="props.busy" @click="emit('close')">完成</ElButton>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.line-image-manager { min-height: 310px; }
.line-image-manager-toolbar { position: relative; display: flex; align-items: center; justify-content: space-between; gap: 20px; padding-bottom: 14px; border-bottom: 1px solid var(--erp-color-border); }
.line-image-manager-toolbar > div { min-width: 0; }
.line-image-manager-toolbar strong, .line-image-manager-toolbar span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.line-image-manager-toolbar strong { color: var(--erp-color-text-primary); font-size: 14px; }
.line-image-manager-toolbar span { margin-top: 5px; color: var(--erp-color-text-secondary); font-size: 12px; }
.line-image-file-input { position: absolute; width: 1px; height: 1px; overflow: hidden; opacity: 0; pointer-events: none; }
.cutting-image-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
.cutting-image-grid article { display: grid; grid-template-columns: 72px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 8px; border: 1px solid var(--erp-color-border); border-radius: 6px; background: var(--erp-color-surface); }
.cutting-image-grid :deep(.el-image) { width: 72px; height: 56px; border-radius: 4px; background: var(--erp-color-readonly); }
.cutting-image-grid article > div { min-width: 0; }
.cutting-image-grid article > div strong, .cutting-image-grid article > div span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cutting-image-grid article > div strong { color: var(--erp-color-text-regular); font-size: 12px; }
.cutting-image-grid article > div span { margin-top: 5px; color: var(--erp-color-text-muted); font-size: 11px; }
</style>
