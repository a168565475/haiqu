<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { MoreFilled, Picture } from '@element-plus/icons-vue'

import ComplaintEditDialog from '@/components/complaints/ComplaintEditDialog.vue'
import ComplaintImagePreview from '@/components/complaints/ComplaintImagePreview.vue'
import ComplaintProgressDialog from '@/components/complaints/ComplaintProgressDialog.vue'
import { fetchComplaint, fetchComplaintOptions } from '@/api/complaints'
import { useOptions } from '@/composables/useOptions'
import { useAuthStore } from '@/stores/auth'
import type { Complaint, ComplaintAttachment, ComplaintDictionaryItem, ComplaintOptions, ComplaintStatus } from '@/types/complaint'
import { complaintDate, complaintRequestMessage } from '@/utils/complaintFeedback'

const route = useRoute()
const authStore = useAuthStore()
const complaintId = computed(() => String(route.params.complaintId || ''))
const complaint = ref<Complaint | null>(null)
const etag = ref<string | null>(null)
const options = ref<ComplaintOptions | null>(null)
const loading = ref(false)
const errorMessage = ref('')
const conflictMessage = ref('')
const editVisible = ref(false)
const progressVisible = ref(false)
const progressTarget = ref<ComplaintStatus | null>(null)
const previewVisible = ref(false)
const previewAttachment = ref<ComplaintAttachment | null>(null)
const complaintTypeSource = useOptions('COMPLAINT_TYPE', computed(() => complaint.value?.complaint_type.id))
const severitySource = useOptions('COMPLAINT_SEVERITY', computed(() => complaint.value?.severity.id))
const canEdit = computed(() => authStore.hasPermission('customers.change_customercomplaint'))
const canProcess = computed(() => authStore.hasPermission('customers.process_customer_complaint'))
const canClose = computed(() => authStore.hasPermission('customers.close_customer_complaint'))
const terminal = computed(() => ['CLOSED', 'CANCELLED'].includes(complaint.value?.status || ''))
const workflowSteps: Array<{ value: ComplaintStatus; label: string }> = [
  { value: 'ACCEPTED', label: '已受理' }, { value: 'RESPONSIBILITY_CONFIRMATION', label: '责任确认' },
  { value: 'SOLUTION_PLANNING', label: '方案制定' }, { value: 'CUSTOMER_CONFIRMATION', label: '客户确认' },
  { value: 'CLOSED', label: '关闭' },
]
const currentStepIndex = computed(() => Math.max(0, workflowSteps.findIndex(item => item.value === complaint.value?.status)))
const nextStatus = computed<ComplaintStatus>(() => {
  const map: Partial<Record<ComplaintStatus, ComplaintStatus>> = {
    ACCEPTED: 'RESPONSIBILITY_CONFIRMATION', RESPONSIBILITY_CONFIRMATION: 'SOLUTION_PLANNING',
    SOLUTION_PLANNING: 'CUSTOMER_CONFIRMATION', CUSTOMER_CONFIRMATION: 'CLOSED',
  }
  return map[complaint.value?.status || 'ACCEPTED'] || (complaint.value?.status as ComplaintStatus) || 'ACCEPTED'
})
const primaryActionText = computed(() => nextStatus.value === 'CLOSED' ? '关闭客诉' : '更新进展')
const slaText = computed(() => {
  if (!complaint.value) return ''
  if (complaint.value.sla_status === 'OVERDUE') return `SLA 已超时 · ${complaintDate(complaint.value.target_completion_at)}`
  if (complaint.value.sla_status === 'AT_RISK') return `SLA 即将到期 · ${complaintDate(complaint.value.target_completion_at)}`
  if (complaint.value.sla_status === 'COMPLETED') return 'SLA 已结束'
  return `SLA 目标 · ${complaintDate(complaint.value.target_completion_at)}`
})

function publishedItems(source: typeof complaintTypeSource, fallback: ComplaintDictionaryItem[] = []) {
  if (!source.options.value.length) return fallback
  return source.options.value.map(item => ({
    id: item.id, item_code: item.code, display_name: item.label,
    description: typeof item.extra.description === 'string' ? item.extra.description : '',
    sort_order: item.sort_order, extra_data: item.extra as Record<string, string | number>, disabled: item.status !== 'ACTIVE',
  }))
}
const complaintTypes = computed(() => publishedItems(complaintTypeSource, options.value?.complaint_types))
const severities = computed(() => publishedItems(severitySource, options.value?.severities))

