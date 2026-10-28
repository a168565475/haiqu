<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { isAxiosError } from 'axios'
import { ElButton, ElOption, ElPagination, ElSelect, ElTag } from 'element-plus'
import AppWindowDialog from '@/components/common/AppWindowDialog.vue'
import { getNotificationSendRecords, notificationSendRecordsError } from '@/api/notifications'
import { useAuthStore } from '@/stores/auth'
import type { NotificationChannelStatus, NotificationRecordSource, NotificationSendRecord } from '@/types/notifications'

const props = defineProps<{ embedded?: boolean }>()
const auth = useAuthStore()
const sources = computed(() => {
  if (!auth.isAuthenticated || auth.waitingForRole) return []
  const notifications = auth.managementCan('access_control.manage_notifications')
  const wecom = auth.managementCan('access_control.manage_wecom')
  return [
    { value: 'BUSINESS' as const, label: '自动通知', allowed: notifications },
    { value: 'RULE_PREVIEW' as const, label: '规则试发', allowed: notifications && wecom && auth.user?.is_superuser === true },
    { value: 'MESSAGE_TEST' as const, label: '消息测试', allowed: wecom },
  ].filter(item => item.allowed)
})
const source = ref<NotificationRecordSource | null>(null)
const status = ref<NotificationChannelStatus | ''>('')
const rows = ref<NotificationSendRecord[]>([])
const count = ref<number | null>(null)
const page = ref(1)
const loading = ref(false)
const loadError = ref('')
const forbidden = ref(false)
const selected = ref<NotificationSendRecord>()
const detailVisible = ref(false)
const allowed = computed(() => sources.value.some(item => item.value === source.value))
const identity = computed(() => JSON.stringify([auth.isAuthenticated, auth.waitingForRole, auth.user?.id,
  auth.user?.username, auth.user?.is_superuser, auth.user?.employee, auth.user?.permissions, auth.user?.effective_access]))
const statusLabels: Record<NotificationChannelStatus, string> = {
  PENDING: '待发送', PROCESSING: '正在处理', ACCEPTED: '企业微信已受理', FAILED: '发送失败', UNCERTAIN: '结果未确认', SKIPPED: '已跳过',
}
const sourceLabels: Record<NotificationRecordSource, string> = { BUSINESS: '自动通知', RULE_PREVIEW: '规则试发', MESSAGE_TEST: '消息测试' }
const statusOptions = computed(() => (Object.keys(statusLabels) as NotificationChannelStatus[])
  .filter(value => source.value === 'BUSINESS' || !['PENDING', 'SKIPPED'].includes(value)))
let request: AbortController | undefined
let disposed = false

function clearRecords() {
  request?.abort(); request = undefined
  rows.value = []; count.value = null; loading.value = false; loadError.value = ''
  selected.value = undefined; detailVisible.value = false
}

async function loadRecords(nextPage = 1) {
  if (!source.value || !allowed.value || forbidden.value) return
  clearRecords()
  page.value = nextPage
  const controller = new AbortController()
  request = controller
  loading.value = true
  try {
    const result = await getNotificationSendRecords({ source: source.value, page: nextPage, page_size: 20,
      ...(status.value ? { status: status.value } : {}) }, controller.signal)
    if (disposed || request !== controller || !allowed.value) return
    rows.value = result.data; count.value = result.count; page.value = result.page
  } catch (error) {
    if (disposed || request !== controller || !allowed.value) return
    forbidden.value = isAxiosError(error) && [401, 403].includes(error.response?.status || 0)
    loadError.value = notificationSendRecordsError(error)
  } finally {
    if (request === controller) loading.value = false
  }
}

function formatTime(value: string | null, missing = '—') {
  if (!value) return missing
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone: 'Asia/Shanghai',
  }).format(date) : '时间未知'
}
function statusType(value: NotificationChannelStatus) {
  if (value === 'ACCEPTED') return 'success'
  if (value === 'FAILED') return 'danger'
  if (value === 'UNCERTAIN') return 'warning'
  return 'info'
}
function contentSummary(row: NotificationSendRecord) { return [row.title, row.body].filter(Boolean).join(' · ') || '未保存发送内容' }
function selectSource(value: NotificationRecordSource) {
  if (source.value === value) return
  status.value = ''; source.value = value
}
function openDetail(row: NotificationSendRecord) {
  if (!allowed.value || forbidden.value || loading.value) return
  selected.value = row; detailVisible.value = true
}

