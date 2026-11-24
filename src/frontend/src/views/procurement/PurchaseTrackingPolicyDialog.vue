<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { fetchPurchaseTrackingPolicy, updatePurchaseTrackingPolicy } from '@/api/purchaseTracking'
import type { PurchaseTrackingPolicy } from '@/types/purchaseTracking'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean]; saved: [] }>()
const loading = ref(false)
const loadFailed = ref(false)
const saving = ref(false)
const loaded = ref(false)
const canManage = ref(false)
const conflicted = ref(false)
const errorMessage = ref('')
const bomTimeoutDays = ref<number | null | undefined>(null)
const categoryLeadDays = ref<Record<string, number | null | undefined>>({})
const categories = ref<PurchaseTrackingPolicy['categories']>([])
const etag = ref('')
const canSave = computed(() => loaded.value && canManage.value && !loading.value && !loadFailed.value && !saving.value && !conflicted.value)
let controller: AbortController | undefined
let requestVersion = 0
let disposed = false

function failureText(error: unknown, fallback: string): string {
  const response = (error as { response?: { status?: number; data?: { error?: { message?: string } } } })?.response
  if (response?.status === 503) return '采购提醒时间规则尚未启用，请联系管理员完成启用后重试。'
  if (response?.status === 403) return '当前账号无权修改采购提醒设置。'
  return response?.data?.error?.message || fallback
}

async function load(): Promise<void> {
  const version = ++requestVersion
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  loadFailed.value = false
  errorMessage.value = ''
  try {
    const policy = await fetchPurchaseTrackingPolicy(controller.signal)
    if (disposed || version !== requestVersion) return
    bomTimeoutDays.value = policy.bom_timeout_days
    categories.value = policy.categories
    categoryLeadDays.value = Object.fromEntries(policy.categories.map(item => [item.key, policy.category_lead_days[item.key] ?? null]))
    etag.value = policy.etag
    canManage.value = policy.can_manage
    conflicted.value = false
    loaded.value = true
  } catch (error) {
    if (!disposed && version === requestVersion) {
      // 重新加载失败时保留草稿，但不沿用旧响应的可保存状态。
      loadFailed.value = true
      errorMessage.value = failureText(error, '提醒设置加载失败，请重新加载。')
    }
  } finally {
    if (!disposed && version === requestVersion) loading.value = false
  }
}

function validDays(value: number | null | undefined): boolean {
  return value === null || value === undefined || (Number.isInteger(value) && value >= 0 && value <= 365)
}

async function save(): Promise<void> {
  if (!canSave.value) return
  if (![bomTimeoutDays.value, ...Object.values(categoryLeadDays.value)].every(validDays)) {
    errorMessage.value = '天数须为 0～365 的整数；暂不设置可清空。'
    return
  }
  saving.value = true
  errorMessage.value = ''
  try {
    await updatePurchaseTrackingPolicy({
      bom_timeout_days: bomTimeoutDays.value ?? null,
      category_lead_days: Object.fromEntries(categories.value.map(item => [item.key, categoryLeadDays.value[item.key] ?? null])),
    }, etag.value)
    if (disposed) return
    emit('saved')
    emit('update:modelValue', false)
  } catch (error) {
    if (disposed) return
    const status = (error as { response?: { status?: number } })?.response?.status
    if (status === 412 || status === 428) {
      conflicted.value = true
      errorMessage.value = '规则版本已变化或已失效，输入已保留。请重新加载最新规则后再修改保存。'
    } else {
      if (status === 403) canManage.value = false
      errorMessage.value = failureText(error, '提醒设置保存失败，输入已保留，请重试。')
    }
  } finally {
    if (!disposed) saving.value = false
  }
}

function close(): void { if (!saving.value) emit('update:modelValue', false) }
watch(() => props.modelValue, value => {
  if (value) {
    loaded.value = false
    conflicted.value = false
    canManage.value = false
    void load()
  } else {
    requestVersion++
    controller?.abort()
    loading.value = false
  }
}, { immediate: true })
onBeforeUnmount(() => { disposed = true; requestVersion++; controller?.abort() })
</script>

<template>
  <AppWindowDialog :model-value="modelValue" title="采购提醒设置" :width="540" :minimizable="false" :close-on-click-modal="false" :close-on-press-escape="!saving" :before-close="close" destroy-on-close @update:model-value="value => { if (!value) close() }">
    <div v-loading="loading" class="purchase-policy-form" :aria-busy="loading || saving">
      <ElAlert v-if="errorMessage" type="error" :title="errorMessage" :closable="false">
        <ElButton v-if="!saving" link data-testid="reload-policy" :disabled="loading" @click="load">{{ loaded ? '重新加载（放弃当前修改）' : '重新加载' }}</ElButton>
      </ElAlert>
      <ElAlert v-if="loaded && !canManage" type="warning" title="当前账号无权修改采购提醒设置。" :closable="false" />
      <ElForm v-if="loaded" label-position="left" label-width="210px" :disabled="!canManage || loading || loadFailed || saving" @submit.prevent="save">
        <ElFormItem label="BOM确认后未买足提醒">
          <ElInputNumber v-model="bomTimeoutDays" :min="0" :max="365" :step="1" step-strictly controls-position="right" :disabled="!canManage || loading || loadFailed || saving" aria-label="BOM确认后未买足提醒天数" /><span class="day-unit">天</span>
        </ElFormItem>
        <p class="policy-help">从 BOM 确认时间起计时，未采购或未买足时提醒。</p>
        <h3>采购提前期</h3>
        <ElFormItem v-for="category in categories" :key="category.key" :label="category.label">
          <ElInputNumber v-model="categoryLeadDays[category.key]" :min="0" :max="365" :step="1" step-strictly controls-position="right" :disabled="!canManage || loading || loadFailed || saving" :aria-label="`${category.label}采购提前期天数`" /><span class="day-unit">天</span>
        </ElFormItem>
        <p class="policy-help">最晚采购日＝排产材料入库日－采购提前期。天数包含供货、运输和验收，按自然日计算，与到货催货的提前5天／3天分开。</p>
        <p class="policy-help">天数可设为 0～365 的整数；清空后提示“规则待设置”，缺日期时提示核对。</p>
      </ElForm>
      <p v-else-if="loading" class="policy-help">正在加载提醒设置…</p>
    </div>
    <template #footer>
      <ElButton data-testid="close-policy" :disabled="saving" @click="close">取消</ElButton>
      <ElButton data-testid="save-policy" type="primary" :loading="saving" :disabled="!canSave" @click="save">保存</ElButton>
    </template>
  </AppWindowDialog>
</template>

<style scoped lang="scss">
.purchase-policy-form { min-height: 80px; }
.purchase-policy-form .el-alert { margin-bottom: 16px; }
.purchase-policy-form .el-form-item { margin-bottom: 12px; }
.purchase-policy-form .el-input-number { width: 144px; }
.purchase-policy-form h3 { margin: 20px 0 12px; font-size: 14px; font-weight: 600; }
.day-unit { margin-left: 8px; }
.policy-help { margin: 8px 0; color: var(--erp-color-text-secondary); font-size: 12px; line-height: 20px; }
</style>