async function load() {
  loading.value = true
  errorMessage.value = ''
  conflictMessage.value = ''
  try {
    const result = await fetchComplaint(complaintId.value)
    complaint.value = result.data
    etag.value = result.etag
  } catch (error) {
    complaint.value = null
    errorMessage.value = complaintRequestMessage(error)
  } finally { loading.value = false }
}

function acceptUpdate(updated: Complaint, nextEtag: string | null) {
  complaint.value = updated
  etag.value = nextEtag
  conflictMessage.value = ''
}

function openProgress(target: ComplaintStatus = nextStatus.value) {
  if (!canProcess.value || terminal.value) return
  if (target === 'CLOSED' && !canClose.value) return ElMessage.warning('当前账号没有关闭客诉的权限。')
  progressTarget.value = target
  progressVisible.value = true
}

async function openCancel() {
  try {
    await ElMessageBox.confirm('取消后客诉将进入终态，不能继续更新进展。确认继续吗？', '取消客诉', {
      confirmButtonText: '继续填写取消说明', cancelButtonText: '返回', type: 'warning',
    })
  } catch { return }
  openProgress('CANCELLED')
}

function setProgressVisible(value: boolean) {
  progressVisible.value = value
  if (!value) {
    progressTarget.value = null
    void load()
  }
}

function showPreview(item: ComplaintAttachment) {
  previewAttachment.value = item
  previewVisible.value = true
}

function formatSize(value: number) {
  return value < 1024 * 1024 ? `${Math.ceil(value / 1024)} KB` : `${(value / 1024 / 1024).toFixed(1)} MB`
}

onMounted(async () => {
  const [complaintOptions] = await Promise.all([
    fetchComplaintOptions().catch(error => { errorMessage.value = complaintRequestMessage(error); return null }),
    load(),
  ])
  options.value = complaintOptions
  await Promise.all([complaintTypeSource.load().catch(() => []), severitySource.load().catch(() => [])])
  if (route.query.action === 'edit' && canEdit.value) editVisible.value = true
  if (route.query.action === 'progress' && canProcess.value) openProgress()
})
</script>