watch([source, status], ([nextSource], [previousSource]) => {
  if (nextSource !== previousSource) forbidden.value = false
  void loadRecords(1)
})
watch(identity, () => {
  clearRecords(); forbidden.value = false; page.value = 1
  const first = sources.value[0]?.value || null
  const changed = source.value !== first || status.value !== ''
  source.value = first; status.value = ''
  if (!changed && first) void loadRecords(1)
}, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { disposed = true; clearRecords() })
</script>

<template>
  <section class="notification-records-page erp-glass-list" aria-label="发送记录">
    <section class="erp-list-filter">
      <header v-if="!props.embedded" class="erp-list-heading"><h1>发送记录</h1></header>
      <div v-if="sources.length" class="records-toolbar">
        <div class="erp-list-tabs" role="group" aria-label="发送记录来源">
          <button v-for="item in sources" :key="item.value" type="button" :class="{ active: source === item.value }"
            :aria-pressed="source === item.value" :data-record-source="item.value" @click="selectSource(item.value)">{{ item.label }}</button>
        </div>
        <div class="erp-list-filters">
          <label for="send-record-status">发送结果<ElSelect id="send-record-status" v-model="status" :disabled="forbidden" placeholder="全部结果" aria-label="发送结果筛选">
            <ElOption value="" label="全部结果" /><ElOption v-for="value in statusOptions" :key="value" :value="value" :label="statusLabels[value]" />
          </ElSelect></label>
          <ElButton :disabled="loading || forbidden" @click="loadRecords(page)">刷新</ElButton>
        </div>
      </div>
      <p class="records-note">企业微信已受理不等于送达或已读。历史记录按已保存的内容快照展示，缺失内容无法还原。</p>
      <p v-if="source === 'RULE_PREVIEW'" class="records-note">规则试发仅显示当前账号的记录。</p>
    </section>
    <section class="erp-list-data" :aria-busy="loading">
      <p v-if="!sources.length" class="records-state">当前账号没有发送记录查看权限。</p>
      <p v-else-if="loading" class="records-state" role="status">正在读取发送记录…</p>
      <div v-else-if="loadError" class="records-state records-error" role="alert">
        <p>{{ loadError }}</p><ElButton v-if="!forbidden" @click="loadRecords(page)">重新加载</ElButton>
      </div>
      <template v-else>
        <div class="erp-list-table-frame">
          <div class="erp-list-table-scroll" role="region" aria-label="发送记录列表" tabindex="0">
            <table class="erp-list-native-table records-table">
              <colgroup><col style="width:130px"><col style="width:190px"><col style="width:340px"><col style="width:190px"><col style="width:170px"><col style="width:100px"></colgroup>
              <thead><tr><th scope="col">接收人</th><th scope="col">业务环节</th><th scope="col">发送内容</th><th scope="col">发送时间</th><th scope="col">发送结果</th><th scope="col">操作</th></tr></thead>
              <tbody>
                <tr v-for="row in rows" :key="row.id" :data-record-id="row.id">
                  <td><span class="cell-text" :title="row.recipient_name">{{ row.recipient_name || '接收人未知' }}</span></td>
                  <td><span class="cell-text" :title="row.event_name">{{ row.event_name || sourceLabels[row.source] }}</span></td>
                  <td><span class="cell-text" :title="contentSummary(row)">{{ contentSummary(row) }}</span></td>
                  <td><time :datetime="row.sent_at || undefined">{{ formatTime(row.sent_at, '未发送') }}</time></td>
                  <td><ElTag :type="statusType(row.status)">{{ statusLabels[row.status] }}</ElTag></td>
                  <td><ElButton link type="primary" :aria-label="`查看${row.recipient_name || '该接收人'}的发送全文`" @click="openDetail(row)">查看全文</ElButton></td>
                </tr>
                <tr v-if="!rows.length"><td class="empty" colspan="6">{{ count ? '此页暂无发送记录，请返回上一页。' : '暂无符合条件的发送记录。' }}</td></tr>
              </tbody>
            </table>
          </div>
        </div>
        <footer v-if="count !== null" class="records-pagination erp-list-footer">
          <span>共 {{ count }} 条</span><ElPagination :current-page="page" :page-size="20" :total="count" :pager-count="5"
            layout="prev, pager, next" @current-change="loadRecords" />
        </footer>
      </template>
    </section>
    <AppWindowDialog v-if="allowed && !forbidden" v-model="detailVisible" title="发送详情" :width="760" :min-width="280" :minimizable="false" destroy-on-close @closed="selected = undefined">
      <div v-if="selected" class="record-detail">
        <dl>
          <div><dt>接收人</dt><dd>{{ selected.recipient_name || '接收人未知' }}</dd></div>
          <div><dt>记录来源</dt><dd>{{ sourceLabels[selected.source] }}</dd></div>
          <div><dt>业务环节</dt><dd>{{ selected.event_name || sourceLabels[selected.source] }}</dd></div>
          <div><dt>发送时间</dt><dd>{{ formatTime(selected.sent_at, '未发送') }}</dd></div>
          <div><dt>发送结果</dt><dd>{{ statusLabels[selected.status] }}</dd></div>
          <div><dt>尝试次数</dt><dd>{{ selected.attempt_count }}</dd></div>
          <div><dt>记录时间</dt><dd>{{ formatTime(selected.created_at) }}</dd></div>
          <div><dt>处理完成时间</dt><dd>{{ formatTime(selected.finished_at) }}</dd></div>
          <div v-if="selected.error_code"><dt>失败／跳过原因</dt><dd>{{ selected.error_code }}</dd></div>
        </dl>
        <section class="record-content" aria-label="完整发送内容"><h2>{{ selected.title || '发送内容' }}</h2><p>{{ selected.body || '未保存发送正文。' }}</p></section>
        <p class="records-note">企业微信已受理不等于送达或已读。</p>
      </div>
      <template #footer><ElButton @click="detailVisible = false">关闭</ElButton></template>
    </AppWindowDialog>
  </section>
