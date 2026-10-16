<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { isAxiosError } from 'axios'
import { fetchProductionTask, productionTaskBusinessFileUrl } from '@/api/productionTasks'
import ProductImage from '@/components/products/ProductImage.vue'

const props = defineProps<{ taskId: string; productLineId: string }>()
const imageUrl = ref('')
const imageName = ref('产品图片')
const loading = ref(false)
const errorMessage = ref('')
const canRetry = ref(false)
let requestVersion = 0

async function loadImage() {
  const version = ++requestVersion
  const { taskId, productLineId } = props
  imageUrl.value = ''
  errorMessage.value = ''
  canRetry.value = false
  loading.value = false
  if (!taskId) {
    errorMessage.value = 'BOM 未关联生产任务，无法读取产品图片。'
    return
  }
  if (!productLineId) {
    errorMessage.value = 'BOM 未关联生产任务产品明细，无法读取产品图片。'
    return
  }

  loading.value = true
  let result: Awaited<ReturnType<typeof fetchProductionTask>>
  try {
    result = await fetchProductionTask(taskId)
  } catch (error) {
    if (version !== requestVersion) return
    loading.value = false
    const response = isAxiosError(error) ? error.response : undefined
    const status = response?.status
    if (status === 401 || response?.data?.error?.code === 'AUTHENTICATION_REQUIRED') errorMessage.value = '登录状态已失效，请重新登录后查看产品图片。'
    else if (status === 403) errorMessage.value = '无权查看生产任务产品图片。'
    else if (status === 404) errorMessage.value = '图片来源不存在或无权访问。'
    else {
      errorMessage.value = '产品图片加载失败，请重试。'
      canRetry.value = true
    }
    return
  }

  // 切换 BOM 或产品后，较早请求的结果不能替换当前图片。
  if (version !== requestVersion) return
  loading.value = false
  const product = result.data.products.find(item => item.id === productLineId)
  if (!product) {
    errorMessage.value = '关联的产品明细不存在，请检查 BOM 来源。'
    return
  }
  const primaryImage = product.images[0]
  if (!primaryImage) return
  imageName.value = `${product.product_name || '产品'}图片`
  imageUrl.value = productionTaskBusinessFileUrl(taskId, primaryImage.id)
}

function handleImageError() {
  imageUrl.value = ''
  errorMessage.value = '图片文件加载失败，请重试。'
  canRetry.value = true
}

watch(() => [props.taskId, props.productLineId], loadImage, { immediate: true })
onBeforeUnmount(() => { requestVersion += 1 })
</script>

<template>
  <figure class="bom-product-image" aria-label="生产任务产品图片">
    <div class="bom-product-image__stage" :aria-busy="loading" @error.capture="handleImageError">
      <p v-if="loading" role="status">正在加载产品图片…</p>
      <div v-else-if="errorMessage" class="bom-product-image__message" role="alert">
        <p>{{ errorMessage }}</p>
        <el-button v-if="canRetry" size="small" @click="loadImage">重试</el-button>
      </div>
      <ProductImage v-else-if="imageUrl" :src="imageUrl" :name="imageName" large />
      <p v-else role="status">暂无产品图片</p>
    </div>
    <figcaption v-if="imageUrl">生产任务产品主图 · 点击查看大图</figcaption>
  </figure>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;

.bom-product-image { margin: 0; min-width: 0; }
.bom-product-image__stage {
  display: grid;
  place-items: center;
  width: 100%;
  min-height: 220px;
  max-height: 360px;
  aspect-ratio: 4 / 3;
  border: 1px solid token.$crm-border-default;
  border-radius: token.$crm-radius-2;
  background: token.$crm-color-surface;
  color: token.$crm-text-secondary;
  text-align: center;
  font-size: 13px;
  p { margin: 0; padding: 16px; }
  :deep(.product-image.large) {
    width: 100%;
    height: 100%;
    min-width: 0;
    min-height: 0;
    padding: 16px;
    border: 0;
    background: transparent;
    img { width: 100%; height: 100%; object-fit: contain; }
  }
}
.bom-product-image__message { padding-bottom: 16px; }
.bom-product-image figcaption { margin-top: 8px; color: token.$crm-text-secondary; text-align: center; font-size: 12px; }
</style>