<template>
  <section class="complaint-detail" v-loading="loading">
    <el-alert v-if="errorMessage" :title="errorMessage" type="error" show-icon :closable="false" class="error"><template #default><el-button link type="primary" @click="load">重试</el-button></template></el-alert>
    <template v-else-if="complaint">
      <header class="detail-heading">
        <div><p class="eyebrow">{{ complaint.complaint_code }}</p><h1>{{ complaint.title }}</h1><p><span class="solid-tag" :class="`severity-${complaint.severity.item_code.toLowerCase()}`">{{ complaint.severity.display_name }}</span><span class="solid-tag status-tag">{{ complaint.status_label }}</span><strong :class="{ overdue: complaint.sla_status === 'OVERDUE' }">{{ slaText }}</strong></p></div>
        <div class="heading-actions"><el-button v-if="canProcess && !terminal" type="primary" :disabled="nextStatus === 'CLOSED' && !canClose" @click="openProgress()">{{ primaryActionText }}</el-button><el-dropdown v-if="canEdit || (canProcess && !terminal)" trigger="click"><el-button>更多 <el-icon><MoreFilled /></el-icon></el-button><template #dropdown><el-dropdown-menu><el-dropdown-item v-if="canEdit" @click="editVisible = true">编辑客诉 / 转交负责人</el-dropdown-item><el-dropdown-item v-if="canProcess && !terminal" @click="openProgress(complaint.status)">仅补充进展</el-dropdown-item><el-dropdown-item v-if="canProcess && !terminal" divided @click="openCancel">取消客诉</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
      </header>

      <el-alert v-if="conflictMessage" class="error" :title="conflictMessage" type="warning" :closable="false" show-icon><template #default><el-button link type="primary" @click="load">刷新到最新版本</el-button></template></el-alert>

      <section class="workflow-card">
        <div class="workflow-steps"><template v-for="(step, index) in workflowSteps" :key="step.value"><div :class="{ done: index < currentStepIndex, current: index === currentStepIndex }"><i>{{ index < currentStepIndex ? '✓' : index + 1 }}</i><span>{{ step.label }}</span></div><b v-if="index < workflowSteps.length - 1" :class="{ done: index < currentStepIndex }" /></template></div>
        <article><strong>当前阶段 · {{ complaint.status_label }}</strong><p>{{ complaint.progress_entries[0]?.progress_note || '等待补充最新处理说明。' }}</p><small>业务状态按顺序推进；SLA 状态独立计算，不会改变业务阶段。</small></article>
      </section>

      <main class="detail-layout">
        <div class="left-column">
          <section class="surface overview-card"><div class="section-title"><h2>客诉概览</h2><span>{{ complaint.complaint_type.display_name }}</span></div><dl><div><dt>客户</dt><dd>{{ complaint.customer.account_name }}</dd></div><div><dt>联系人</dt><dd>{{ complaint.contact?.display_name || '—' }}</dd></div><div><dt>关联订单</dt><dd>{{ complaint.source_order_reference || '—' }}</dd></div><div><dt>负责人</dt><dd>{{ complaint.owner.display_name }}</dd></div><div><dt>协同人</dt><dd>{{ complaint.collaborators.map(item => item.display_name).join('、') || '无' }}</dd></div><div><dt>首次响应</dt><dd>{{ complaintDate(complaint.first_responded_at) }}</dd></div><div><dt>目标完成</dt><dd>{{ complaintDate(complaint.target_completion_at) }}</dd></div><div><dt>最近更新</dt><dd>{{ complaintDate(complaint.updated_at) }}</dd></div></dl><p class="finance-note">CRM 仅记录客诉事实与处理结论，不执行退款、赔付或核销。</p></section>
          <section class="surface evidence-card"><div class="section-title"><h2>问题描述与证据</h2><span>{{ complaint.attachments.length }} 张图片</span></div><p class="issue-description">{{ complaint.issue_description }}</p><div v-if="complaint.attachments.length" class="image-grid"><button v-for="item in complaint.attachments" :key="item.id" @click="showPreview(item)"><span><Picture /></span><div><strong>{{ item.original_name }}</strong><small>{{ item.caption || '客诉图片' }} · {{ formatSize(item.size_bytes) }}</small></div><em>查看</em></button></div><div v-else class="empty">暂无图片证据</div></section>
          <section class="surface timeline-card"><div class="section-title"><h2>处理时间轴</h2><span>{{ complaint.progress_entries.length }} 条</span></div><div v-if="complaint.progress_entries.length" class="timeline"><article v-for="item in complaint.progress_entries" :key="item.id"><i /><time>{{ complaintDate(item.created_at) }}</time><div><strong>{{ item.progress_note }}</strong><small>{{ item.from_status_label }} → {{ item.to_status_label }}</small></div><span>{{ item.created_by?.display_name || '系统' }}</span></article></div><div v-else class="empty">暂无处理记录</div></section>
        </div>
        <aside>
          <section class="surface resolution-card"><div class="section-title"><h2>原因与处理方案</h2><span>当前结论</span></div><dl><div><dt>根本原因</dt><dd>{{ complaint.root_cause || '待确认' }}</dd></div><div><dt>责任归属</dt><dd>{{ complaint.responsibility || '待确认' }}</dd></div><div><dt>解决方案</dt><dd>{{ complaint.solution || '待制定' }}</dd></div><div><dt>客户反馈</dt><dd>{{ complaint.customer_feedback || '待反馈' }}</dd></div></dl></section>
          <section class="surface meta-card"><div class="section-title"><h2>记录信息</h2></div><dl><div><dt>创建人</dt><dd>{{ complaint.created_by?.display_name || '—' }}</dd></div><div><dt>最后更新人</dt><dd>{{ complaint.last_updated_by?.display_name || '—' }}</dd></div><div><dt>创建时间</dt><dd>{{ complaintDate(complaint.created_at) }}</dd></div><div><dt>原始客户</dt><dd>{{ complaint.original_customer.account_name }}</dd></div></dl></section>
        </aside>
      </main>
      <section v-if="complaint.original_customer.id !== complaint.customer.id" class="merge-note">客户已合并；原始客户 {{ complaint.original_customer.account_name }}（{{ complaint.original_customer.account_code }}）仍保留用于追溯。</section>

      <ComplaintEditDialog v-model="editVisible" :complaint="complaint" :etag="etag" :options="options" :complaint-types="complaintTypes" :severities="severities" @updated="acceptUpdate" />
      <ComplaintProgressDialog :model-value="progressVisible" :complaint="complaint" :etag="etag" :options="options" :can-close="canClose" :initial-target="progressTarget" @update:model-value="setProgressVisible" @updated="acceptUpdate" />
      <ComplaintImagePreview v-model="previewVisible" :attachment="previewAttachment" />
    </template>
  </section>
