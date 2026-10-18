<script setup lang="ts">
import { computed } from 'vue'
import { ElButton, ElImage } from 'element-plus'

import { bomLineImageUrl } from '@/api/boms'
import type { BomDraftLineImage, BomLineImage, BomLineInput } from '@/types/bom'

const props = defineProps<{
  line: BomLineInput
  editable?: boolean
}>()

const emit = defineEmits<{
  open: []
}>()

const images = computed<(BomLineImage | BomDraftLineImage)[]>(() =>
  [...(props.line.images || []), ...(props.line.draft_images || [])]
    .sort((left, right) => left.position - right.position),
)

const previewUrls = computed(() => images.value.map((image) => bomLineImageUrl(image.content_url)))
</script>

<template>
  <div class="bom-line-image-summary">
    <div v-if="images.length" class="image-thumbnails">
      <ElImage
        v-for="image in images.slice(0, 3)"
        :key="image.id"
        :src="bomLineImageUrl(image.content_url)"
        :preview-src-list="previewUrls"
        preview-teleported
        fit="cover"
        @click.stop
      />
    </div>
    <span>{{ images.length ? `共 ${images.length} 张` : '暂无图片' }}</span>
    <ElButton v-if="editable" size="small" plain type="primary" @click.stop="emit('open')">
      {{ images.length ? '管理图片' : '上传图片' }}
    </ElButton>
  </div>
</template>

<style lang="scss" scoped>
.bom-line-image-summary {
  display: flex;
  min-height: 32px;
  align-items: center;
  gap: 7px;
  color: var(--erp-color-text-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.image-thumbnails {
  display: flex;
  gap: 4px;
}

.image-thumbnails :deep(.el-image) {
  width: 32px;
  height: 32px;
  flex: none;
  border: 1px solid var(--erp-color-border);
  border-radius: 4px;
  background: var(--erp-color-subtle);
}
</style>
