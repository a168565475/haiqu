<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Bell } from '@element-plus/icons-vue'
import { getNotificationInbox, notificationInboxError } from '@/api/notifications'
import { useNotificationsStore } from '@/stores/notifications'
import type { NotificationItem } from '@/types/notifications'

const notifications = useNotificationsStore(), router = useRouter()
const messages = ref<NotificationItem[]>([]), count = ref<number | null>(null)
const page = ref(1), expanded = ref(false), refresh = ref(0), loading = ref(false), error = ref('')
watch([page, refresh], ([number], _, cleanup) => {
  const request = new AbortController()
  cleanup(() => request.abort())
  error.value = ''
  loading.value = true
  getNotificationInbox(number, request.signal, true).then(result => {
    if (request.signal.aborted) return
    if (number > 1 && !result.data.length) { page.value = 1; return }
    messages.value = result.data; count.value = result.count
  }).catch(cause => {
    if (request.signal.aborted) return
    error.value = notificationInboxError(cause, '未读消息加载失败。')
    messages.value = []; count.value = null
  }).finally(() => { if (!request.signal.aborted) loading.value = false })
}, { immediate: true })
watch(() => notifications.unread, (n, old) => { if (n !== null && old !== null) refresh.value++ })
async function open(item: NotificationItem) {
  // 复用页头的收件人详情入口，展示正文并重新核实业务单据权限。
  const query = router.currentRoute.value.query
  if (query.notification === item.id) await router.replace({ query: { ...query, notification: undefined } })
  await router.replace({ query: { ...query, notification: item.id } })
}
const time = (date: string) => new Intl.DateTimeFormat('zh-CN', {
  month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai',
}).format(new Date(date))
</script>

<template>
  <section class="glass sidepanel">
    <header><h2><Bell />未读消息</h2><span class="badge">{{ count ?? '—' }}</span></header>
    <p v-if="error" role="alert">{{ error }} <button @click="refresh++">重试</button></p>
    <p v-else-if="loading && !messages.length" role="status">正在加载…</p>
    <p v-else-if="!messages.length">暂无未读消息</p>
    <template v-else>
      <button v-for="m in (expanded ? messages : messages.slice(0, 2))" :key="m.id" class="msgrow" @click="open(m)"><i aria-hidden="true" /><span>{{ m.title }}</span><time :datetime="m.created_at">{{ time(m.created_at) }}</time></button>
      <button v-if="(count ?? 0) > 2" class="more" :aria-expanded="expanded" @click="expanded = !expanded; page = 1">{{ expanded ? '收起' : '查看全部未读' }}</button>
      <ElPagination v-if="expanded && (count ?? 0) > 10" v-model:current-page="page" small :total="count ?? 0" :page-size="10" layout="prev, pager, next" />
    </template>
  </section>
</template>

<style scoped>
header,.msgrow { display:flex; gap:8px; align-items:center; justify-content:space-between; }
.badge { padding:2px 7px; border-radius:5px; background:var(--erp-color-subtle); color:var(--erp-color-brand); font-size:12px; }
.msgrow,.more,p button { border:0; background:none; color:inherit; font:inherit; cursor:pointer; }.msgrow { width:100%; text-align:left; justify-content:flex-start; padding:10px 0; align-items:baseline; font-size:13px; }.msgrow+.msgrow { border-top:1px solid var(--erp-color-border-subtle); }.msgrow i { width:6px; height:6px; border-radius:50%; background:#278299; flex:none; }.msgrow time { flex:none; margin-left:auto; font-size:11px; color:var(--erp-color-text-muted); }.msgrow span { overflow-wrap:anywhere; }
.more,p button { color:var(--erp-color-brand); font-size:12px; padding:4px 0; }.msgrow:hover { color:var(--erp-color-brand); }p { font-size:12px; color:var(--erp-color-text-secondary); }
</style>