</template>

<style scoped lang="scss">
@use '@/styles/theme/detail' as detail;
@use '@/styles/crm/tokens' as token;
.complaint-detail { min-width: 0; min-height: 0; margin: 0; padding: 0; color: var(--erp-color-text-primary); background: transparent; font-family: token.$crm-font-body; font-size: 13px; line-height: 20px; }.back-link { height: 28px; padding: 0; color: var(--erp-color-brand); font-size: 14px; }.error { margin-bottom: 14px; }
.detail-heading, .heading-actions, .detail-heading > div > p:last-child, .section-title { display: flex; align-items: center; }.detail-heading { min-height: 0; justify-content: space-between; gap: 14px; flex-wrap: wrap; margin-bottom: 14px; }.eyebrow { margin: 0; color: var(--erp-color-brand); font-size: 12px; font-weight: 700; letter-spacing: 1px; }.detail-heading h1 { max-width: 1040px; overflow: hidden; margin: 4px 0 7px; font-family: var(--erp-font-body); font-size: 36px; font-weight: 700; line-height: 44px; text-overflow: ellipsis; white-space: normal; overflow-wrap: anywhere; }.detail-heading > div > p:last-child { gap: 9px; margin: 0; }.detail-heading p strong { color: var(--erp-color-text-regular); font-size: 13px; font-weight: 500; }.detail-heading p strong.overdue { color: var(--erp-color-danger); }.heading-actions { gap: 8px; flex-wrap: wrap; }.heading-actions :deep(.el-button) { height: 32px; margin: 0; border-radius: 8px; font-size: 13px; }.heading-actions :deep(.el-button--primary) { border-color: var(--erp-button-primary-border); background: var(--erp-button-primary-surface); }
.solid-tag { min-width: 66px; height: 28px; display: inline-flex; align-items: center; justify-content: center; padding: 0 9px; border-radius: 3px; color: var(--erp-tag-neutral-text); background: var(--erp-tag-info-background); font-size: 13px; }.severity-important, .severity-high { background: var(--erp-tag-warning-background); }.severity-serious, .severity-critical { background: var(--erp-tag-danger-background); }.status-tag { background: var(--erp-tag-neutral-background); }
.workflow-card { @include detail.surface; min-height: 0; display: grid; grid-template-columns: 1.35fr .65fr; align-items: center; margin: 0 0 14px; overflow: hidden; }.workflow-steps { display: flex; align-items: flex-start; padding: 16px; }.workflow-steps > div { width: 88px; flex: none; text-align: center; }.workflow-steps i { width: 30px; height: 30px; display: grid; place-items: center; margin: 0 auto; border: 1px solid var(--erp-color-border); border-radius: 50%; color: var(--erp-color-text-regular); background: var(--erp-color-subtle); font-size: 13px; font-style: normal; }.workflow-steps span { display: block; margin-top: 9px; color: var(--erp-color-text-regular); font-size: 13px; white-space: nowrap; }.workflow-steps > div.done i, .workflow-steps > div.current i { border-color: var(--erp-color-brand); color: var(--erp-color-text-inverse); background: var(--erp-color-brand); }.workflow-steps > div.current span { color: var(--erp-color-brand); font-weight: 600; }.workflow-steps b { height: 2px; flex: 1; margin-top: 14px; background: var(--erp-color-border); }.workflow-steps b.done { background: var(--erp-color-brand); }.workflow-card > article { min-height: 0; padding: 16px; border-left: 1px solid var(--erp-color-border); background: var(--erp-glass-inner-background); }.workflow-card article strong { color: var(--erp-color-brand); font-size: 15px; }.workflow-card article p { margin: 8px 0 5px; color: var(--erp-color-text-primary); font-size: 14px; line-height: 21px; }.workflow-card article small { color: var(--erp-color-text-regular); font-size: 12px; }
.detail-layout { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(400px, .55fr); gap: 14px; }.left-column, aside { display: grid; align-content: start; gap: 14px; min-width: 0; }.surface {
 @include detail.surface; overflow: hidden; }.section-title { height: auto; justify-content: space-between; padding: 12px 16px; border-bottom: 1px solid var(--erp-color-border); min-height: 48px; gap: 8px; flex-wrap: wrap; }.section-title h2 { margin: 0; font-family: var(--erp-font-body); font-size: 16px; font-weight: 600; line-height: 24px; }.section-title span { color: var(--erp-color-text-regular); font-size: 13px; }
