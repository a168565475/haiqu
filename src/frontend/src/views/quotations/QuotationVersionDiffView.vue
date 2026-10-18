<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Box, Coin, CopyDocument, Document, Tickets } from '@element-plus/icons-vue'
import { AxiosError } from 'axios'
import { ElMessage } from 'element-plus'

import { createQuotationVersion, fetchQuotation, fetchQuotationVersion, fetchQuotationVersionDiff } from '@/api/quotations'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { useAuthStore } from '@/stores/auth'
import type { QuotationDetail, QuotationVersionDetail, QuotationVersionDiff } from '@/types/quotation'
import { useQuotationWorkflow } from './workflow/quotationWorkflow'
import '@fontsource-variable/noto-sans-sc'
import '@fontsource-variable/noto-serif-sc'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const quotationId = computed(() => String(route.params.quotationId || ''))
const quotation = ref<QuotationDetail | null>(null)
const baseVersion = ref<QuotationVersionDetail | null>(null)
const compareVersion = ref<QuotationVersionDetail | null>(null)
const diff = ref<QuotationVersionDiff | null>(null)
const baseVersionId = ref('')
const compareVersionId = ref('')
const loading = ref(true)
const comparing = ref(false)
const creating = ref(false)
const errorMessage = ref('')
const errorStatus = ref<number | null>(null)
const conflictMessage = ref('')
const versionWorkflow = useQuotationWorkflow('F06-S01')

const sortedVersions = computed(() => [...(quotation.value?.versions || [])].sort((left, right) => right.version_number - left.version_number))
const hasSingleVersion = computed(() => sortedVersions.value.length === 1)
const canCreateVersion = computed(() => Boolean(quotation.value?.allowed_actions.create_version && authStore.hasPermission('quotations.add_quotationversion')))
const sectionCounts = computed(() => {
  const changes = diff.value?.changes || []
  return ['商业快照', '产品与数量', '价格与装柜量', '条款与有效期'].map(section => ({ section, count: changes.filter(item => item.section === section).length }))
})
const totalDifference = computed(() => {
  if (!baseVersion.value || !compareVersion.value) return null
  return Number(compareVersion.value.total_amount) - Number(baseVersion.value.total_amount)
})
const errorTitle = computed(() => {
  if (errorStatus.value === 403) return '历史版本无权限'
  if (errorStatus.value === 404) return '比较数据缺失'
  return '报价版本加载失败'
})

function readableError(error: unknown) {
  if (!(error instanceof AxiosError)) return error instanceof Error ? error.message : '加载失败，请稍后重试。'
  if (!error.response) return '网络异常，请检查连接后重试。'
  if (error.response.status === 401) return '登录状态已失效，请重新登录。'
  if (error.response.status === 403) return '当前账号没有查看报价版本的权限。'
  if (error.response.status === 404) return '报价或版本不存在。'
  return (error.response.data as { error?: { message?: string } }).error?.message || '报价版本服务暂时异常，请稍后重试。'
}

function statusType(status: string) {
  return ({ DRAFT: 'info', SENT: 'success', ISSUED: 'warning', VOID: 'danger', SUPERSEDED: 'info' }[status] || 'info') as 'info' | 'success' | 'warning' | 'danger'
}

function statusLabel(status: string) {
  return ({ DRAFT: '草稿', LOCKED: '已锁定', ISSUED: '已签发', SENT: '已发送', SUPERSEDED: '已替代', VOID: '已作废' }[status] || status)
}

function responseStatus(error: unknown) {
  return error instanceof AxiosError ? error.response?.status || null : null
}

