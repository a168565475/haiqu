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
@use '@/styles/crm/tokens' as token;
.complaint-detail { min-width: 0; min-height: calc(100vh - 112px); margin: 0; padding: 24px 30px 36px; color: #292624; background: token.$crm-color-page; font-family: token.$crm-font-body; }.back-link { height: 28px; padding: 0; color: #8f3b24; font-size: 14px; }.error { margin-bottom: 14px; }
.detail-heading, .heading-actions, .detail-heading > div > p:last-child, .section-title { display: flex; align-items: center; }.detail-heading { min-height: 106px; justify-content: space-between; gap: 20px; }.eyebrow { margin: 0; color: #a04b34; font-size: 12px; font-weight: 700; letter-spacing: 1px; }.detail-heading h1 { max-width: 1040px; overflow: hidden; margin: 4px 0 7px; font-family: token.$crm-font-display; font-size: 34px; font-weight: 600; line-height: 42px; text-overflow: ellipsis; white-space: nowrap; }.detail-heading > div > p:last-child { gap: 9px; margin: 0; }.detail-heading p strong { color: #716b65; font-size: 13px; font-weight: 500; }.detail-heading p strong.overdue { color: #b53333; }.heading-actions { gap: 10px; }.heading-actions :deep(.el-button) { height: 42px; margin: 0; border-radius: 4px; font-size: 16px; }.heading-actions :deep(.el-button--primary) { border-color: #c7441d; background: #c7441d; }
.solid-tag { min-width: 66px; height: 28px; display: inline-flex; align-items: center; justify-content: center; padding: 0 9px; border-radius: 3px; color: #faf9f5; background: #3898ec; font-size: 13px; }.severity-important, .severity-high { background: #b8781e; }.severity-serious, .severity-critical { background: #b53333; }.status-tag { background: #5e5d59; }
.workflow-card { min-height: 154px; display: grid; grid-template-columns: 1.35fr .65fr; align-items: center; margin: 8px 0 16px; border: 1px solid #ded9d1; border-radius: 5px; background: #fffefb; }.workflow-steps { display: flex; align-items: flex-start; padding: 0 34px; }.workflow-steps > div { width: 88px; flex: none; text-align: center; }.workflow-steps i { width: 30px; height: 30px; display: grid; place-items: center; margin: 0 auto; border: 1px solid #cfc8bf; border-radius: 50%; color: #817a73; background: #f1eee8; font-size: 13px; font-style: normal; }.workflow-steps span { display: block; margin-top: 9px; color: #817a73; font-size: 13px; white-space: nowrap; }.workflow-steps > div.done i, .workflow-steps > div.current i { border-color: #c7441d; color: #fff; background: #c7441d; }.workflow-steps > div.current span { color: #8f3b24; font-weight: 600; }.workflow-steps b { height: 2px; flex: 1; margin-top: 14px; background: #ddd7cf; }.workflow-steps b.done { background: #c7441d; }.workflow-card > article { min-height: 96px; padding: 18px 24px; border-left: 1px solid #e4dfd7; background: #f2eee7; }.workflow-card article strong { color: #8f3b24; font-size: 15px; }.workflow-card article p { margin: 8px 0 5px; color: #3f3a36; font-size: 14px; line-height: 21px; }.workflow-card article small { color: #857f78; font-size: 12px; }
.detail-layout { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(400px, .55fr); gap: 16px; }.left-column, aside { display: grid; align-content: start; gap: 16px; }.surface { border: 1px solid #ded9d1; border-radius: 5px; background: #fffefb; }.section-title { height: 54px; justify-content: space-between; padding: 0 20px; border-bottom: 1px solid #e5e0d8; }.section-title h2 { margin: 0; font-family: token.$crm-font-display; font-size: 20px; font-weight: 600; }.section-title span { color: #817b75; font-size: 13px; }
.overview-card dl { display: grid; grid-template-columns: repeat(4, 1fr); gap: 18px 16px; margin: 0; padding: 18px 20px; }.overview-card dt, .resolution-card dt, .meta-card dt { color: #817b75; font-size: 12px; }.overview-card dd, .resolution-card dd, .meta-card dd { margin: 6px 0 0; color: #332f2c; font-size: 14px; line-height: 21px; }.finance-note { margin: 0 20px 20px; padding: 11px 14px; border-left: 3px solid #b8781e; color: #675f58; background: #f0ece5; font-size: 13px; }
.issue-description { min-height: 52px; margin: 0; padding: 18px 20px; color: #4a4541; font-size: 15px; line-height: 25px; white-space: pre-wrap; }.image-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 0 20px 20px; }.image-grid button { min-height: 64px; display: grid; grid-template-columns: 42px 1fr 42px; align-items: center; gap: 10px; padding: 8px 12px; border: 1px solid #e1dcd4; color: #332f2c; background: #faf8f3; cursor: pointer; text-align: left; }.image-grid button > span { width: 38px; height: 38px; display: grid; place-items: center; color: #8f3b24; background: #ece5dc; }.image-grid button strong, .image-grid button small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.image-grid button strong { font-size: 14px; }.image-grid button small { margin-top: 4px; color: #817b75; font-size: 11px; }.image-grid button em { color: #8f3b24; font-size: 13px; font-style: normal; }
.timeline { padding: 18px 20px 22px; }.timeline article { position: relative; min-height: 62px; display: grid; grid-template-columns: 14px 145px 1fr 90px; gap: 10px; }.timeline article:not(:last-child)::before { position: absolute; top: 15px; bottom: -5px; left: 5px; width: 1px; content: ''; background: #d9d3cb; }.timeline i { z-index: 1; width: 11px; height: 11px; margin-top: 4px; border-radius: 50%; background: #c7441d; }.timeline time, .timeline small, .timeline > article > span { color: #847e77; font-size: 12px; }.timeline strong { font-size: 14px; }.timeline article div small { display: block; margin-top: 5px; }.timeline > article > span { text-align: right; }
.resolution-card dl, .meta-card dl { margin: 0; padding: 4px 20px 20px; }.resolution-card dl div { min-height: 74px; padding: 16px 0; border-bottom: 1px solid #e8e3dc; }.resolution-card dl div:last-child { border-bottom: 0; }.resolution-card dd { white-space: pre-wrap; }.meta-card dl { display: grid; grid-template-columns: 1fr 1fr; gap: 18px 14px; padding-top: 18px; }.empty { min-height: 88px; display: grid; place-items: center; color: #918b84; font-size: 14px; }.merge-note { margin-top: 14px; padding: 12px 15px; border-left: 3px solid #b8781e; color: #6b5c48; background: #eee7da; font-size: 13px; }
@media (max-width: 1300px) { .workflow-card, .detail-layout { grid-template-columns: 1fr; }.workflow-card > article { border-top: 1px solid #e4dfd7; border-left: 0; }.overview-card dl { grid-template-columns: 1fr 1fr; } }
</style>