</template>

<style scoped lang="scss">
.notification-records-page { min-height: 320px; }
.records-toolbar { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 14px; }
.records-toolbar .el-select { width: 170px; }
.records-note { margin: 10px 0 0; color: var(--erp-color-text-secondary); font-size: 12px; line-height: 20px; }
.records-state { margin: 0; padding: 48px 16px; text-align: center; color: var(--erp-color-text-secondary); font-size: 13px; }
.records-error { color: var(--erp-color-danger); }
.records-error p { margin: 0 0 12px; }
.records-table { min-width: 1120px; }
.records-table th, .records-table td { border-right: 0; }
.records-table time { white-space: nowrap; }
.cell-text { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.records-pagination { display: flex; align-items: center; justify-content: space-between; flex: none; gap: 12px; min-height: 40px; font-size: 12px; color: var(--erp-color-text-secondary); }
.record-detail { color: var(--erp-color-text-primary); font: 13px/1.6 var(--erp-font-body); }
.record-detail dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 20px; margin: 0 0 20px; }
.record-detail dl > div { min-width: 0; }
.record-detail dt { margin-bottom: 3px; color: var(--erp-color-text-secondary); font-size: 12px; }
.record-detail dd { margin: 0; overflow-wrap: anywhere; }
.record-content { padding: 14px; border: 1px solid var(--erp-color-border); border-radius: var(--erp-radius-control); background: var(--erp-color-surface); }
.record-content h2 { margin: 0 0 10px; font-size: 15px; line-height: 24px; white-space: pre-wrap; overflow-wrap: anywhere; }
.record-content p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.erp-list-tabs button:focus-visible, .erp-list-table-scroll:focus-visible { outline: 2px solid var(--erp-color-focus); outline-offset: 2px; }
@media (max-width: 640px) { .record-detail dl { grid-template-columns: 1fr; }.records-toolbar .erp-list-filters { width: 100%; }.records-pagination { flex-wrap: wrap; } }
</style>
