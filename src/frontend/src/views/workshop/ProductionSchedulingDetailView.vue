<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { ArrowRight, Back } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'

import { fetchSchedule, scheduleProductImageUrl, voidSchedule } from '@/api/productionScheduling'
import productImagePlaceholder from '@/assets/productionScheduling/product-image-placeholder.png'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { PlanCategory, ProductionSchedule, ScheduleProduct } from '@/types/productionScheduling'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const scheduleId = computed(() => String(route.params.scheduleId || ''))
const loading = ref(true)
const schedule = ref<ProductionSchedule | null>(null)
const etag = ref('')
const errorMessage = ref('')
const voidDialogVisible = ref(false)
const voidReason = ref('')
const voidReasonError = ref('')
const voiding = ref(false)
const canEdit = computed(() => schedule.value?.record_status === 'ACTIVE'
  && schedule.value.source_current_status === 'READY'
  && !schedule.value.source_is_archived
  && (auth.user?.is_superuser || auth.hasPermission('production_scheduling.change_productionschedule')))
const canVoid = computed(() => schedule.value?.record_status === 'ACTIVE' && (auth.user?.is_superuser || auth.hasPermission('production_scheduling.void_productionschedule')))
const planLinks: Array<{ category: PlanCategory; label: string; path: string }> = [
  { category: 'METAL', label: '查看金工计划', path: '/workshop/plans/metalworking' },
  { category: 'CUTTING', label: '查看裁剪计划', path: '/workshop/plans/cutting' },
  { category: 'SEWING', label: '查看车缝计划', path: '/workshop/plans/sewing' },
  { category: 'ASSEMBLY', label: '查看装配计划', path: '/workshop/plans/assembly' },
]
function errorText(error: unknown) {
  if (!(error instanceof AxiosError)) return '排产详情加载失败。'
  const data = error.response?.data as { error?: { message?: string } } | undefined
  return data?.error?.message || '排产详情加载失败。'
}
async function load() {
  loading.value = true
  try { const result = await fetchSchedule(scheduleId.value); schedule.value = result.data; etag.value = result.etag; errorMessage.value = '' }
  catch (error) { errorMessage.value = errorText(error) }
  finally { loading.value = false }
}
function productHasCategory(product: ScheduleProduct, category: PlanCategory) { return product.crafts.some(craft => craft.craft_type === 'INTERNAL' && craft.plan_category === category) }
function openPlan(link: typeof planLinks[number], product?: ScheduleProduct) {
  void router.push({ path: link.path, query: { schedule_id: scheduleId.value, ...(product ? { schedule_product_id: product.id } : {}) } })
}
function formatDate(value: string) { return value ? value.slice(0, 10) : '—' }
function craftTagClass(craft: ScheduleProduct['crafts'][number]) {
  if (craft.craft_type === 'EXTERNAL') return 'is-external'
  if (craft.plan_category === 'CUTTING') return 'is-cutting'
  if (craft.plan_category === 'SEWING') return 'is-sewing'
  if (craft.plan_category === 'ASSEMBLY') return 'is-assembly'
  return 'is-metal'
}
function openVoidDialog() {
  voidReason.value = ''
  voidReasonError.value = ''
  voidDialogVisible.value = true
}
function useProductImageFallback(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (image.dataset.fallbackApplied === 'true') return
  image.dataset.fallbackApplied = 'true'
  image.src = productImagePlaceholder
  image.classList.add('is-placeholder')
}
async function submitVoid() {
  const reason = voidReason.value.trim()
  if (reason.length < 2) {
    voidReasonError.value = '作废原因至少 2 个字。'
    return
  }
  if (voiding.value) return
  voiding.value = true
  voidReasonError.value = ''
  try {
    const result = await voidSchedule(scheduleId.value, reason, etag.value)
    schedule.value = result.data
    etag.value = result.etag
    voidDialogVisible.value = false
    ElMessage.success('排产计划已作废')
  } catch (error) {
    voidReasonError.value = errorText(error)
  } finally {
    voiding.value = false
  }
}
onMounted(() => { void load() })
</script>

