import { mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import { usePageTabsStore } from '@/stores/pageTabs'
import type { AuthResponse } from '@/types/auth'
import { usePageTabsIdentitySync } from './usePageTabsIdentitySync'

const mounted: VueWrapper[] = []
const component = defineComponent({ template: '<div />' })
const Harness = defineComponent({ setup() { usePageTabsIdentitySync(); return () => null } })
function identity(id = 1, version = 'flow-private-v1'): AuthResponse {
  return { authenticated: true, user: { id, username: `user${id}`, display_name: '测试用户',
    is_superuser: false, employee: null, permissions: ['b', 'a'], data_scope: 'ALL' },
  account_switch: { active: true, can_return: true, identity_version: version } }
}
async function setup() {
  const pinia = createPinia(); setActivePinia(pinia)
  const auth = useAuthStore(); auth.applyAuthResponse(identity())
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', name: 'home', component, meta: { layout: 'erp' } },
    { path: '/customers/:customerId', name: 'customer-detail', component, meta: { layout: 'erp' } },
  ] })
  await router.push('/customers/old?source=old'); await router.isReady()
  mounted.push(mount(Harness, { global: { plugins: [pinia, router] } }))
  return { auth, tabs: usePageTabsStore(), router }
}
beforeEach(() => { sessionStorage.clear(); localStorage.clear() })
afterEach(() => { mounted.splice(0).forEach(wrapper => wrapper.unmount()); sessionStorage.clear(); localStorage.clear() })

describe('页签身份边界（jsdom 单元测试，无真实浏览器存储操作）', () => {
  it('初始挂载可记录现有路由，普通/me不清页签', async () => {
    const { auth, tabs } = await setup()
    expect(tabs.tabs.map(tab => tab.fullPath)).toEqual(['/', '/customers/old?source=old'])
    const same = identity(); same.user!.permissions.reverse()
    auth.applyAuthResponse(same); await nextTick()
    expect(tabs.tabs.map(tab => tab.fullPath)).toEqual(['/', '/customers/old?source=old'])
  })
  it.each([1, 2])('目标账号%s身份边界清旧页签，不能把旧URL重新记入；不冒充已做安全导航', async userId => {
    const { auth, tabs, router } = await setup()
    auth.applyAuthResponse(identity(userId, 'flow-private-v2')); await nextTick()
    expect(tabs.accountId).toBe(String(userId)); expect(tabs.tabs.map(tab => tab.fullPath)).toEqual(['/'])
    // 本单元没有自动导航；下一UI单元必须先处理未保存确认再进入安全落点。
    expect(router.currentRoute.value.fullPath).toBe('/customers/old?source=old')
    await router.push('/customers/new'); await nextTick()
    expect(tabs.tabs.map(tab => tab.fullPath)).toEqual(['/', '/customers/new'])
  })
  it('转换期间路由变化不写入页签；匿名刷新清旧账号', async () => {
    const { auth, tabs, router } = await setup()
    auth.identityTransitionPending = true
    await router.push('/customers/transition'); await nextTick()
    expect(tabs.tabs.some(tab => tab.fullPath.includes('transition'))).toBe(false)
    auth.applyAuthResponse({ authenticated: false, user: null }); await nextTick()
    expect(tabs.accountId).toBe(''); expect(tabs.tabs).toEqual([])
  })
  it('身份版本不落盘；历史草稿、幂等记录和用户偏好不被批量删除', async () => {
    const { auth, tabs, router } = await setup()
    const localKeys = ['material-receiving-draft:v2:purchase-order-test', 'material-quality-draft:v2:batch-test', 'haiqu:theme']
    const sessionKeys = ['assembly-receipt:plan-test', 'internal-receipt-pending:plan-test:category', 'manual-material-inbound-request-id']
    for (const key of localKeys) localStorage.setItem(key, 'original-payload-or-idempotency-uuid')
    for (const key of sessionKeys) sessionStorage.setItem(key, 'original-payload-or-idempotency-uuid')
    auth.applyAuthResponse(identity(1, 'flow-private-v2')); await nextTick()
    await router.push('/customers/new'); await nextTick(); tabs.persist()
    expect(sessionStorage.getItem('haiqu:page-tabs:v1:1')).not.toContain('flow-private')
    for (const key of localKeys) expect(localStorage.getItem(key)).toBe('original-payload-or-idempotency-uuid')
    for (const key of sessionKeys) expect(sessionStorage.getItem(key)).toBe('original-payload-or-idempotency-uuid')
  })
})
