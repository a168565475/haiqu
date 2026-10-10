<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'
import { fetchSample } from '@/api/samples'
import { reviewSampleApplication } from '@/api/sampleApplication'
import SampleApplicationSummary from '@/components/samples/SampleApplicationSummary.vue'
import SampleSection from '@/components/samples/SampleSection.vue'
import SampleStatusTag from '@/components/samples/SampleStatusTag.vue'
import type { SampleDetail } from '@/types/sample'
import { useSampleUnsavedChanges } from '@/composables/useSampleUnsavedChanges'

const route = useRoute()
const router = useRouter()
const sample = ref<SampleDetail | null>(null)
const etag = ref('')
const loading = ref(true)
const submitting = ref(false)
const errorMessage = ref('')
const opinion = ref('')
const actionError = ref('')
const closed = computed(() => sample.value != null && ['FINISHED', 'CONFIRMED', 'COMPLETED', 'REJECTED', 'CANCELLED'].includes(sample.value.status))
const actionDisabled = computed(() => loading.value || submitting.value || !sample.value?.application_actions?.can_director_review || Boolean(errorMessage.value))
let loadRequest = 0
useSampleUnsavedChanges(() => Boolean(opinion.value), '离开厂长确认页')

async function loadPage() {
  const request = ++loadRequest
  loading.value = true
  errorMessage.value = ''
  try {
    if (typeof route.params.sampleId !== 'string' || !route.params.sampleId) throw new Error('缺少申请编号，请从列表重新进入。')
    const result = await fetchSample(route.params.sampleId)
    if (request !== loadRequest) return
    sample.value = result.data
    etag.value = result.etag
  } catch (error) {
    if (request !== loadRequest) return
    sample.value = null
    etag.value = ''
    if (error instanceof AxiosError && error.response?.status === 403) errorMessage.value = '当前账号没有查看此申请的权限。'
    else errorMessage.value = error instanceof AxiosError && error.response?.status === 404 ? '未找到此打样申请。' : '申请加载失败，请重试。'
  } finally { if (request === loadRequest) loading.value = false }
}

async function explainAction(returnToSales: boolean) {
  if (!sample.value || actionDisabled.value) return
  actionError.value = ''
  submitting.value = true
  try {
    await reviewSampleApplication({ sampleId: sample.value.id, etag: etag.value, decision: returnToSales ? 'return' : 'approve', note: opinion.value })
    opinion.value = ''
    ElMessage.success(returnToSales ? '已退回业务员补充。' : '已确认可做，交打样部填写材料需求。')
    await loadPage()
  } catch (error) {
    actionError.value = error instanceof AxiosError
      ? error.response?.data?.error?.message || '处理失败，请刷新申请后重试，填写意见已保留。'
      : error instanceof Error ? error.message : '处理失败，请重试。'
  }
  finally { submitting.value = false }
}
onMounted(loadPage)
onBeforeUnmount(() => { loadRequest++ })
</script>

<template>
  <section class="director-page" data-figma-node="1812:18474">
    <div v-loading="loading" class="director-content">
      <header class="director-heading">
        <div><h1>厂长确认打样申请</h1><SampleStatusTag v-if="sample" appearance="page" :status="sample.status" :label="sample.status_display" /></div>
        <div class="director-heading-actions">
          <ElButton class="back-button" :disabled="submitting" @click="router.push({ name: 'samples' })">返回列表</ElButton>
          <div class="action-buttons">
            <ElButton :disabled="actionDisabled" @click="explainAction(true)">退回不出</ElButton>
            <ElButton type="primary" :disabled="actionDisabled" @click="explainAction(false)">确认可做</ElButton>
          </div>
        </div>
      </header>
      <p v-if="actionError" class="director-action-error" role="alert">{{ actionError }}</p>
      <p v-else-if="closed" class="readonly-hint">当前申请流程已结束，仅供查看。</p>
      <div v-if="errorMessage" class="director-error" role="alert"><p>{{ errorMessage }}</p><ElButton :disabled="loading" @click="loadPage">重新加载</ElButton></div>
      <template v-else-if="sample">
        <SampleApplicationSummary :sample="sample" />
        <SampleSection title="厂长处理" class="director-decision">
          <p>核对产品是否可做；确认后交打样部，需补充信息时退回业务员。</p>
          <label for="director-opinion">处理意见（退回时必填）</label>
          <ElInput id="director-opinion" v-model="opinion" :disabled="actionDisabled" type="textarea" :rows="2" maxlength="500" show-word-limit resize="none" placeholder="请输入处理意见或需要业务员补充的内容" />
        </SampleSection>
      </template>
    </div>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/crm/tokens' as token;
@use '@/styles/crm/sample-controls' as sample;
.director-page { @include sample.controls; display: flex; height: calc(100dvh - 92px); flex-direction: column; color: token.$crm-text-primary; background: token.$crm-color-page; }
.director-content { flex: 1; min-height: 0; overflow-y: auto; }
.director-heading { display: flex; min-height: 44px; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
.director-heading > div { display: flex; align-items: center; gap: 16px; }
.director-heading :deep(.sample-page-status) { min-width: 0; height: 24px !important; min-height: 24px !important; padding: 2px 10px; border-radius: 12px; font-size: 12px; line-height: 20px !important; }
h1 { margin: 0; font-family: token.$crm-font-display; font-size: 34px; line-height: 44px; }
.director-decision { height: 168px; margin-top: 18px; padding: 12px 24px 8px; }
.director-decision :deep(h2) { margin-bottom: 4px; }
.director-decision p { margin: 0 0 4px; color: token.$crm-text-secondary; font-size: 12px; line-height: 22px; }
.director-decision label { display: block; margin-bottom: 4px; font-size: 13px; line-height: 22px; }
.director-decision :deep(.el-textarea__inner) { height: 52px; padding: 4px 12px; box-shadow: inset 0 0 0 1px token.$crm-border-subtle; font-size: 13px; line-height: 22px; }
.director-decision :deep(.el-input__count) { bottom: 4px; line-height: 22px; background: token.$crm-color-surface; }
.director-heading-actions { display: flex; flex: none; align-items: center; gap: 10px; }
.director-heading .action-buttons { display: flex; gap: 10px; }
.action-buttons :deep(.el-button) { width: auto; height: 32px; padding: 0 16px; border-radius: 5px; font-size: 13px; }
.action-buttons :deep(.el-button--primary) { background: sample.$action-primary; border-color: sample.$action-primary; }
.director-action-error, .director-error { color: token.$crm-danger; font-size: 13px; }
.readonly-hint { color: token.$crm-text-secondary; font-size: 13px; }
</style>
