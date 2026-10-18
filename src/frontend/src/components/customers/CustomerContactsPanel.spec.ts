import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElButton, ElInput } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createContact, fetchContact, updateContact } from '@/api/contacts'
import type { ContactDetail, ContactMethod } from '@/types/contact'
import CustomerContactsPanel from './CustomerContactsPanel.vue'

const permissions = vi.hoisted(() => new Set<string>())
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ hasPermission: (value: string) => permissions.has(value) }) }))
vi.mock('@/api/contacts', () => ({ createContact: vi.fn(), fetchContact: vi.fn(), updateContact: vi.fn() }))

function method(id: string, value: string, primary = false, type = 'EMAIL'): ContactMethod {
  return { id, method_type: type, display_value: value, masked_value: '***', is_primary: primary,
    is_preferred: false, verification_status: 'VERIFIED', archived_at: null } as ContactMethod
}
function contact(overrides: Partial<ContactDetail> = {}): ContactDetail {
  return { id: 'contact-1', display_name: '测试联系人', status: 'ACTIVE',
    customer: { id: 'customer-1' }, methods: [method('a', 'old@example.com', true)], ...overrides } as ContactDetail
}
let wrapper: VueWrapper
function setup(contacts = [contact()], props = {}) {
  wrapper = mount(CustomerContactsPanel, { props: { customerId: 'customer-1', contacts, ...props }, global: { plugins: [ElementPlus] } })
  return wrapper
}
function button(label: string) {
  const found = wrapper.findAllComponents(ElButton).find(item => item.text() === label)
  if (!found) throw new Error(`找不到按钮 ${label}`)
  return found
}
async function openEdit() { await button('编辑').trigger('click'); await flushPromises() }
async function fill(name: string, email?: string) {
  const inputs = wrapper.findAllComponents(ElInput)
  await inputs[0]!.setValue(name)
  if (email !== undefined) await inputs[1]!.setValue(email)
}