.overview-card dl { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 14px; margin: 0; padding: 16px; }.overview-card dt, .resolution-card dt, .meta-card dt { color: var(--erp-color-text-regular); font-size: 12px; }.overview-card dd, .resolution-card dd, .meta-card dd { margin: 6px 0 0; color: var(--erp-color-text-primary); font-size: 13px; line-height: 21px; overflow-wrap: anywhere; }.finance-note { margin: 0 20px 20px; padding: 11px 14px; border-left: 3px solid var(--erp-color-warning-border); color: var(--erp-color-text-regular); background: var(--erp-color-subtle); font-size: 13px; }
.issue-description { min-height: 52px; margin: 0; padding: 16px; color: var(--erp-color-text-primary); font-size: 13px; line-height: 22px; white-space: pre-wrap; }.image-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 0 16px 16px; }.image-grid button { @include detail.inset; min-height: 64px; display: grid; grid-template-columns: 42px 1fr 42px; align-items: center; gap: 10px; padding: 8px 12px; color: var(--erp-color-text-primary); cursor: pointer; text-align: left; }.image-grid button > span { width: 38px; height: 38px; display: grid; place-items: center; color: var(--erp-color-brand); background: var(--erp-color-subtle); }.image-grid button strong, .image-grid button small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.image-grid button strong { font-size: 14px; }.image-grid button small { margin-top: 4px; color: var(--erp-color-text-regular); font-size: 11px; }.image-grid button em { color: var(--erp-color-brand); font-size: 13px; font-style: normal; }
.timeline { padding: 16px; }.timeline article { position: relative; min-height: 62px; display: grid; grid-template-columns: 14px 145px 1fr 90px; gap: 10px; }.timeline article:not(:last-child)::before { position: absolute; top: 15px; bottom: -5px; left: 5px; width: 1px; content: ''; background: var(--erp-color-border); }.timeline i { z-index: 1; width: 11px; height: 11px; margin-top: 4px; border-radius: 50%; background: var(--erp-color-brand); }.timeline time, .timeline small, .timeline > article > span { color: var(--erp-color-text-regular); font-size: 12px; }.timeline strong { font-size: 14px; }.timeline article div small { display: block; margin-top: 5px; }.timeline > article > span { text-align: right; }
.resolution-card dl, .meta-card dl { margin: 0; padding: 4px 16px 16px; }.resolution-card dl div { min-height: 74px; padding: 16px 0; border-bottom: 1px solid var(--erp-color-border); }.resolution-card dl div:last-child { border-bottom: 0; }.resolution-card dd { white-space: pre-wrap; }.meta-card dl { display: grid; grid-template-columns: 1fr 1fr; gap: 18px 14px; padding-top: 16px; }.empty { min-height: 88px; display: grid; place-items: center; color: var(--erp-color-text-secondary); font-size: 14px; }.merge-note { margin-top: 14px; padding: 12px 15px; border-left: 3px solid var(--erp-color-warning-border); color: var(--erp-color-warning); background: var(--erp-color-subtle); font-size: 13px; }
@media (max-width: 1300px) { .workflow-card, .detail-layout { grid-template-columns: 1fr; }.workflow-card > article { border-top: 1px solid var(--erp-table-border); border-left: 0; min-height: 0; padding: 16px; background: var(--erp-glass-inner-background); }.overview-card dl { grid-template-columns: repeat(4,minmax(0,1fr)); gap: 14px; padding: 16px; } }
@media (max-width:680px) { .workflow-steps { padding:14px 8px; } .workflow-steps > div { width:auto; flex:1; min-width:0; } .workflow-steps span { white-space:normal; } .overview-card dl, .image-grid { grid-template-columns:minmax(0,1fr); } .timeline article { grid-template-columns:14px minmax(0,1fr); } .timeline article > div, .timeline article > span { grid-column:2; text-align:left; } }
</style>
