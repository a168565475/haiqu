import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ReferenceDataSettingsView from './ReferenceDataSettingsView.vue'

const fixtures = vi.hoisted(() => {
  const granted = new Set<string>()
  const dictionaryTypes = [
    {
      id: 'type-customer-level', code: 'CUSTOMER_LEVEL', chinese_name: '客户等级', english_name: 'Customer level',
      group_code: 'CUSTOMER', status: 'ACTIVE', sort_order: 10, description: '', item_count: 4,
      active_item_count: 4, reference_count: 12, created_at: '2026-08-01T00:00:00Z',
      updated_at: '2026-08-26T00:00:00Z', archived_at: null,
    },
    {
      id: 'type-inquiry-source', code: 'INQUIRY_SOURCE', chinese_name: '询盘来源', english_name: 'Inquiry source',
      group_code: 'INQUIRY', status: 'ACTIVE', sort_order: 20, description: '', item_count: 8,
      active_item_count: 8, reference_count: 6, created_at: '2026-08-01T00:00:00Z',
      updated_at: '2026-08-26T00:00:00Z', archived_at: null,
    },
  ]
  const parameters = [
    {
      id: 'parameter-language', code: 'DEFAULT_LANGUAGE', chinese_name: '默认语言', english_name: 'Default language',
      group_code: 'GENERAL', value_type: 'STRING', default_value: 'zh-CN', draft_value: 'zh-CN',
      validation_rules: {}, status: 'ACTIVE', sort_order: 10, description: '', updated_at: '2026-08-26T00:00:00Z',
    },
  ]
  const release = {
    id: 'release-1', version: 3, status: 'PUBLISHED', notes: '', published_at: '2026-08-26T00:00:00Z',
    published_by: null, failure_message: '', created_at: '2026-08-26T00:00:00Z', updated_at: '2026-08-26T00:00:00Z',
  }
  return { granted, dictionaryTypes, parameters, release }
})

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    user: { is_superuser: false },
    hasPermission: (permission: string) => fixtures.granted.has(permission),
  }),
}))

vi.mock('@/api/referenceData', () => ({
  fetchReferenceDataSummary: vi.fn().mockResolvedValue({
    active_dictionary_items: 67, active_system_parameters: 6, pending_changes: 2, config_version: 3,
  }),
  fetchDictionaryTypes: vi.fn().mockResolvedValue({ data: fixtures.dictionaryTypes, meta: {} }),
  fetchDictionaryType: vi.fn(),
  updateDictionaryType: vi.fn(),
  fetchDictionaryItems: vi.fn().mockResolvedValue({ data: [], meta: {} }),
  fetchDictionaryItem: vi.fn(),
  createDictionaryItem: vi.fn(),
  updateDictionaryItem: vi.fn(),
  changeDictionaryItemStatus: vi.fn(),
  archiveDictionaryItem: vi.fn(),
  fetchSystemParameters: vi.fn().mockResolvedValue({ data: fixtures.parameters, meta: {} }),
  fetchSystemParameter: vi.fn(),
  updateSystemParameter: vi.fn(),
  fetchConfigReleases: vi.fn().mockResolvedValue({ data: [fixtures.release], meta: {} }),
  fetchConfigRelease: vi.fn(),
  publishReferenceData: vi.fn(),
}))

describe('ReferenceDataSettingsView', () => {
  beforeEach(() => {
    fixtures.granted.clear()
    fixtures.granted.add('reference_data.view_dictionarytype')
    fixtures.granted.add('reference_data.view_referencedictionary')
    fixtures.granted.add('reference_data.view_systemparameterdefinition')
    fixtures.granted.add('reference_data.view_configrelease')
  })

  it('展示真实汇总、稳定大写编码和当前分类数量', async () => {
    const wrapper = mount(ReferenceDataSettingsView, { global: { plugins: [createPinia(), ElementPlus] } })
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain('启用字典项')
    expect(wrapper.text()).toContain('67')
    expect(wrapper.text()).toContain('待发布变更')
    expect(wrapper.text()).toContain('CUSTOMER_LEVEL')
    expect(wrapper.text()).toContain('客户等级')
    expect(wrapper.text()).toContain('默认语言')
    expect(wrapper.text()).toContain('当前版本 v3')
    expect(wrapper.text()).not.toContain('customer_level')
  })

  it('没有任一配置查看权限时显示独立无权限状态且不请求数据', async () => {
    fixtures.granted.clear()
    const { fetchDictionaryTypes } = await import('@/api/referenceData')
    vi.mocked(fetchDictionaryTypes).mockClear()

    const wrapper = mount(ReferenceDataSettingsView, { global: { plugins: [createPinia(), ElementPlus] } })
    await flushPromises()

    expect(wrapper.text()).toContain('无配置权限')
    expect(wrapper.text()).toContain('联系管理员')
    expect(fetchDictionaryTypes).not.toHaveBeenCalled()
  })

  it('拥有任一生产资料查看权限时显示无下划线的生产维护入口', async () => {
    fixtures.granted.add('reference_data.view_productcolor')
    const wrapper = mount(ReferenceDataSettingsView, { global: { plugins: [createPinia(), ElementPlus] } })
    await flushPromises()

    const link = wrapper.find('a[href="/settings/production-data"]')
    expect(link.exists()).toBe(true)
    expect(link.text()).toContain('生产维护')
    expect(link.classes()).toContain('page-heading__link')
  })

  it('字典行操作统一收进不带三点图标的更多菜单', async () => {
    fixtures.granted.add('reference_data.change_dictionarytype')
    const wrapper = mount(ReferenceDataSettingsView, {
      attachTo: document.body,
      global: { plugins: [createPinia(), ElementPlus] },
    })
    await flushPromises()
    await flushPromises()

    const moreButton = wrapper.get('[data-testid="dictionary-row-more"]')
    expect(moreButton.text()).toBe('更多')
    expect(moreButton.find('.el-icon').exists()).toBe(false)
    expect(wrapper.findAll('.dictionary-operation-column button').some(button => button.text() === '编辑')).toBe(false)

    wrapper.unmount()
  })
})