describe('客户概览联系人简表', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    permissions.clear()
    for (const permission of ['add_customercontact', 'change_customercontact', 'add_customercontactmethod', 'change_customercontactmethod', 'view_sensitive_customercontactmethod']) permissions.add(`customers.${permission}`)
    vi.mocked(fetchContact).mockResolvedValue({ data: contact(), etag: 'contact-v2' })
    vi.mocked(createContact).mockResolvedValue({ data: contact(), etag: 'contact-v3' })
    vi.mocked(updateContact).mockResolvedValue({ data: contact(), etag: 'contact-v3' })
  })
  afterEach(() => { wrapper?.unmount(); document.body.innerHTML = '' })

  it('展示所有联系人名称邮箱，无邮箱历史联系人仍保留，主联系人排前', () => {
    setup([contact({ id: 'one' }), contact({ id: 'two', display_name: '仅电话联系人', methods: [method('p', '123456', false, 'PHONE')] }), contact({ id: 'three' }), contact({ id: 'primary', display_name: '主要联系人', is_primary_contact: true })])
    expect(wrapper.findAll('.contact-row')).toHaveLength(4)
    expect(wrapper.find('.contact-row').text()).toContain('主要联系人')
    expect(wrapper.text()).toContain('仅电话联系人')
    expect(wrapper.text()).toContain('未填写邮箱')
    expect(wrapper.text()).not.toContain('123456')
    expect(wrapper.find('table').exists()).toBe(false)
  })

  it('失败显示重试，不伪装为空联系人；无权限不显示写入口', async () => {
    permissions.clear()
    setup([], { error: '联系人加载失败' })
    expect(wrapper.text()).not.toContain('暂无联系人')
    expect(wrapper.text()).not.toContain('新增')
    await button('重试').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('新增要求名称邮箱，修正验证错误后可以保存并独立通知刷新', async () => {
    setup([])
    await button('新增').trigger('click')
    await flushPromises()
    await fill('新联系人')
    await button('保存').trigger('click')
    expect(createContact).not.toHaveBeenCalled()
    await fill('新联系人', 'new@example.com')
    await button('保存').trigger('click')
    await flushPromises()
    expect(createContact).toHaveBeenCalledWith({ customer_id: 'customer-1', display_name: '新联系人', methods: [{ method_type: 'EMAIL', raw_value: 'new@example.com', is_primary: true, is_preferred: true }] })
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('按后端顺序编辑主要邮箱，只传名称及该EMAIL，不覆盖其他方法和资料', async () => {
    const data = contact({ methods: [method('z', 'other@example.com'), method('b', 'second-primary@example.com', true), method('a', 'first-primary@example.com', true), method('p', '123456', false, 'PHONE')] })
    vi.mocked(fetchContact).mockResolvedValue({ data, etag: 'etag-latest' })
    setup([data])
    await openEdit()
    expect(wrapper.findAllComponents(ElInput)[1]!.props('modelValue')).toBe('first-primary@example.com')
    await fill('新名称', 'changed@example.com')
    await button('保存').trigger('click')
    await flushPromises()
    expect(updateContact).toHaveBeenCalledWith('contact-1', { display_name: '新名称', methods: [{ method_type: 'EMAIL', raw_value: 'changed@example.com', is_primary: true, is_preferred: false, verification_status: 'UNVERIFIED' }] }, 'etag-latest')
  })

  it('历史无邮箱联系人可以只改名称，不要求补邮箱，不发送空methods', async () => {
    const data = contact({ methods: [method('p', '123456', false, 'PHONE')] })
    vi.mocked(fetchContact).mockResolvedValue({ data, etag: 'etag-latest' })
    setup([data]); await openEdit(); await fill('只修改名称')
    await button('保存').trigger('click'); await flushPromises()
    expect(updateContact).toHaveBeenCalledWith('contact-1', { display_name: '只修改名称' }, 'etag-latest')
  })

  it('无敏感信息权限时脱敏邮箱不填入表单，也不回写', async () => {
    permissions.delete('customers.view_sensitive_customercontactmethod')
    const data = contact({ methods: [method('a', 'o***@example.com', true)] })
    vi.mocked(fetchContact).mockResolvedValue({ data, etag: 'etag-latest' })
    setup([data]); await openEdit()
    const email = wrapper.findAllComponents(ElInput)[1]!
    expect(email.props('modelValue')).toBe('')
    expect(email.props('disabled')).toBe(true)
    await fill('新名称'); await button('保存').trigger('click'); await flushPromises()
    expect(updateContact).toHaveBeenCalledWith('contact-1', { display_name: '新名称' }, 'etag-latest')
  })

  it.each(['o***@example.com', ''])('即使有权限，接口只返回掩码或无明文邮箱 %s 也不回写', async value => {
    const data = contact({ methods: [method('a', value, true)] })
    vi.mocked(fetchContact).mockResolvedValue({ data, etag: 'etag-latest' })
    setup([data]); await openEdit()
    expect(wrapper.findAllComponents(ElInput)[1]!.props('modelValue')).toBe('')
    expect(wrapper.findAllComponents(ElInput)[1]!.props('disabled')).toBe(true)
    await fill('新名称'); await button('保存').trigger('click'); await flushPromises()
    expect(updateContact).toHaveBeenCalledWith('contact-1', { display_name: '新名称' }, 'etag-latest')
  })

  it('详情获取失败或缺失ETag不会误创建联系人', async () => {
    vi.mocked(fetchContact).mockRejectedValue(new Error('读取失败'))
    setup(); await openEdit()
    expect(button('保存').props('disabled')).toBe(true)
    expect(document.body.textContent).toContain('读取失败')
    expect(createContact).not.toHaveBeenCalled()
    await button('取消').trigger('click'); await flushPromises()
    vi.mocked(fetchContact).mockResolvedValue({ data: contact(), etag: null })
    await openEdit()
    expect(button('保存').props('disabled')).toBe(true)
    expect(updateContact).not.toHaveBeenCalled()
  })

  it('并发冲突保留输入和弹窗，不发成功事件', async () => {
    vi.mocked(updateContact).mockRejectedValue({ isAxiosError: true, response: { status: 412 } })
    setup(); await openEdit(); await fill('待保存名称')
    await button('保存').trigger('click'); await flushPromises()
    expect(wrapper.findAllComponents(ElInput)[0]!.props('modelValue')).toBe('待保存名称')
    expect(document.body.textContent).toContain('联系人已被其他人修改')
    expect(wrapper.emitted('changed')).toBeUndefined()
  })
})
