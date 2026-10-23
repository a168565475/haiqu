import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import ReferenceDataSettingsView from './ReferenceDataSettingsView.vue'
import { useReferenceOptionsStore } from '@/stores/referenceOptions'

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
    managementCan: (permission: string) => fixtures.granted.has(permission),
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
  fetchSystemParameter: vi.fn().mockResolvedValue({ data: fixtures.parameters[0], etag: '"parameter-1"' }),
  updateSystemParameter: vi.fn().mockResolvedValue({ data: fixtures.parameters[0], etag: '"parameter-2"' }),
  fetchConfigReleases: vi.fn().mockResolvedValue({ data: [fixtures.release], meta: {} }),
  fetchConfigRelease: vi.fn().mockResolvedValue({ data: fixtures.release, etag: '"release-3"' }),
  publishReferenceData: vi.fn().mockResolvedValue({ data: fixtures.release, etag: '"release-4"' }),
}))

const dialogStub = {
  props: ['modelValue', 'title'],
  template: '<section v-if="modelValue" role="dialog" :aria-label="title"><slot/><slot name="footer"/></section>',
}

function mountSection(section: 'dictionary' | 'parameters') {
  const pinia = createPinia()
  const wrapper = mount(ReferenceDataSettingsView, {
    props: { section },
    global: { plugins: [pinia, ElementPlus], stubs: { ElDialog: dialogStub } },
  })
  return { wrapper, pinia, canClose: () => (wrapper.vm as unknown as { canClose: () => boolean }).canClose() }
}