<template>
  <section v-loading="loading" class="schedule-page schedule-detail" data-testid="production-scheduling-detail">
    <header class="schedule-heading detail-heading"><div><ElButton :icon="Back" @click="router.push('/workshop/scheduling')">返回</ElButton><h1>排产计划详情</h1></div><div><ElButton v-if="canVoid" @click="openVoidDialog">整单作废</ElButton><ElButton v-if="canEdit" type="primary" @click="router.push(`/workshop/scheduling/${scheduleId}/edit`)">编辑排产</ElButton></div></header>
    <ElAlert v-if="errorMessage" type="error" :title="errorMessage" show-icon :closable="false"><ElButton @click="load">重试</ElButton></ElAlert>
    <template v-if="schedule">
      <section class="schedule-section detail-basic"><header><h2>基本信息</h2></header><dl><div><dt>排产计划号</dt><dd>{{ schedule.schedule_number }}</dd></div><div><dt>生产任务单</dt><dd>{{ schedule.source.task_number }}</dd></div><div><dt>创建日期</dt><dd>{{ formatDate(schedule.created_at) }}</dd></div><div><dt>创建人</dt><dd>{{ schedule.created_by.name }}</dd></div><div><dt>交货日期</dt><dd>{{ formatDate(schedule.source.delivery_date) }}</dd></div><div><dt>版本</dt><dd>V{{ schedule.version }}</dd></div><div><dt>状态</dt><dd>{{ schedule.record_status_display }}</dd></div></dl></section>
      <section class="schedule-section detail-products"><header><h2>产品排产明细 <span>共 {{ schedule.products.length }} 个产品</span></h2></header>
        <article v-for="product in schedule.products" :key="product.id" class="schedule-product-card">
          <div class="schedule-product-card__body">
            <div class="detail-product-main"><img :src="product.image_file_id ? scheduleProductImageUrl(schedule.production_task_id, product.image_file_id) : productImagePlaceholder" :class="{ 'is-placeholder': !product.image_file_id }" :alt="`${product.product.product_name || '产品'}图片`" @error="useProductImageFallback" /><dl><div><dt>产品号</dt><dd>{{ product.product.item_number || product.product.product_number || '—' }}</dd></div><div><dt>产品名称</dt><dd>{{ product.product.product_name || '未命名产品' }}</dd></div><div><dt>规格</dt><dd>{{ product.product.specification || '—' }}</dd></div><div><dt>颜色</dt><dd>{{ product.product.color_name || '—' }}</dd></div></dl></div>
            <dl class="detail-quantities"><div><dt>订单数量</dt><dd>{{ product.source_quantity.toLocaleString('zh-CN') }} {{ product.unit_name }}</dd></div><div><dt>排产数量</dt><dd>{{ product.planned_quantity.toLocaleString('zh-CN') }} {{ product.unit_name }}</dd></div></dl>
            <section class="detail-dates"><h3>计划关键日期</h3><dl><div><dt>材料入库时间</dt><dd>{{ formatDate(product.material_inbound_date) }}</dd></div><div><dt>金工回货时间</dt><dd>{{ formatDate(product.metal_return_date) }}</dd></div><div><dt>车缝回货时间</dt><dd>{{ formatDate(product.sewing_return_date) }}</dd></div><div><dt>成品入库时间</dt><dd>{{ formatDate(product.finished_inbound_date) }}</dd></div></dl></section>
            <div class="detail-crafts"><h3>工艺选择</h3><div><span>厂内工艺</span><p><ElTag v-for="craft in product.crafts.filter(item => item.craft_type === 'INTERNAL')" :key="craft.id" effect="dark" :class="craftTagClass(craft)">{{ craft.name }}</ElTag><em v-if="!product.crafts.some(item => item.craft_type === 'INTERNAL')">—</em></p></div><div><span>厂外工艺</span><p><ElTag v-for="craft in product.crafts.filter(item => item.craft_type === 'EXTERNAL')" :key="craft.id" effect="dark" :class="craftTagClass(craft)">{{ craft.name }}</ElTag><em v-if="!product.crafts.some(item => item.craft_type === 'EXTERNAL')">—</em></p></div></div>
          </div>
          <div class="related-plans"><button v-for="link in planLinks.filter(item => productHasCategory(product, item.category))" :key="link.category" type="button" @click="openPlan(link, product)">{{ link.label }}<ElIcon><ArrowRight /></ElIcon></button></div>
        </article>
      </section>
    </template>
    <AppWindowDialog v-model="voidDialogVisible" title="整单作废" :width="520" :height="300" class="schedule-void-dialog" destroy-on-close :close-on-click-modal="!voiding" :close-on-press-escape="!voiding" :show-close="!voiding">
      <p>作废后该计划保留历史，可为同一生产任务单重新建立有效计划。</p>
      <ElInput v-model="voidReason" type="textarea" :rows="3" maxlength="200" show-word-limit placeholder="请输入作废原因" :disabled="voiding" @input="voidReasonError = ''" />
      <span v-if="voidReasonError" class="schedule-field-error">{{ voidReasonError }}</span>
      <template #footer><ElButton :disabled="voiding" @click="voidDialogVisible = false">取消</ElButton><ElButton type="primary" :loading="voiding" @click="submitVoid">确认作废</ElButton></template>
    </AppWindowDialog>
  </section>
</template>

<style lang="scss">@use '@/styles/productionScheduling.scss';</style>
<style scoped lang="scss">
.schedule-page.schedule-detail {
  min-height: calc(100dvh - 92px);
  margin-bottom: 0;
}
</style>