function formatAmount(value: number) {
  return `${value >= 0 ? '+' : ''}${value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

async function compare() {
  if (!baseVersionId.value || !compareVersionId.value) return
  comparing.value = true
  versionWorkflow.setState('F06-S02')
  errorMessage.value = ''
  try {
    const [baseResult, compareResult, diffResult] = await Promise.all([
      fetchQuotationVersion(baseVersionId.value),
      fetchQuotationVersion(compareVersionId.value),
      fetchQuotationVersionDiff(compareVersionId.value, baseVersionId.value),
    ])
    baseVersion.value = baseResult.data
    compareVersion.value = compareResult.data
    diff.value = diffResult
    versionWorkflow.reset('F06-S02')
  } catch (error) {
    errorStatus.value = responseStatus(error)
    errorMessage.value = readableError(error)
    versionWorkflow.reset(responseStatus(error) === 409 || responseStatus(error) === 412 ? 'F06-S05' : 'F06-S01')
  } finally {
    comparing.value = false
  }
}

async function loadPage() {
  loading.value = true
  errorMessage.value = ''
  errorStatus.value = null
  try {
    const result = await fetchQuotation(quotationId.value)
    quotation.value = result.data
    const latest = [...result.data.versions].sort((left, right) => right.version_number - left.version_number)[0]
    if (!latest) throw new Error('该报价尚未创建版本。')
    compareVersionId.value = latest.id
    baseVersionId.value = latest.parent_version || result.data.versions.filter(item => item.version_number < latest.version_number).sort((left, right) => right.version_number - left.version_number)[0]?.id || latest.id
    if (result.data.versions.length === 1) {
      const onlyVersion = await fetchQuotationVersion(latest.id)
      baseVersion.value = onlyVersion.data
      compareVersion.value = onlyVersion.data
      diff.value = { base_version: null, compare_version: latest.id, changes: [] }
      versionWorkflow.reset('F06-S06')
    } else {
      await compare()
    }
  } catch (error) {
    errorStatus.value = responseStatus(error)
    errorMessage.value = readableError(error)
  } finally {
    loading.value = false
  }
}

async function createCopy(sourceVersionId = compareVersionId.value) {
  if (!quotation.value || !sourceVersionId || !canCreateVersion.value) return
  creating.value = true
  versionWorkflow.reset('F06-S03')
  try {
    const source = quotation.value.versions.find(item => item.id === sourceVersionId)
    if (!source) throw new Error('找不到要复制的版本。')
    const result = await createQuotationVersion(quotation.value.id, {
      currency_code: source.currency_code,
      valid_until: source.valid_until,
      from_version_id: sourceVersionId,
    }, (await fetchQuotation(quotation.value.id)).etag)
    versionWorkflow.reset('F06-S04')
    ElMessage.success(`已基于 V${source.version_number} 创建新的草稿版本。`)
    await router.push({ name: 'quotation-edit', params: { quotationId: quotation.value.id }, query: { version: result.data.id } })
  } catch (error) {
    const status = responseStatus(error)
    if (status === 409 || status === 412) {
      versionWorkflow.reset('F06-S05')
      conflictMessage.value = '报价版本已被其他用户更新。为避免覆盖最新内容，请重新加载版本树后再创建副本。'
    } else {
      versionWorkflow.reset(hasSingleVersion.value ? 'F06-S06' : 'F06-S01')
      ElMessage.error(readableError(error))
    }
  } finally {
    creating.value = false
  }
}

async function selectCompareVersion(versionId: string) {
  compareVersionId.value = versionId
  await compare()
}

function versionDetail(versionId: string) {
  if (compareVersion.value?.id === versionId) return compareVersion.value
  if (baseVersion.value?.id === versionId) return baseVersion.value
  return null
}

function versionQuantity(versionId: string) {
  const detail = versionDetail(versionId)
  if (!detail) return '—'
  const quantity = detail.lines.reduce((total, item) => total + Number(item.quantity || 0), 0)
  const unit = detail.lines[0]?.unit_code || ''
  return `${quantity.toLocaleString('zh-CN')} ${unit}`.trim()
}

function formatVersionTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).replaceAll('/', '-')
}

onMounted(() => { void loadPage() })
</script>

<template>
  <section v-loading="loading || comparing" class="version-diff-page" aria-label="报价版本对比">
    <template v-if="quotation && compareVersion && baseVersion">
      <header class="page-header">
        <div><h1>报价版本对比</h1><p>报价编号：{{ quotation.quotation_number }}　｜　客户：{{ quotation.customer_name }}　｜　产品：{{ compareVersion.lines[0]?.product_description_snapshot || '—' }}　｜　币种：{{ compareVersion.currency_code }}　｜　贸易条款：{{ compareVersion.incoterm_label || '—' }}　｜　有效期：{{ compareVersion.valid_until || '—' }}</p></div>
        <div class="header-actions"><div><ElButton class="black-button" :icon="CopyDocument" :loading="creating" :disabled="!canCreateVersion" :title="canCreateVersion ? '' : '当前账号没有创建报价版本权限'" @click="createCopy(compareVersionId)">基于V{{ compareVersion.version_number }}创建副本</ElButton><ElButton :icon="Document" @click="router.push({ name: 'quotation-preview', params: { quotationId }, query: { version: compareVersionId } })">查看当前版本</ElButton></div></div>
      </header>

      <div class="f06-layout">
        <ElCard class="version-sidebar" shadow="never">
          <template #header><div class="section-heading"><b>版本记录</b></div></template>
          <div class="version-list"><button v-for="item in sortedVersions" :key="item.id" class="version-node" :class="{ selected: item.id === compareVersionId }" @click="selectCompareVersion(item.id)"><span class="version-dot"></span><div><strong>V{{ item.version_number }}</strong><ElTag :type="statusType(item.status)" size="small">{{ statusLabel(item.status) }}</ElTag></div><small>{{ formatVersionTime(item.updated_at) }}</small><b>{{ item.id === compareVersionId ? '当前版本' : versionQuantity(item.id) }}</b></button></div>
        </ElCard>

        <ElCard class="comparison-workspace" shadow="never">
          <div class="compare-controls"><label><span>基准版本</span><ElSelect v-model="baseVersionId" aria-label="基准版本" @change="compare"><ElOption v-for="item in sortedVersions" :key="item.id" :label="`V${item.version_number}（${statusLabel(item.status)}）`" :value="item.id" /></ElSelect></label><span class="swap-mark">⇄</span><label><span>对比版本</span><ElSelect v-model="compareVersionId" aria-label="对比版本" :disabled="hasSingleVersion" @change="compare"><ElOption v-for="item in sortedVersions" :key="item.id" :label="`V${item.version_number}（${statusLabel(item.status)}）`" :value="item.id" /></ElSelect></label></div>
          <section class="difference-overview"><h2>差异概览</h2><div class="stat-row"><div v-for="(item, index) in sectionCounts" :key="item.section"><span class="stat-icon"><ElIcon><Tickets v-if="index===0"/><Box v-else-if="index===1"/><Coin v-else-if="index===2"/><Document v-else/></ElIcon></span><p><span>{{ item.section }}</span><b>{{ hasSingleVersion ? '—' : item.count }}</b><small v-if="!hasSingleVersion">项差异</small></p></div></div></section>
          <div class="comparison-panels"><section><header>基准版本　V{{ baseVersion.version_number }} <ElTag :type="statusType(baseVersion.status)" size="small">{{ statusLabel(baseVersion.status) }}</ElTag></header><div v-if="hasSingleVersion" class="comparison-empty"><ElIcon><Document /></ElIcon><b>暂无其他版本可比较</b></div><dl v-else><template v-for="(item,index) in diff?.changes" :key="`before-${index}`"><dt>{{ item.field }}</dt><dd>{{ item.before }}</dd></template></dl></section><section><header>对比版本　<template v-if="!hasSingleVersion">V{{ compareVersion.version_number }} <ElTag :type="statusType(compareVersion.status)" size="small">{{ statusLabel(compareVersion.status) }}</ElTag></template><ElTag v-else type="info" size="small">未选择</ElTag></header><div v-if="hasSingleVersion" class="comparison-empty"><ElIcon><Document /></ElIcon><b>当前报价只有一个版本</b></div><dl v-else><template v-for="(item,index) in diff?.changes" :key="`after-${index}`"><dt>{{ item.field }}</dt><dd>{{ item.after }}</dd></template></dl></section></div>
          <div class="total-difference"><ElIcon><Coin /></ElIcon><b>总价差异</b><strong>{{ hasSingleVersion || totalDifference === null ? '—' : `${totalDifference > 0 ? '↑ ' : totalDifference < 0 ? '↓ ' : ''}${compareVersion.currency_code} ${formatAmount(totalDifference)}` }}</strong><span>{{ hasSingleVersion ? '暂无对比。' : `V${baseVersion.version_number} 与 V${compareVersion.version_number} 的总价差异` }}</span></div>
        </ElCard>
      </div>
    </template>
    <ElResult v-else-if="errorMessage" :icon="errorStatus === 403 ? 'warning' : 'error'" :title="errorTitle" :sub-title="errorMessage"><template #extra><ElButton @click="router.push({ name: 'quotations' })">返回报价列表</ElButton><ElButton v-if="errorStatus !== 403" class="black-button" @click="loadPage">重新加载</ElButton></template></ElResult>
    <AppWindowDialog :model-value="Boolean(conflictMessage)" title="版本冲突" :width="520" :height="280" :show-close="false" @update:model-value="value => { if (!value) conflictMessage = '' }">
      <ElAlert :title="conflictMessage" type="error" :closable="false" show-icon />
      <template #footer><ElButton @click="conflictMessage = ''">取消</ElButton><ElButton class="black-button" @click="conflictMessage = ''; loadPage()">加载最新版本</ElButton></template>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/theme/detail' as detail;
.version-diff-page { min-width: 0; color: var(--erp-color-text-primary); --el-color-primary: var(--erp-color-brand); font-family: var(--erp-font-body); font-size: 13px; }
.page-header { display: flex; align-items: baseline; gap: 14px; min-height: 0; flex-wrap: wrap; margin-bottom: 14px; }
.page-header h1 { margin: 0; font-family: var(--erp-font-body); font-size: 36px; font-weight: 700; line-height: 44px; }
.page-header p { margin: 0; color: var(--erp-color-text-secondary); font-size: 13px; }
.black-button { color: var(--erp-button-primary-text)!important; border-color: var(--erp-button-primary-border) !important; background: var(--erp-button-primary-surface)!important; }
.version-record-card,.difference-overview,.detail-difference { margin-bottom: 14px; border: 1px solid var(--erp-color-border); border-radius: 5px; background: var(--erp-color-surface); box-shadow: none; }
.version-record-card :deep(.el-card__header),.difference-overview :deep(.el-card__header),.detail-difference :deep(.el-card__header) { min-height: 52px; padding: 0 20px; border-bottom: 0; }
.section-heading { display: flex; align-items: center; min-height: 48px; }
.section-heading b { font-family: var(--erp-font-body); font-size: 20px; }
.version-record-card :deep(.el-card__body) { padding: 0 20px 20px; }
.version-record-content { display: grid; grid-template-columns: 620px minmax(0,1fr); gap: 40px; align-items: center; }
.version-list { display: grid; grid-template-columns: repeat(2,minmax(230px,1fr)); gap: 16px; }
.version-node { position: relative; display: grid; gap: 8px; min-height: 106px; box-sizing: border-box; padding: 16px 24px; border: 1px solid var(--erp-color-border); border-radius: 8px; color: var(--erp-color-text-primary); background: var(--erp-color-surface); text-align: left; cursor: pointer; }
.version-node.selected { border-color: var(--erp-color-brand); background: var(--erp-color-selected); }
.version-node > div { display: flex; align-items: center; gap: 14px; }
.version-node strong { font-family: var(--erp-font-body); font-size: 22px; }
.version-node small,.version-node span { color: var(--erp-color-text-regular); font-size: 13px; }
.version-node i { position: absolute; top: 39px; right: 22px; color: var(--erp-color-text-regular); font-size: 25px; font-style: normal; }
.version-node :deep(.el-tag) { border: 0; border-radius: 999px; }
.compare-controls { display: grid; grid-template-columns: minmax(190px,1fr) minmax(190px,1fr) minmax(220px,1.15fr); gap: 14px 20px; align-items: end; }
.compare-controls label { display: grid; grid-template-columns: 84px 1fr; align-items: center; gap: 12px; color: var(--erp-color-text-regular); font-size: 14px; }
.compare-controls :deep(.el-select__wrapper) { height: 32px; min-height: 32px; border-radius: var(--erp-radius-control); background: var(--erp-input-surface); box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-border) inset; }
.compare-controls :deep(.el-select__wrapper.is-focused) { box-shadow: var(--erp-input-shadow), 0 0 0 1px var(--erp-input-focus-border) inset; }
.compare-actions { grid-column: 3; grid-row: 1 / span 2; display: grid; gap: 12px; }
.compare-actions :deep(.el-button) { width: 100%; height: 48px; margin: 0; border-radius: 4px; font-size: 15px; }
.difference-overview :deep(.el-card__body) { padding: 0 20px 20px; }
.stat-row { display: grid; grid-template-columns: repeat(4,1fr); gap: 16px; }
.stat-row > div { display: flex; align-items: center; gap: 24px; min-height: 96px; box-sizing: border-box; padding: 16px 22px; border: 1px solid var(--erp-color-border); border-radius: 4px; background: var(--erp-color-surface); }
.stat-icon { display: grid; width: 48px; height: 48px; flex: none; place-items: center; border-radius: 50%; color: var(--erp-color-brand)!important; background: var(--erp-color-subtle); font-size: 26px!important; }
.stat-row p { display: grid; grid-template-columns: auto auto; align-items: end; gap: 2px 8px; margin: 0; }
.stat-row p > span { grid-column: 1 / -1; color: var(--erp-color-info); font-size: 16px; }
.stat-row p b { color: var(--erp-color-text-primary); font-family: var(--erp-font-body); font-size: 30px; font-weight: 600; line-height: 32px; }
.stat-row p small { color: var(--erp-color-text-regular); font-size: 13px; }
.detail-difference :deep(.el-card__body) { padding: 0 20px 20px; }
.diff-table-wrap { overflow: auto; }
.diff-table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 14px; }
.diff-table th { height: 42px; padding: 0 20px; color: var(--erp-color-info); background: var(--erp-table-header-background); font-weight: 500; text-align: left; }
.diff-table td { height: 42px; padding: 0 20px; border-bottom: 1px solid var(--erp-table-border); color: var(--erp-table-text); }
.diff-table th:first-child { width: 15%; }.diff-table th:nth-child(2),.diff-table th:nth-child(3) { width: 25%; }.diff-table th:last-child { width: 25%; }
.after-value { color: var(--erp-color-brand)!important; font-weight: 600; }
.single-version-state { display: grid; place-items: center; min-height: 330px; text-align: center; }
.single-version-state p { margin: -8px 0 10px; color: var(--erp-color-text-regular); font-size: 13px; }
.single-version-state > div { display: flex; gap: 12px; }
:global(.version-diff-page .el-dialog) { border-radius: 6px; background: var(--erp-color-page); }
@media(max-width:1500px){.version-record-content{grid-template-columns:520px minmax(0,1fr)}.compare-controls{grid-template-columns:minmax(160px,1fr) minmax(160px,1fr) minmax(190px,1fr)}}

/* F06 方案 2：版本记录与差异比较 */
.page-header { justify-content: space-between; align-items: flex-start; min-height: 0; gap: 14px; flex-wrap: wrap; margin-bottom: 14px; }
.page-header > div:first-child { display: grid; gap: 2px; }
.page-header h1 { line-height: 44px; font-family: var(--erp-font-body); font-size: 36px; font-weight: 700; }
.page-header p { color: var(--erp-color-text-regular); font-size: 13px; white-space: nowrap; }
.header-actions { display: grid; justify-items: end; gap: 12px; padding-top: 8px; min-width: 0; flex-wrap: wrap; }
.header-actions small { color: var(--erp-color-text-regular); font-size: 12px; }
.header-actions > div { display: flex; gap: 14px; }
.header-actions :deep(.el-button) { min-width: 138px; height: 32px; margin: 0; border-radius: 8px; }
.header-actions .black-button { min-width: 208px; }
.f06-layout { display: grid; grid-template-columns: 260px minmax(0,1fr); gap: 14px; min-height: 0; }
.version-sidebar,.comparison-workspace {
 @include detail.surface; }
.version-sidebar :deep(.el-card__header) { min-height: 48px; padding: 0 16px; border-bottom: 1px solid var(--erp-color-border); }
.section-heading { min-height: 48px; }
.section-heading b { font-size: 21px; }
.version-sidebar :deep(.el-card__body) { padding: 16px; }
.version-list { display: grid; grid-template-columns: 1fr; gap: 10px; }
.version-node { position: relative; display: grid; grid-template-columns: 20px 1fr; gap: 5px 8px; min-height: 106px; padding: 14px 16px; border: 0; border-left: 3px solid transparent; border-radius: 8px; background: var(--erp-color-subtle); }
.version-node.selected { border-left-color: var(--erp-color-brand); background: var(--erp-color-selected); }
.version-dot { grid-row: 1 / span 3; align-self: start; width: 10px; height: 10px; margin-top: 7px; border-radius: 50%; background: var(--erp-color-warning); }
.version-node > div { justify-content: flex-start; }
.version-node strong { font-size: 20px; }
.version-node small,.version-node > b { grid-column: 2; color: var(--erp-color-text-regular); font-size: 13px; font-weight: 400; }
.comparison-workspace :deep(.el-card__body) { display: grid; grid-template-rows: auto auto auto auto; gap: 14px; height: auto; box-sizing: border-box; padding: 16px; }
.compare-controls { display: grid; grid-template-columns: minmax(0,1fr) 40px minmax(0,1fr); align-items: center; gap: 18px; }
.compare-controls label { display: grid; grid-template-columns: 82px minmax(0,1fr); align-items: center; gap: 12px; color: var(--erp-color-info); font-size: 14px; font-weight: 600; }
.compare-controls :deep(.el-select__wrapper) { height: 32px; min-height: 32px; }
.swap-mark { color: var(--erp-color-info); font-size: 22px; text-align: center; }
.comparison-workspace .difference-overview { @include detail.inset; display: grid; gap: 12px; margin: 0; padding: 14px; }
.difference-overview h2 { margin: 0; font-family: var(--erp-font-body); font-size: 20px; }
.comparison-workspace .stat-row { gap: 0; }
.comparison-workspace .stat-row > div { min-height: 82px; padding: 10px 30px; border: 0; border-right: 1px solid var(--erp-color-border); background: transparent; }
.comparison-workspace .stat-row > div:last-child { border-right: 0; }
.comparison-workspace .stat-icon { color: var(--erp-color-info)!important; background: transparent; }
.comparison-workspace .stat-row p b { color: var(--erp-color-info); font-size: 26px; }
.comparison-panels { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; min-height: 0; }
.comparison-panels > section { @include detail.inset; display: grid; grid-template-rows: auto auto; overflow: visible; }
.comparison-panels header { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid var(--erp-color-border); background: var(--erp-color-subtle); font-size: 13px; font-weight: 600; min-height: 40px; flex-wrap: wrap; }
.comparison-panels header :deep(.el-tag) { border: 0; border-radius: 999px; }
.comparison-empty { display: grid; place-content: center; justify-items: center; gap: 12px; color: var(--erp-color-text-secondary); }
.comparison-empty :deep(.el-icon) { color: var(--erp-color-text-muted); font-size: 52px; }
.comparison-empty b { font-size: 14px; font-weight: 500; }
.comparison-panels dl { display: grid; grid-template-columns: minmax(90px,.55fr) minmax(0,1fr); align-content: start; margin: 0; padding: 12px 14px; font-size: 13px; overflow-wrap: anywhere; }
.comparison-panels dt,.comparison-panels dd { margin: 0; padding: 10px 0; border-bottom: 1px solid var(--erp-color-border); }
.comparison-panels dt { color: var(--erp-color-text-regular); }.comparison-panels dd { color: var(--erp-color-text-primary); font-weight: 600; }
.total-difference { @include detail.inset; display: grid; grid-template-columns: 24px auto minmax(0,160px); align-items: center; gap: 12px; padding: 14px; color: var(--erp-color-text-primary); }
.total-difference :deep(.el-icon) { color: var(--erp-color-brand); font-size: 24px; }.total-difference strong { color: var(--erp-color-brand); font-size: 18px; }.total-difference span { padding-left: 24px; border-left: 1px solid var(--erp-color-border); color: var(--erp-color-text-regular); }
@media(max-width:1500px){.f06-layout{grid-template-columns:280px minmax(0,1fr)}.comparison-workspace .stat-row > div{padding-inline:14px}.page-header p{font-size:12px}}
.total-difference > span { grid-column:2 / -1; }
@media (max-width:1200px) { .f06-layout { grid-template-columns:220px minmax(0,1fr); } .comparison-workspace .stat-row { grid-template-columns:repeat(2,minmax(0,1fr)); } .compare-controls label { grid-template-columns:minmax(0,1fr); gap:6px; } }
@media (max-width:800px) { .f06-layout { grid-template-columns:minmax(0,1fr); } .version-list { grid-template-columns:repeat(2,minmax(0,1fr)); } .comparison-panels { grid-template-columns:minmax(0,1fr); } }
</style>