describe('ReferenceDataSettingsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: vi.fn() }))
    vi.spyOn(ElMessage, 'success').mockImplementation(() => ({ close: vi.fn() }))
    fixtures.granted.clear()
    fixtures.granted.add('reference_data.view_dictionarytype')
    fixtures.granted.add('reference_data.view_referencedictionary')
    fixtures.granted.add('reference_data.view_systemparameterdefinition')
    fixtures.granted.add('reference_data.view_configrelease')
  })

  afterEach(() => {
    vi.mocked(ElMessage.warning).mockRestore()
    vi.mocked(ElMessage.success).mockRestore()
  })

  it('列表页移除统计与业务参数卡并保留字典表', async () => {
    const wrapper = mount(ReferenceDataSettingsView, { global: { plugins: [createPinia(), ElementPlus] } })
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain('CUSTOMER_LEVEL')
    expect(wrapper.text()).toContain('客户等级')
    expect(wrapper.text()).toContain('当前版本 v3')
    expect(wrapper.text()).not.toContain('customer_level')
    expect(wrapper.find('.metric-grid').exists()).toBe(false)
    expect(wrapper.find('.parameter-card').exists()).toBe(false)
    expect(wrapper.find('.dictionary-table').exists()).toBe(true)
    expect(wrapper.find('[data-testid="open-parameters"]').exists()).toBe(true)
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
  it('输入、清空和状态变化即时筛选，按钮仍可应用和重置', async () => {
    const wrapper = mount(ReferenceDataSettingsView, { global: { plugins: [createPinia(), ElementPlus] } })
    await flushPromises()
    const keywordInput = wrapper.get<HTMLInputElement>('input[placeholder="搜索字典编码、中英文名称"]')
    await keywordInput.setValue('不存在的字典')
    expect(wrapper.find('.dictionary-table').exists()).toBe(false)
    expect(wrapper.text()).toContain('当前分类暂无符合条件的字典配置')

    const filterButtons = wrapper.findAll('.erp-list-filter-actions button')
    await filterButtons.find(button => button.text() === '应用筛选')!.trigger('click')
    expect(wrapper.find('.dictionary-table').exists()).toBe(false)

    await keywordInput.setValue('')
    expect(wrapper.find('.dictionary-table').text()).toContain('CUSTOMER_LEVEL')

    const statusSelect = wrapper.findComponent({ name: 'ElSelect' })
    statusSelect.vm.$emit('update:modelValue', 'INACTIVE')
    statusSelect.vm.$emit('change', 'INACTIVE')
    await flushPromises()
    expect(wrapper.find('.dictionary-table').exists()).toBe(false)

    await filterButtons.find(button => button.text() === '重置')!.trigger('click')
    expect(wrapper.find('.dictionary-table').text()).toContain('CUSTOMER_LEVEL')
    expect(keywordInput.element.value).toBe('')
    expect(statusSelect.props('modelValue')).toBe('')
    wrapper.unmount()
  })

  it('字典独立模式保留管理、导出与发布，隐藏其他配置入口', async () => {
    fixtures.granted.add('reference_data.view_productcolor')
    fixtures.granted.add('reference_data.publish_configrelease')
    fixtures.granted.add('reference_data.add_referencedictionary')
    fixtures.granted.add('reference_data.change_dictionarytype')
    const { wrapper, canClose } = mountSection('dictionary')
    await flushPromises()

    expect(wrapper.get('h1').text()).toBe('字典配置')
    expect(wrapper.get('.dictionary-table').text()).toContain('CUSTOMER_LEVEL')
    expect(wrapper.find('a[href^="/settings/"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="open-parameters"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="parameters-section"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('导出配置')
    expect(wrapper.text()).toContain('发布配置')
    expect(wrapper.text()).toContain('批量排序')
    expect(canClose()).toBe(true)

    await wrapper.findAll('button').find(button => button.text() === '新增字典项')!.trigger('click')
    expect(canClose()).toBe(false)
    expect(ElMessage.warning).toHaveBeenCalledWith('请先保存或取消当前编辑，再关闭配置窗口。')
    await wrapper.get('[role="dialog"][aria-label="新增字典项"]').findAll('button').find(button => button.text() === '取消')!.trigger('click')
    expect(canClose()).toBe(true)
    wrapper.unmount()
  })

  it('参数独立模式直接展示参数表并保留共享版本与发布入口', async () => {
    fixtures.granted.add('reference_data.publish_configrelease')
    fixtures.granted.add('reference_data.change_systemparameterdefinition')
    const { wrapper } = mountSection('parameters')
    await flushPromises()

    expect(wrapper.find('h1').exists()).toBe(false)
    expect(wrapper.get('[data-testid="parameters-section"]').text()).toContain('默认语言')
    expect(wrapper.text()).not.toContain('当前版本')
    expect(wrapper.text()).toContain('导出配置')
    expect(wrapper.text()).toContain('发布配置')
    expect(wrapper.find('.dictionary-table').exists()).toBe(false)
    expect(wrapper.find('.category-panel').exists()).toBe(false)
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.findAllComponents({ name: 'AppWindowDialog' }).some(dialog => dialog.props('title') === '全部业务参数')).toBe(false)
    wrapper.unmount()
  })

  it('仅参数权限不请求字典汇总或发布基线，也不显示虚构版本', async () => {
    fixtures.granted.clear()
    fixtures.granted.add('reference_data.view_systemparameterdefinition')
    const api = await import('@/api/referenceData')
    const { wrapper } = mountSection('parameters')
    await flushPromises()

    expect(wrapper.text()).toContain('默认语言')
    expect(wrapper.text()).not.toContain('当前版本')
    expect(wrapper.text()).not.toContain('发布配置')
    expect(api.fetchSystemParameters).toHaveBeenCalledTimes(1)
    expect(api.fetchDictionaryTypes).not.toHaveBeenCalled()
    expect(api.fetchReferenceDataSummary).not.toHaveBeenCalled()
    expect(api.fetchConfigReleases).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each([
    ['dictionary', 'reference_data.view_systemparameterdefinition'],
    ['parameters', 'reference_data.view_dictionarytype'],
  ] as const)('%s 模式不能借另一模块权限进入', async (section, granted) => {
    fixtures.granted.clear()
    fixtures.granted.add(granted)
    const api = await import('@/api/referenceData')
    const { wrapper } = mountSection(section)
    await flushPromises()

    expect(wrapper.text()).toContain('无配置权限')
    expect(api.fetchDictionaryTypes).not.toHaveBeenCalled()
    expect(api.fetchSystemParameters).not.toHaveBeenCalled()
    expect(api.fetchReferenceDataSummary).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('参数编辑和保存期间阻止关闭，保存继续携带 ETag 且发布后失效选项缓存', async () => {
    fixtures.granted.add('reference_data.change_systemparameterdefinition')
    fixtures.granted.add('reference_data.publish_configrelease')
    const api = await import('@/api/referenceData')
    let finishSave!: () => void
    vi.mocked(api.updateSystemParameter).mockImplementationOnce(() => new Promise(resolve => {
      finishSave = () => resolve({ data: fixtures.parameters[0] as Awaited<ReturnType<typeof api.updateSystemParameter>>['data'], etag: '"parameter-2"' })
    }))
    const { wrapper, pinia, canClose } = mountSection('parameters')
    await flushPromises()
    await wrapper.get('[data-testid="parameters-section"]').findAll('button').find(button => button.text() === '编辑')!.trigger('click')
    await flushPromises()

    const editor = wrapper.get('[role="dialog"][aria-label="编辑业务参数"]')
    expect(canClose()).toBe(false)
    await editor.get('input').setValue('en-US')
    await editor.findAll('button').find(button => button.text() === '保存草稿')!.trigger('click')
    expect(api.updateSystemParameter).toHaveBeenCalledWith('parameter-language', 'en-US', '"parameter-1"')
    expect(canClose()).toBe(false)
    expect(ElMessage.warning).toHaveBeenLastCalledWith('正在处理配置变更，请稍后再关闭。')

    finishSave()
    await flushPromises()
    expect(canClose()).toBe(true)
    await wrapper.findAll('button').find(button => button.text() === '发布配置')!.trigger('click')
    await flushPromises()
    expect(api.fetchConfigRelease).toHaveBeenCalledWith('release-1')
    expect(canClose()).toBe(false)
    const publishDialog = wrapper.get('[role="dialog"][aria-label="发布配置版本"]')
    await publishDialog.get('textarea').setValue('调整默认语言')
    const options = useReferenceOptionsStore(pinia)
    const cacheGeneration = options.cacheGeneration
    await publishDialog.findAll('button').find(button => button.text() === '确认发布')!.trigger('click')
    await flushPromises()

    expect(api.publishReferenceData).toHaveBeenCalledWith('调整默认语言', '"release-3"')
    expect(options.cacheGeneration).toBe(cacheGeneration + 1)
    expect(api.fetchReferenceDataSummary).toHaveBeenCalledTimes(3)
    expect(canClose()).toBe(true)
    wrapper.unmount()
  })

})
