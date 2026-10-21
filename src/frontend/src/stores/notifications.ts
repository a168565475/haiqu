import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { isAxiosError } from 'axios'
import { useAuthStore } from './auth'
import { getNotificationInbox, getNotificationTarget, getNotificationUnreadCount, markNotificationRead, notificationInboxError } from '@/api/notifications'
import type { NotificationItem } from '@/types/notifications'
import { notificationRoute } from '@/utils/notificationTarget'

export const useNotificationsStore = defineStore('notifications', () => {
  const auth = useAuthStore()
  const items = ref<NotificationItem[]>([])
  const unread = ref<number | null>(null)
  const count = ref(0)
  const page = ref(1)
  const pageSize = ref(10)
  const loading = ref(false)
  const countLoading = ref(false)
  const error = ref('')
  const countError = ref('')
  const actionError = ref('')
  const actionId = ref('')
  const opened = ref(false)
  const arrival = ref(0)
  const running = ref(false)
  const blocked = ref(false)
  let epoch = 0
  let controller = new AbortController()
  let timer: ReturnType<typeof setTimeout> | undefined
  const identity = computed(() => auth.user && !auth.waitingForRole
    ? JSON.stringify([auth.user.id, auth.user.employee?.id, auth.user.employee?.status, auth.user.permissions, auth.user.effective_access]) : '')

  function clear() {
    epoch++
    controller.abort()
    controller = new AbortController()
    clearTimeout(timer)
    timer = undefined
    items.value = []
    unread.value = null
    count.value = 0
    page.value = 1
    loading.value = countLoading.value = false
    error.value = countError.value = actionError.value = actionId.value = ''
    opened.value = false
    arrival.value = 0
    blocked.value = false
  }

  function deny(errorValue: unknown) {
    if (!isAxiosError(errorValue) || ![401, 403].includes(errorValue.response?.status || 0)) return false
    const message = notificationInboxError(errorValue, '当前无法访问消息。')
    clear()
    blocked.value = true
    error.value = countError.value = message
    return true
  }

  async function refreshUnread() {
    if (!identity.value || blocked.value || countLoading.value) return
    const current = epoch
    countLoading.value = true
    try {
      const next = await getNotificationUnreadCount(controller.signal)
      if (current !== epoch) return
      if (unread.value !== null && next > unread.value) arrival.value++
      unread.value = next
      countError.value = ''
    } catch (cause) {
      if (current !== epoch || deny(cause)) return
      countError.value = notificationInboxError(cause, '未读数更新失败，请重试；显示的数量可能已过期。')
    } finally { if (current === epoch) countLoading.value = false }
  }

  async function loadPage(next = page.value) {
    if (!identity.value || blocked.value || loading.value || actionId.value) return
    const current = epoch
    loading.value = true
    error.value = ''
    try {
      const result = await getNotificationInbox(next, controller.signal)
      if (current !== epoch) return
      items.value = result.data
      count.value = result.count
      page.value = result.page
      pageSize.value = result.page_size
    } catch (cause) {
      if (current !== epoch || deny(cause)) return
      error.value = notificationInboxError(cause, '消息加载失败，请重试。')
    } finally { if (current === epoch) loading.value = false }
  }

  async function poll() {
    const current = epoch
    await refreshUnread()
    if (current !== epoch) return
    if (opened.value) await loadPage()
    if (current === epoch && running.value && identity.value && !blocked.value) timer = setTimeout(() => { void poll() }, 30_000)
  }

  function start() {
    if (running.value) return
    running.value = true
    if (identity.value) void poll()
  }
  function stop() { running.value = false; clear() }
  async function open() {
    opened.value = true
    await Promise.all([loadPage(1), refreshUnread()])
  }
  function close() { opened.value = false }
  async function retry() {
    if (blocked.value) return
    await Promise.all([loadPage(), refreshUnread()])
  }

  async function readAndResolve(item: NotificationItem) {
    if (!identity.value || blocked.value || actionId.value) return null
    const current = epoch
    actionId.value = item.id
    actionError.value = ''
    try {
      const updated = await markNotificationRead(item.id, controller.signal)
      if (current !== epoch) return null
      items.value = items.value.map(row => row.id === item.id ? updated : row)
      // 已读成功后只刷新服务端计数；不依赖旧页面本地减一。
      await refreshUnread()
      if (current !== epoch) return null
      // 删除知悉无业务目标；正文来自本次服务端权限复查，不请求已删除报工的详情。
      if (updated.event_code === 'WORK_REPORT_DELETED' && updated.target === null && !updated.target_accessible) {
        actionId.value = ''
        return null
      }
    } catch (cause) {
      if (current === epoch && !deny(cause)) actionError.value = notificationInboxError(cause, '标记已读失败，尚未跳转，请重试。')
      if (current === epoch) actionId.value = ''
      return null
    }
    try {
      if (current !== epoch) return null
      const target = await getNotificationTarget(item.id, controller.signal)
      if (current !== epoch) return null
      return notificationRoute(item.event_code, target)
    } catch (cause) {
      if (current === epoch && !deny(cause)) {
        actionError.value = notificationInboxError(cause, '消息已读，但业务跳转暂不可用，请稍后重试。')
        // 撤权/对象删除后清掉当前正文；不以取消状态推断不可访问。
        if (isAxiosError(cause) && cause.response?.status === 404) {
          items.value = items.value.map(row => row.id === item.id ? { ...row, title: '通知内容不可访问', body: '该业务已删除或当前无权查看。', target: null, target_accessible: false } : row)
        }
      }
      return null
    } finally { if (current === epoch) actionId.value = '' }
  }

  watch(identity, () => { clear(); if (running.value && identity.value) void poll() }, { flush: 'sync' })
  return { items, unread, count, page, pageSize, loading, countLoading, error, countError, actionError, actionId, opened, arrival, blocked,
    start, stop, open, close, retry, loadPage, refreshUnread, readAndResolve }
})
