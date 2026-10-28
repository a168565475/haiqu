import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ElOption, ElPagination, ElSelect } from 'element-plus'
import { AxiosError } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import type { NotificationSendRecord, NotificationSendRecordsResponse } from '@/types/notifications'
import NotificationDeliveryRecordsView from './NotificationDeliveryRecordsView.vue'

const api = vi.hoisted(() => ({ getNotificationSendRecords: vi.fn() }))
vi.mock('@/api/notifications', async original => ({ ...await original<object>(), ...api }))
const dialog = defineComponent({ props: ['modelValue'], template: '<section v-if="modelValue" role="dialog"><slot /><slot name="footer" /></section>' })
const row: NotificationSendRecord = { id: 'record-1', source: 'BUSINESS', recipient_name: '接收员工', event_code: 'BOM_CONFIRMED',
  event_name: 'BOM确认', title: 'BOM通知', body: '第一行内容\n第二行完整内容<script>非HTML</script>', status: 'ACCEPTED', error_code: '', attempt_count: 1,
  created_at: '2026-10-28T01:00:00Z', sent_at: '2026-10-28T01:00:01Z', finished_at: '2026-10-28T01:00:02Z' }
const wrappers: ReturnType<typeof mount>[] = []
function result(rows = [row], page = 1, count = rows.length): NotificationSendRecordsResponse { return { data: rows, count, page, page_size: 20 } }
function grant(permissions: string[], superuser = false) {
  const auth = useAuthStore()
  auth.user = { ...auth.user!, username: 'manager', is_superuser: superuser,
    effective_access: { active: true, is_superuser: superuser, roles: [], legacy_sources: [], version: 'test',
      actions: Object.fromEntries(permissions.map(code => [code, { scopes: ['MODULE'], sources: [{ type: 'ROLE', scope: 'MODULE' }] }])) } }
}
async function render() {
  const wrapper = mount(NotificationDeliveryRecordsView, { props: { embedded: true }, global: { stubs: { AppWindowDialog: dialog } } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}
function sources(wrapper: ReturnType<typeof mount>) { return wrapper.findAll('[data-record-source]').map(item => item.attributes('data-record-source')) }
function button(wrapper: ReturnType<typeof mount>, text: string) { return wrapper.findAll('button').find(item => item.text() === text)! }
beforeEach(() => {
  vi.resetAllMocks(); setActivePinia(createPinia())
  useAuthStore().applyAuthResponse({ authenticated: true, user: { id: 1, username: 'admin', display_name: '管理员', is_superuser: true,
    employee: { id: 'admin', employee_code: 'ADMIN', display_name: '管理员', status: 'ACTIVE' }, permissions: [], data_scope: 'ALL' } })
  api.getNotificationSendRecords.mockResolvedValue(result())
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = ''; vi.restoreAllMocks() })

describe('发送记录页面（测试替身）', () => {
  it('默认读取自动通知，准确展示环节、受理状态和上海时间，详情保留全文但不渲染HTML', async () => {
    const wrapper = await render()
    expect(sources(wrapper)).toEqual(['BUSINESS', 'RULE_PREVIEW', 'MESSAGE_TEST'])
    expect(api.getNotificationSendRecords).toHaveBeenCalledExactlyOnceWith({ source: 'BUSINESS', page: 1, page_size: 20 }, expect.any(AbortSignal))
    expect(wrapper.get('table').text()).toContain('BOM确认')
    expect(wrapper.get('table').text()).toContain('企业微信已受理')
    expect(wrapper.get('time').text()).toContain('09:00:01')
    expect(wrapper.text()).toContain('不等于送达或已读')
    await button(wrapper, '查看全文').trigger('click')
    expect(wrapper.get('[role="dialog"] .record-content p').text()).toBe(row.body)
    expect(wrapper.find('script').exists()).toBe(false)
  })

  it.each([
    [[], false, []],
    [['access_control.manage_notifications'], false, ['BUSINESS']],
    [['access_control.manage_wecom'], false, ['MESSAGE_TEST']],
    [['access_control.manage_notifications', 'access_control.manage_wecom'], false, ['BUSINESS', 'MESSAGE_TEST']],
    [['access_control.manage_notifications', 'access_control.manage_wecom'], true, ['BUSINESS', 'RULE_PREVIEW', 'MESSAGE_TEST']],
  ] as const)('权限 %j 超管 %s 仅开放对应来源', async (permissions, superuser, expected) => {
    grant([...permissions], superuser)
    api.getNotificationSendRecords.mockResolvedValue(result([]))
    const wrapper = await render()
    expect(sources(wrapper)).toEqual(expected)
    if (expected.length) expect(api.getNotificationSendRecords.mock.calls[0]![0].source).toBe(expected[0])
    else { expect(api.getNotificationSendRecords).not.toHaveBeenCalled(); expect(wrapper.text()).toContain('没有发送记录查看权限') }
  })

  it('筛选和分页调用接口，切换来源回到第一页并清空不适用状态', async () => {
    api.getNotificationSendRecords.mockResolvedValue(result([row], 1, 41))
    const wrapper = await render()
    wrapper.getComponent(ElSelect).vm.$emit('update:modelValue', 'PENDING'); await flushPromises()
    expect(api.getNotificationSendRecords.mock.lastCall![0]).toMatchObject({ status: 'PENDING', page: 1 })
    wrapper.getComponent(ElPagination).vm.$emit('current-change', 2); await flushPromises()
    expect(api.getNotificationSendRecords.mock.lastCall![0]).toMatchObject({ status: 'PENDING', page: 2 })
    api.getNotificationSendRecords.mockResolvedValue(result([]))
    await wrapper.get('[data-record-source="RULE_PREVIEW"]').trigger('click'); await flushPromises()
    expect(api.getNotificationSendRecords.mock.lastCall![0]).toEqual({ source: 'RULE_PREVIEW', page: 1, page_size: 20 })
    expect(wrapper.getComponent(ElSelect).findAllComponents(ElOption).map(option => option.props('value'))).not.toContain('PENDING')
    expect(wrapper.getComponent(ElSelect).findAllComponents(ElOption).map(option => option.props('value'))).not.toContain('SKIPPED')
    expect(wrapper.text()).toContain('仅显示当前账号')
  })

  it('未发送不借用创建时间，历史缺正文说明不可还原', async () => {
    api.getNotificationSendRecords.mockResolvedValue(result([{ ...row, body: '', title: '', sent_at: null, status: 'PENDING' }]))
    const wrapper = await render()
    expect(wrapper.get('time').text()).toBe('未发送')
    expect(wrapper.get('table').text()).toContain('未保存发送内容')
    await button(wrapper, '查看全文').trigger('click')
    expect(wrapper.get('[role="dialog"]').text()).toContain('未保存发送正文')
  })

  it('请求失败显示错误和重试，不伪造零条或正常通道', async () => {
    api.getNotificationSendRecords.mockRejectedValueOnce(new Error('offline'))
    const wrapper = await render()
    expect(wrapper.get('[role="alert"]').text()).toContain('加载失败')
    expect(wrapper.text()).not.toContain('共 0 条')
    expect(wrapper.find('table').exists()).toBe(false)
    api.getNotificationSendRecords.mockResolvedValueOnce(result([]))
    await button(wrapper, '重新加载').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('暂无符合条件的发送记录')
    expect(wrapper.text()).not.toContain('发送正常')
  })

  it('撤销权限立即清空列表和详情，旧请求返回也不能恢复敏感内容', async () => {
    const wrapper = await render()
    await button(wrapper, '查看全文').trigger('click')
    let finish!: (value: NotificationSendRecordsResponse) => void
    api.getNotificationSendRecords.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await button(wrapper, '刷新').trigger('click')
    const signal = api.getNotificationSendRecords.mock.lastCall![1] as AbortSignal
    grant([]); await flushPromises()
    expect(signal.aborted).toBe(true)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain(row.body)
    finish(result()); await flushPromises()
    expect(wrapper.text()).not.toContain(row.recipient_name)
    expect(wrapper.text()).toContain('没有发送记录查看权限')
  })

  it('来源切换取消旧请求，旧来源晚返回不能覆盖当前结果', async () => {
    let finish!: (value: NotificationSendRecordsResponse) => void
    api.getNotificationSendRecords.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    const wrapper = await render()
    expect(wrapper.text()).toContain('正在读取发送记录')
    const signal = api.getNotificationSendRecords.mock.calls[0]![1] as AbortSignal
    api.getNotificationSendRecords.mockResolvedValueOnce(result([{ ...row, id: 'test', source: 'MESSAGE_TEST', recipient_name: '当前消息测试接收人' }]))
    await wrapper.get('[data-record-source="MESSAGE_TEST"]').trigger('click'); await flushPromises()
    expect(signal.aborted).toBe(true)
    finish(result()); await flushPromises()
    expect(wrapper.get('table').text()).toContain('当前消息测试接收人')
    expect(wrapper.get('table').text()).not.toContain('接收员工')
  })

  it('服务端403清空旧内容并停止当前来源重试，仍能切到有权限的其他来源', async () => {
    const wrapper = await render()
    api.getNotificationSendRecords.mockRejectedValueOnce(new AxiosError('forbidden', undefined, undefined, undefined,
      { status: 403, data: {}, headers: {}, config: {} as never, statusText: 'Forbidden' }))
    await button(wrapper, '刷新').trigger('click'); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('无权查看该来源')
    expect(wrapper.find('table').exists()).toBe(false)
    expect(button(wrapper, '刷新').attributes('disabled')).toBeDefined()
    api.getNotificationSendRecords.mockResolvedValueOnce(result([]))
    await wrapper.get('[data-record-source="MESSAGE_TEST"]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('暂无符合条件的发送记录')
  })
})
